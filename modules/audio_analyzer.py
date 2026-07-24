import os
import re
import json
import logging
import librosa
import numpy as np
from pathlib import Path
from .file_validator import FileValidator

logger = logging.getLogger(__name__)

class AudioAnalyzer:
    # BPM and key are only meaningful for content with actual tempo/pitch.
    # Tracking which source tags produced each field lets the suppression
    # pass strip exactly those entries (not the whole source list) when the
    # final classification says the field doesn't apply.
    BPM_SOURCE_TAGS = {'filename_bpm', 'analysis_bpm', 'metadata_bpm'}
    KEY_SOURCE_TAGS = {'filename_key', 'analysis_key', 'metadata_key'}

    def __init__(self, config):
        self.config = config
        self.validator = FileValidator()

    def analyze_file(self, filepath):
        """Complete analysis of audio file"""
        result = {
            'original_path': str(filepath),
            'filename': os.path.basename(filepath),
            'bpm': None,
            'key': None,
            'genre': None,
            'type': None,
            'classification': None,
            'brightness': None,
            'duration_sec': None,
            'confidence': 0.0,
            'source': []
        }

        try:
            # Step 1: Extract existing metadata
            existing_metadata = self.validator.extract_existing_metadata(filepath)
            if existing_metadata['bpm']:
                result['bpm'] = existing_metadata['bpm']
                result['source'].append('metadata_bpm')
            if existing_metadata['key']:
                result['key'] = existing_metadata['key']
                result['source'].append('metadata_key')
            if existing_metadata['genre']:
                # Normalize through the same keyword taxonomy as filename
                # genre, don't trust the raw ID3 tag verbatim — checked
                # against this library, some files carry uncurated tags
                # like "Melodic House & Techno" or "Organic House" that
                # would otherwise create one-off folders alongside the
                # curated House/Techno/Deep buckets, fragmenting the same
                # genre across multiple differently-spelled top-level
                # folders. If the tag doesn't match any known genre,
                # falls through to filename-based detection instead of
                # trusting an arbitrary uncontrolled string.
                normalized_genre = self._extract_genre_from_path(existing_metadata['genre'])
                if normalized_genre:
                    result['genre'] = normalized_genre
                    result['source'].append('metadata_genre')

            # Get duration
            duration = self.validator.get_audio_duration(filepath)
            result['duration_sec'] = duration

            # Step 2: Try to extract from filename. Basename only, same
            # reasoning as type below: searching the full path let a parent
            # folder's track number or catalog code get read as this file's
            # BPM/key. Validated against this library — that bug both
            # fabricated values from unrelated folder numbers AND, worse,
            # silently swallowed real basename BPMs when an earlier bogus
            # match elsewhere in the path exhausted the pattern first.
            bpm_from_name = self._extract_bpm_from_name(os.path.basename(filepath))
            if bpm_from_name and not result['bpm']:
                result['bpm'] = bpm_from_name
                result['source'].append('filename_bpm')

            key_from_name = self._extract_key_from_name(os.path.basename(filepath))
            if key_from_name and not result['key']:
                result['key'] = key_from_name
                result['source'].append('filename_key')

            genre_from_name = self._extract_genre_from_path(str(filepath))
            if genre_from_name and not result['genre']:
                result['genre'] = genre_from_name
                result['source'].append('filename_genre')

            # Basename only — unlike genre (which intentionally searches the
            # full path, since genre is often only expressed via a folder
            # name), type must not pick up unrelated words from parent
            # folders. Otherwise a file named "PML_crash.wav" sitting inside
            # ".../Future Bass Track/..." gets tagged type=Bass from the
            # folder text alone, with nothing to do with the file itself.
            type_from_name = self._extract_type_from_name(os.path.basename(filepath))
            if type_from_name and not result['type']:
                result['type'] = type_from_name
                result['source'].append('filename_type')

            # Step 3: Audio analysis. Classification runs first — BPM and key
            # are only meaningful for some outcomes (see suppression rules
            # below), so knowing the classification lets us skip the
            # tempo/chroma calls entirely when they won't be kept anyway.
            try:
                y, sr = librosa.load(filepath, sr=None, mono=True)

                if not result['classification'] and duration is not None:
                    classification = self._classify_sound_type(y, sr, duration)
                    result['classification'] = classification
                    result['source'].append('analysis_classification')

                # Tempo is not a property of a single event: only a Loop has
                # a groove to measure. Skip the estimate for Oneshot/FX.
                if result['classification'] == 'Loop' and not result['bpm']:
                    bpm = self._estimate_bpm(y, sr)
                    if bpm:
                        result['bpm'] = int(bpm)
                        result['source'].append('analysis_bpm')

                # Chroma analysis always returns a dominant note even for
                # untuned percussion (a clap has no pitch center) — skip it
                # for percussive one-shots so we don't manufacture a key.
                skip_key = (result['type'] == 'Drums' and result['classification'] == 'Oneshot')
                if not skip_key and not result['key']:
                    key = self._estimate_key(y, sr)
                    if key:
                        result['key'] = key
                        result['source'].append('analysis_key')

                # Spectral brightness — unlike BPM/key, this is a property
                # every sound has (even a clap has a timbre), so it's never
                # suppressed by classification.
                brightness = self._classify_brightness(y, sr)
                if brightness:
                    result['brightness'] = brightness
                    result['source'].append('analysis_brightness')

            except Exception as e:
                logger.debug(f"Could not perform audio analysis on {filepath}: {e}")

            # Step 4: Fallback heuristic (used only when audio couldn't be loaded).
            # Duration alone can't tell a Loop from a long FX one-shot (e.g. an
            # 8s riser has no groove), so without audio signal we can only split
            # short percussive hits from "everything else long" — never guess Loop.
            if not result['classification'] and duration is not None:
                thresholds = self.config['classification_thresholds']
                short_max = thresholds['short_oneshot_max_duration_seconds']
                result['classification'] = 'Oneshot' if duration < short_max else 'FX_Oneshot_Longo'
                result['source'].append('heuristic_duration')

            # Last-resort net: duration itself unreadable (None), so neither
            # heuristic above could fire. Rather than leave classification
            # None (which later crashes path-building expecting a string),
            # default to Oneshot — the safer guess for content we know
            # nothing about.
            if not result['classification']:
                result['classification'] = 'Oneshot'
                result['source'].append('heuristic_unknown_duration')

            if not result['type']:
                result['type'] = 'Fx'  # Default type
                result['source'].append('default_type')

            if not result['genre']:
                result['genre'] = self._fallback_genre_from_pack(filepath)
                result['source'].append('default_genre')

            # Final suppression pass — authoritative regardless of source.
            # Even a "120bpm" literally in the filename, or a key embedded in
            # an ID3 tag, gets dropped if the final classification says that
            # field doesn't apply: a one-shot/FX has no tempo no matter where
            # a stray number came from, and a clap has no pitch no matter
            # what a tag claims. Absence is recorded as real None, never 0
            # or a placeholder.
            self._apply_suppression_rules(result)

            # Confidence only counts fields that actually apply to this file
            # — a one-shot isn't "less confident" for correctly having no
            # BPM, so the denominator adapts instead of penalizing it.
            applicable_fields = 3  # genre, type, brightness always apply
            if result['classification'] == 'Loop':
                applicable_fields += 1  # bpm
            if not (result['type'] == 'Drums' and result['classification'] == 'Oneshot'):
                applicable_fields += 1  # key

            resolved = len([s for s in result['source'] if s not in ('default_genre', 'default_type')])
            result['confidence'] = resolved / applicable_fields if applicable_fields else 0.0

            return result

        except Exception as e:
            logger.error(f"Error analyzing {filepath}: {e}")
            return None

    def _apply_suppression_rules(self, result):
        """
        Null out fields that aren't a property of the sound, regardless of
        which source (filename regex, embedded tag, or audio analysis)
        produced them:

          - BPM: only Loop has a tempo. Oneshot and FX_Oneshot_Longo are
            single events — a duration cutoff alone let 1.2-2s one-shots
            through with a fabricated BPM, so this checks classification
            directly instead.
          - Key: untuned percussion one-shots (kick/snare/clap/hat/perc)
            have no pitch center. Loops and FX keep key even when their
            type is Drums (a percussion loop or FX can carry a tonal
            element).
        """
        if result['classification'] in ('Oneshot', 'FX_Oneshot_Longo'):
            if result['bpm'] is not None:
                result['bpm'] = None
                result['source'] = [s for s in result['source'] if s not in self.BPM_SOURCE_TAGS]

        if result['type'] == 'Drums' and result['classification'] == 'Oneshot':
            if result['key'] is not None:
                result['key'] = None
                result['source'] = [s for s in result['source'] if s not in self.KEY_SOURCE_TAGS]

    def _estimate_bpm(self, y, sr):
        """Estimate BPM from audio using librosa"""
        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            bpm = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)[0]
            return bpm if 40 < bpm < 300 else None
        except Exception as e:
            logger.debug(f"BPM estimation failed: {e}")
            return None

    def _estimate_key(self, y, sr):
        """Estimate musical key from audio"""
        try:
            # Simple key detection based on chroma features
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            chroma_mean = np.mean(chroma, axis=1)
            key_index = np.argmax(chroma_mean)

            notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            return notes[key_index]
        except Exception as e:
            logger.debug(f"Key estimation failed: {e}")
            return None

    def _classify_sound_type(self, y, sr, duration):
        """
        3-way classification driven by behavior, not raw duration:

          Loop              - rhythmic/tonal content with a usable loop point
          Oneshot           - single short percussive hit (kick, snare, clap)
          FX_Oneshot_Longo  - single non-rhythmic event that happens to be long
                              (sweep, riser, impact, atmosphere) — NOT a loop
                              just because it's longer than a kick.

        Signals combined:
          1. Onset regularity - loops have several onsets at fairly even
             spacing (a groove); one-shots have 0-2 onsets.
          2. Loop-point similarity - compare the start and end chroma; a
             loopable file's tail resembles its head (it's built to repeat).
          3. Energy decay shape - one-shots (short or long) decay to near
             silence by the end; loops sustain or repeat energy throughout.
        """
        try:
            thresholds = self.config['classification_thresholds']
            short_max = thresholds['short_oneshot_max_duration_seconds']
            loop_sim_threshold = thresholds['loop_similarity_threshold']
            cv_threshold = thresholds['onset_regularity_cv_threshold']
            min_onsets = thresholds['min_onsets_for_rhythmic']
            tail_ratio = thresholds['tail_silence_ratio']

            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='frames')
            num_onsets = len(onset_frames)

            rms = librosa.feature.rms(y=y)[0]
            if len(rms) < 4:
                return 'Oneshot' if duration < short_max else 'FX_Oneshot_Longo'

            peak_energy = np.max(rms)
            tail_window = max(1, len(rms) // 8)
            tail_energy = np.mean(rms[-tail_window:])
            decays_to_silence = peak_energy == 0 or tail_energy < (peak_energy * tail_ratio)

            # Loop-point similarity: compare chroma of the head vs the tail
            edge_len = min(int(sr * 0.3), len(y) // 4)
            loop_similarity = 0.0
            if edge_len > 512:
                start_chroma = librosa.feature.chroma_cqt(y=y[:edge_len], sr=sr).mean(axis=1)
                end_chroma = librosa.feature.chroma_cqt(y=y[-edge_len:], sr=sr).mean(axis=1)
                norm = np.linalg.norm(start_chroma) * np.linalg.norm(end_chroma)
                if norm > 0:
                    loop_similarity = float(np.dot(start_chroma, end_chroma) / norm)

            # Onset regularity: several onsets at roughly even spacing = groove
            is_rhythmic = False
            if num_onsets >= min_onsets:
                onset_times = librosa.frames_to_time(onset_frames, sr=sr)
                intervals = np.diff(onset_times)
                if len(intervals) >= 2 and np.mean(intervals) > 0:
                    cv = np.std(intervals) / np.mean(intervals)
                    is_rhythmic = cv < cv_threshold

            if is_rhythmic and (loop_similarity > loop_sim_threshold or not decays_to_silence):
                return 'Loop'

            if num_onsets <= 2 and decays_to_silence:
                return 'Oneshot' if duration < short_max else 'FX_Oneshot_Longo'

            # Ambiguous middle ground (e.g. a few irregular onsets): fall back
            # to duration but never default to Loop without rhythmic evidence.
            if duration < short_max:
                return 'Oneshot'
            return 'Loop' if is_rhythmic else 'FX_Oneshot_Longo'

        except Exception as e:
            logger.debug(f"Sound type classification failed: {e}")
            return None

    def _classify_brightness(self, y, sr):
        """
        Spectral timbre: Escuro / Medio / Claro / Full_Spectro.

        Splits the spectrum into 3 bands (low/mid/high) and measures each
        band's share of total energy. If one band clearly dominates, the
        sound reads as dark/medium/bright; if energy is spread roughly
        evenly across all three, it's "Full_Spectro" (broadband content —
        white-noise-ish percussion, a full mix bounce, wideband risers).

        This is a separate axis from Loop/Oneshot/FX (rhythm/duration) and
        from key (pitch) — it's about where the energy sits in the
        frequency spectrum, which every sound has regardless of the other
        classifications.
        """
        try:
            bands = self.config['brightness_bands']
            low_max = bands['low_max_hz']
            mid_max = bands['mid_max_hz']
            dominance_ratio = bands['dominance_ratio']

            stft = np.abs(librosa.stft(y))
            freqs = librosa.fft_frequencies(sr=sr, n_fft=(stft.shape[0] - 1) * 2)
            energy = np.sum(stft ** 2, axis=1)
            total_energy = np.sum(energy)
            if total_energy <= 0:
                return None

            low_energy = np.sum(energy[freqs < low_max])
            mid_energy = np.sum(energy[(freqs >= low_max) & (freqs < mid_max)])
            high_energy = np.sum(energy[freqs >= mid_max])

            low_pct = low_energy / total_energy
            mid_pct = mid_energy / total_energy
            high_pct = high_energy / total_energy

            band_pcts = {'Escuro': low_pct, 'Medio': mid_pct, 'Claro': high_pct}
            dominant_label = max(band_pcts, key=band_pcts.get)
            dominant_pct = band_pcts[dominant_label]

            # No single band clearly leads -> energy is spread broadband
            if dominant_pct < dominance_ratio:
                return 'Full_Spectro'
            return dominant_label

        except Exception as e:
            logger.debug(f"Brightness classification failed: {e}")
            return None

    def _extract_bpm_from_name(self, filename):
        """Extract BPM from filename using regex patterns"""
        patterns = self.config['bpm_patterns']
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                try:
                    bpm = int(match.group(1))
                    if 40 < bpm < 300:
                        return bpm
                except:
                    pass
        return None

    def _extract_key_from_name(self, filename):
        """Extract key from filename using regex patterns"""
        patterns = self.config['key_patterns']
        valid_keys = ['C', 'C#', 'Db', 'D', 'D#', 'Eb', 'E', 'F', 'F#', 'Gb', 'G', 'G#', 'Ab', 'A', 'A#', 'Bb', 'B',
                      'Cm', 'C#m', 'Dbm', 'Dm', 'D#m', 'Ebm', 'Em', 'Fm', 'F#m', 'Gbm', 'Gm', 'G#m', 'Abm', 'Am', 'A#m', 'Bbm', 'Bm']

        # Full note-name spelling ("Cmin", "D#Maj", "Ebmin") — checked first
        # since it's even less ambiguous than a single-letter tag. Validated
        # against this library: 932 real audio filenames use this exact
        # convention and it was previously unrecognized entirely — the
        # bracket/underscore single-letter patterns below can't match a
        # 4-6 character token like "Cmin". Needs its own capture-and-build
        # step (not just "is the capture group in valid_keys") because the
        # min/maj suffix has to become the "m" suffix or no suffix.
        full_match = re.search(r'([A-G])([#b]?)(min|maj)', filename, re.IGNORECASE)
        if full_match:
            letter = full_match.group(1).upper()
            accidental = '#' if full_match.group(2) == '#' else ('b' if full_match.group(2) else '')
            key = f"{letter}{accidental}m" if full_match.group(3).lower() == 'min' else f"{letter}{accidental}"
            if key in valid_keys:
                return key

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                key = match.group(1).strip()
                if key in valid_keys:
                    return key
        return None

    # Real-data check (166,808 files across all 3 source folders): these
    # top-level names aren't packs themselves, they're aggregator folders
    # that bundle many distinct packs one level down (e.g. every Splice
    # download lands under a shared "SPLICE" folder; "AlgonautContent" is
    # a plugin's own content root with "Packs Installed" inside it holding
    # the real pack names). Using them verbatim would dump ~38k files
    # across only 3 fallback "genres" instead of their real pack names.
    GENERIC_PACK_CONTAINERS = {
        'splice', 'slate samples', 'algonautcontent', 'packs installed',
    }

    def _resolve_pack_name(self, filepath):
        """Return the source pack's own folder name for a file, skipping
        generic aggregator folders (see GENERIC_PACK_CONTAINERS). Returns
        None if the file has no pack folder to name it after (sits
        directly in the source root) or the source dir isn't known."""
        source_dir = self.config.get('_source_dir')
        if not source_dir:
            return None

        try:
            rel = Path(filepath).resolve().relative_to(source_dir)
        except ValueError:
            return None

        parts = rel.parts[:-1]  # drop the filename itself
        if not parts:
            return None

        for part in parts:
            if part.lower() not in self.GENERIC_PACK_CONTAINERS:
                return part
        return parts[-1]

    def _fallback_genre_from_pack(self, filepath):
        """When no genre keyword matches, resolve the source pack's own
        folder name to a real genre first (see `pack_genre_overrides` in
        genre_mapping.json — populated by researching artist/label/pack
        names that don't self-describe their genre, e.g. 'Deadmau5' ->
        'Progressive House'). If the pack has no researched genre yet,
        fall back to the pack folder name itself (e.g. 'Maschine Samples')
        instead of a meaningless generic bucket — a real library name is
        more useful for browsing than 'Outros'."""
        pack_name = self._resolve_pack_name(filepath)
        if pack_name is None:
            return 'Outros'

        overrides = self.config.get('pack_genre_overrides', {})
        researched_genre = overrides.get(pack_name) or overrides.get(pack_name.lower())
        return researched_genre or pack_name

    def _extract_genre_from_path(self, filepath):
        """Extract genre from file path"""
        genre_keywords = self.config['genre_keywords']
        path_lower = str(filepath).lower()

        for genre, keywords in genre_keywords.items():
            for keyword in keywords:
                if keyword.lower() in path_lower:
                    return genre

        return None

    def _extract_type_from_name(self, filename):
        """Extract sound type from filename"""
        type_keywords = self.config['type_keywords']
        name_lower = str(filename).lower()

        for type_name, keywords in type_keywords.items():
            for keyword in keywords:
                if keyword.lower() in name_lower:
                    return type_name

        return None
