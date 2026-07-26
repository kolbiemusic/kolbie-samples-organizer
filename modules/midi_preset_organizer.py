"""
Destination path/filename/copy logic for the MIDI + Presets pipeline.

Deliberately NOT a subclass of FileOrganizer — that class's BPM/duration
bucketing is audio-specific and doesn't apply here, and inheriting just to
reach its copy_file() would couple two unrelated taxonomies. The generic
*shape* (mkdir -> exists-check -> copy -> verify size -> track) is
reproduced here instead, with one addition: preset filenames collide a lot
across unrelated packs ("Init.fxp", "Default.vital" recur constantly).
FileOrganizer's plain "dest exists -> skip" would silently drop the second,
different, file. Here, an existing destination is only treated as "already
migrated" when its content hash matches; a same-name-different-content
collision gets a short hash suffix instead of being dropped.
"""
import logging
import shutil
from pathlib import Path

from .file_validator import FileValidator

logger = logging.getLogger(__name__)


class MidiPresetOrganizer:
    TEMPO_RANGES = [
        (70, 85, '70-85_bpm'),
        (85, 100, '85-100_bpm'),
        (100, 110, '100-110_bpm'),
        (110, 120, '110-120_bpm'),
        (120, 130, '120-130_bpm'),
        (130, 145, '130-145_bpm'),
        (145, 160, '145-160_bpm'),
        (160, 300, '160+_bpm'),
    ]

    def __init__(self, destination_root):
        self.destination_root = Path(destination_root)
        self.validator = FileValidator()
        self.copied_files = []
        self.skipped_files = []
        self.failed_files = []

    def calculate_destination_path(self, metadata):
        kind = metadata.get('kind')
        genre = self._sanitize_path(metadata.get('genre') or 'Outros')
        category = self._sanitize_path(metadata.get('category') or 'Uncategorized')

        if kind == 'midi':
            # Bucket by tempo_bpm whenever it exists, regardless of whether
            # it came from a Set Tempo meta-event or a filename-regex
            # fallback — both are real numbers worth organizing by, only
            # "no tempo found anywhere" falls to unknown_tempo.
            tempo = metadata.get('tempo_bpm')
            tempo_bucket = 'unknown_tempo'
            if tempo:
                for min_t, max_t, range_str in self.TEMPO_RANGES:
                    if min_t <= tempo < max_t:
                        tempo_bucket = range_str
                        break
            timesig = metadata.get('time_signature') or 'unknown_timesig'
            timesig_dir = self._sanitize_path(timesig.replace('/', '-'))
            return self.destination_root / 'MIDI' / genre / category / tempo_bucket / timesig_dir

        if kind == 'preset':
            # Synth/plugin is the primary browsing axis for presets (user
            # picks the plugin they're using first, then narrows by genre/
            # sound type within it) — reversed from the audio/MIDI trees,
            # where genre leads. See DECISIONS.md for the full rationale.
            plugin_family = self._sanitize_path(metadata.get('plugin_family') or 'Unknown_Plugin')
            return self.destination_root / 'Presets' / plugin_family / genre / category

        return self.destination_root / '_UNCLASSIFIED'

    def generate_new_filename(self, original_filename, metadata):
        base_name = Path(original_filename).stem
        ext = Path(original_filename).suffix
        kind = metadata.get('kind')

        tags = []
        if kind == 'midi':
            # Show the tag for any real tempo (meta-event OR filename
            # fallback) — has_tempo_meta still distinguishes "exact" from
            # "read from the name" in the CSV/JSON, but both are real
            # values worth displaying, not placeholders.
            tempo = metadata.get('tempo_bpm')
            if isinstance(tempo, (int, float)):
                tags.append(f"[{tempo:g} bpm]")
            key = metadata.get('key')
            if isinstance(key, str) and key:
                # "~" only marks the heuristic pitch-class estimate. A key
                # read from the meta-event or the filename itself is an
                # explicit signal, not a guess — no caveat needed, same as
                # the audio pipeline's [key] from a real ID3 tag.
                is_heuristic = 'key_note_analysis' in metadata.get('source', [])
                tags.append(f"[{key}~]" if is_heuristic else f"[{key}]")
            bars = metadata.get('duration_bars')
            if isinstance(bars, (int, float)):
                tags.append(f"[{bars:g}bars]")

        suffix = (" " + " ".join(tags)) if tags else ""
        new_name = f"{base_name}{suffix}{ext}"

        if len(new_name) > 200:
            reserved = len(" [...]") + len(suffix) + len(ext)
            truncate_len = max(200 - reserved, 10)
            new_name = f"{base_name[:truncate_len]} [...]{suffix}{ext}"

        return new_name

    def _disambiguate(self, dest_path, content_hash):
        """Append a short content-hash suffix so a same-name-different-content collision keeps both files."""
        suffix_tag = (content_hash or 'dup')[:6]
        stem, ext = dest_path.stem, dest_path.suffix
        candidate = dest_path.parent / f"{stem} [{suffix_tag}]{ext}"
        n = 1
        while candidate.exists():
            candidate = dest_path.parent / f"{stem} [{suffix_tag}-{n}]{ext}"
            n += 1
        return candidate

    def copy_file(self, source_path, metadata):
        try:
            source_path = Path(source_path)
            dest_dir = self.calculate_destination_path(metadata)
            new_filename = self.generate_new_filename(source_path.name, metadata)
            dest_path = dest_dir / new_filename

            dest_dir.mkdir(parents=True, exist_ok=True)

            content_hash = metadata.get('content_hash')

            if dest_path.exists():
                existing_hash = self.validator.get_file_hash(dest_path) if content_hash else None
                if content_hash and existing_hash == content_hash:
                    logger.info(f"File already exists in destination (same content, skipping): {dest_path}")
                    self.skipped_files.append(str(dest_path))
                    return None
                # Same computed name, different content — don't drop the file.
                dest_path = self._disambiguate(dest_path, content_hash)
                logger.info(f"Name collision with different content — disambiguated to: {dest_path}")

            shutil.copy2(source_path, dest_path)

            if dest_path.exists() and dest_path.stat().st_size == source_path.stat().st_size:
                self.copied_files.append(str(dest_path))
                return str(dest_path)
            else:
                logger.error(f"File copy verification failed for {source_path}")
                self.failed_files.append(str(source_path))
                return None

        except Exception as e:
            logger.error(f"Error copying file {source_path}: {e}")
            self.failed_files.append(str(source_path))
            return None

    def _sanitize_path(self, path_str):
        invalid_chars = '<>:"|?*'
        for char in invalid_chars:
            path_str = path_str.replace(char, '')
        path_str = path_str.strip()
        return path_str if path_str else 'Outros'

    def get_stats(self):
        return {
            'copied': len(self.copied_files),
            'skipped': len(self.skipped_files),
            'failed': len(self.failed_files),
            'total_dest_files': len(list(self.destination_root.rglob('*'))),
        }
