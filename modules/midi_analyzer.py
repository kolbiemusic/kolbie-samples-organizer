"""
MIDI metadata extraction via mido.

MIDI is symbolic data, not a waveform — librosa doesn't apply here. Tempo
and time signature come from exact meta-events (Set Tempo / Time Signature)
when present — but 93.5% of this library's real .mid files have no Set
Tempo meta-event at all (most DAWs just don't export one), so tempo falls
back to the same filename-regex extraction as the audio pipeline (reusing
its corrected patterns) whenever the meta-event is missing. Key follows a
similar precedence: an explicit key in the filename is the producer's own
stated intent, checked first; only when the name has nothing does key fall
back to a genuine heuristic — a pitch-class histogram correlated against
Krumhansl-Kessler major/minor profiles, same family of technique as
chroma-based key detection in audio, applied to exact note data instead of
a waveform. Because that fallback is a guess, it's flagged with a
confidence score and the caller (file_organizer-equivalent) tags it with
"~" in filenames rather than presenting it as ground truth — a
filename-derived or meta-event key gets no such caveat, since both are
explicit rather than inferred.

Each field is extracted in its own try/except. DECISIONS.md documents a
real bug in the audio pipeline where a single blanket except around a
librosa call silently dropped BPM coverage from 96.5% to 25% — the fix
there, and the pattern followed here, is field-level error isolation so
one broken meta-event doesn't null out everything else in the file.
"""
import logging
import re
from pathlib import Path

import mido

from .genre_matcher import extract_genre_from_path, fallback_genre_from_pack
from .category_matcher import extract_category_from_filename

logger = logging.getLogger(__name__)

# 93.5% of this library's real .mid files carry no Set Tempo meta-event at
# all (checked against a 400-file random sample) — MIDI export from most
# DAWs just doesn't embed one. But ~28% of those have the tempo spelled out
# in the filename itself ("PML_Telekinesis_127bpm Amin_Pad.mid"), currently
# discarded entirely. Reuses the SAME corrected bpm_patterns/key_patterns
# from genre_mapping.json (read-only) that fixed the audio pipeline's
# equivalent extraction — not the old buggy version.
_VALID_KEYS = ['C', 'C#', 'Db', 'D', 'D#', 'Eb', 'E', 'F', 'F#', 'Gb', 'G', 'G#', 'Ab', 'A', 'A#', 'Bb', 'B',
               'Cm', 'C#m', 'Dbm', 'Dm', 'D#m', 'Ebm', 'Em', 'Fm', 'F#m', 'Gbm', 'Gm', 'G#m', 'Abm', 'Am', 'A#m', 'Bbm', 'Bm']


def _extract_bpm_from_filename(filename, bpm_patterns):
    for pattern in bpm_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            try:
                bpm = int(match.group(1))
                if 40 < bpm < 300:
                    return bpm
            except (ValueError, IndexError):
                pass
    return None


def _extract_key_from_filename(filename, key_patterns):
    # Full note-name spelling ("Amin", "F#min", "D#Maj") first — checked
    # against this library, 273 real MIDI/preset filenames use this
    # convention and it's more explicit than a single bracketed/underscored
    # letter, so it outranks the generic key_patterns below. Needs its own
    # capture-and-build step since the min/maj suffix has to become the
    # trailing "m" or nothing, not just a raw capture-group lookup.
    full_match = re.search(r'([A-G])([#b]?)(min|maj)', filename, re.IGNORECASE)
    if full_match:
        letter = full_match.group(1).upper()
        accidental = '#' if full_match.group(2) == '#' else ('b' if full_match.group(2) else '')
        key = f"{letter}{accidental}m" if full_match.group(3).lower() == 'min' else f"{letter}{accidental}"
        if key in _VALID_KEYS:
            return key

    for pattern in key_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            key = match.group(1).strip()
            if key in _VALID_KEYS:
                return key
    return None

# Krumhansl-Kessler key profiles — standard reference weights for how
# strongly each scale degree "belongs" to a major/minor key, index 0 = tonic.
_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_PITCH_CLASS_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_MIN_NOTES_FOR_KEY = 8


def _correlate(a, b):
    n = len(a)
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    den_a = sum((a[i] - mean_a) ** 2 for i in range(n)) ** 0.5
    den_b = sum((b[i] - mean_b) ** 2 for i in range(n)) ** 0.5
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / (den_a * den_b)


def _estimate_key(pitch_class_counts):
    """Best-fit major/minor key by Krumhansl-Kessler correlation. Returns (key_str, confidence) or (None, 0.0)."""
    total_notes = sum(pitch_class_counts)
    if total_notes < _MIN_NOTES_FOR_KEY:
        return None, 0.0

    best_key, best_score = None, -2.0
    for tonic in range(12):
        for mode, profile in (('maj', _MAJOR_PROFILE), ('min', _MINOR_PROFILE)):
            rotated = profile[-tonic:] + profile[:-tonic]
            score = _correlate(pitch_class_counts, rotated)
            if score > best_score:
                best_score = score
                suffix = '' if mode == 'maj' else 'm'
                best_key = f"{_PITCH_CLASS_NAMES[tonic]}{suffix}"

    confidence = max(0.0, min(1.0, best_score))
    return best_key, confidence


class MidiAnalyzer:
    def __init__(self, config=None, genre_keywords=None, category_keywords=None,
                 bpm_patterns=None, key_patterns=None, source_dir=None,
                 pack_genre_overrides=None):
        self.config = config or {}
        self.genre_keywords = genre_keywords or {}
        self.category_keywords = category_keywords or {}
        self.source_dir = source_dir
        self.pack_genre_overrides = pack_genre_overrides or {}
        # Only the pattern(s) that require a literal "bpm" marker — the
        # shared bracket/underscore bare-number fallbacks are reliable for
        # audio samples (validated: 30/30 correct there) but NOT for this
        # library's MIDI naming, where a real pack ("PML_MIDIQ_Stab_Melody_
        # 56_Amin_EDM.mid") uses sequential track numbers in the exact same
        # underscore-flanked shape and got "56 bpm" fabricated from a track
        # index. Filtering here means passing the full shared config list is
        # always safe, regardless of what the caller has.
        self.bpm_patterns = [p for p in (bpm_patterns or []) if 'bpm' in p.lower()]
        self.key_patterns = key_patterns or []

    def is_valid_midi(self, filepath):
        """Check the file opens as MIDI. Empty tracks/no notes are still valid — just useless."""
        try:
            mido.MidiFile(filepath, clip=True)
            return True
        except Exception as e:
            logger.warning(f"Invalid MIDI file {filepath}: {e}")
            return False

    def analyze_file(self, filepath):
        filepath = str(filepath)
        result = {
            'original_path': filepath,
            'filename': Path(filepath).name,
            'genre': None,
            'category': 'Uncategorized',
            'tempo_bpm': None,
            'has_tempo_meta': False,
            'time_signature': None,
            'key': None,
            'key_confidence': 0.0,
            'track_names': [],
            'num_tracks': 0,
            'duration_sec': None,
            'duration_bars': None,
            'confidence': 0.0,
            'source': [],
        }

        try:
            genre = extract_genre_from_path(filepath, self.genre_keywords)
            if genre:
                result['genre'] = genre
                result['source'].append('filename_genre')
            else:
                result['genre'] = fallback_genre_from_pack(filepath, self.source_dir, self.pack_genre_overrides)
                result['source'].append('default_genre')
        except Exception as e:
            logger.debug(f"Could not determine genre for {filepath}: {e}")
            result['genre'] = 'Outros'

        try:
            category = extract_category_from_filename(result['filename'], self.category_keywords)
            if category:
                result['category'] = category
                result['source'].append('filename_category')
        except Exception as e:
            logger.debug(f"Could not determine category for {filepath}: {e}")

        try:
            mid = mido.MidiFile(filepath, clip=True)
        except Exception as e:
            logger.warning(f"Could not open MIDI file {filepath}: {e}")
            return result

        result['num_tracks'] = len(mid.tracks)

        try:
            result['track_names'] = [
                msg.name for track in mid.tracks for msg in track
                if msg.is_meta and msg.type == 'track_name' and msg.name.strip()
            ]
        except Exception as e:
            logger.debug(f"Could not read track names from {filepath}: {e}")

        try:
            tempo_msg = next(
                (msg for track in mid.tracks for msg in track
                 if msg.is_meta and msg.type == 'set_tempo'),
                None
            )
            if tempo_msg is not None:
                result['tempo_bpm'] = round(mido.tempo2bpm(tempo_msg.tempo), 2)
                result['has_tempo_meta'] = True
                result['source'].append('tempo_meta_event')
        except Exception as e:
            logger.debug(f"Could not read tempo from {filepath}: {e}")

        # Fallback only when there's no real meta-event — the meta-event,
        # when present, is exact and always wins.
        if not result['has_tempo_meta']:
            try:
                bpm_from_name = _extract_bpm_from_filename(result['filename'], self.bpm_patterns)
                if bpm_from_name:
                    result['tempo_bpm'] = bpm_from_name
                    result['source'].append('filename_bpm')
            except Exception as e:
                logger.debug(f"Could not extract tempo from filename for {filepath}: {e}")

        numerator, denominator = None, None
        try:
            timesig_msg = next(
                (msg for track in mid.tracks for msg in track
                 if msg.is_meta and msg.type == 'time_signature'),
                None
            )
            if timesig_msg is not None:
                numerator, denominator = timesig_msg.numerator, timesig_msg.denominator
                result['time_signature'] = f"{numerator}/{denominator}"
                result['source'].append('time_signature_meta_event')
        except Exception as e:
            logger.debug(f"Could not read time signature from {filepath}: {e}")

        try:
            result['duration_sec'] = round(mid.length, 2)
        except Exception as e:
            logger.debug(f"Could not compute duration for {filepath}: {e}")

        # Gated on tempo_bpm existing at all (meta-event OR filename), not
        # specifically has_tempo_meta — a filename-sourced tempo is still a
        # real number worth deriving a bar count from, just not exact.
        if result['tempo_bpm'] and numerator and denominator and result['duration_sec']:
            try:
                seconds_per_beat = 60.0 / result['tempo_bpm']
                beats_per_bar = numerator * (4.0 / denominator)
                bar_duration = seconds_per_beat * beats_per_bar
                if bar_duration > 0:
                    result['duration_bars'] = round(result['duration_sec'] / bar_duration, 2)
            except Exception as e:
                logger.debug(f"Could not compute duration_bars for {filepath}: {e}")

        # Filename key first: it's the producer's own stated intent, not a
        # statistical guess — checked against this library, note-analysis
        # and an explicit filename key sometimes disagree (e.g. a file
        # literally named "...Fmin.mid" that note-analysis guessed as C#),
        # and the filename is the more trustworthy of the two. Note-based
        # estimation only runs as a fallback when the name has nothing.
        try:
            key_from_name = _extract_key_from_filename(result['filename'], self.key_patterns)
            if key_from_name:
                result['key'] = key_from_name
                result['key_confidence'] = 1.0
                result['source'].append('filename_key')
        except Exception as e:
            logger.debug(f"Could not extract key from filename for {filepath}: {e}")

        if not result['key']:
            try:
                pitch_class_counts = [0] * 12
                for track in mid.tracks:
                    for msg in track:
                        if msg.type == 'note_on' and msg.velocity > 0:
                            pitch_class_counts[msg.note % 12] += 1
                key, key_confidence = _estimate_key(pitch_class_counts)
                if key:
                    result['key'] = key
                    result['key_confidence'] = round(key_confidence, 2)
                    result['source'].append('key_note_analysis')
            except Exception as e:
                logger.debug(f"Could not estimate key for {filepath}: {e}")

        tempo_weight = 0.6 if result['has_tempo_meta'] else (0.3 if 'filename_bpm' in result['source'] else 0.0)
        result['confidence'] = round(tempo_weight + (0.4 * result['key_confidence']), 2)

        return result
