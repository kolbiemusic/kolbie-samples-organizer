import os
import shutil
import logging
from pathlib import Path
from .file_validator import FileValidator

logger = logging.getLogger(__name__)

class FileOrganizer:
    BPM_RANGES = [
        (70, 85, '70-85_bpm'),
        (85, 100, '85-100_bpm'),
        (100, 110, '100-110_bpm'),
        (110, 120, '110-120_bpm'),
        (120, 130, '120-130_bpm'),
        (130, 145, '130-145_bpm'),
        (145, 160, '145-160_bpm'),
        (160, 300, '160+_bpm')
    ]

    # FX one-shots (sweeps, risers, impacts) have no tempo, so they're
    # bucketed by duration instead of BPM — browsing "a long atmosphere"
    # vs "a short impact" beats a meaningless BPM guess.
    DURATION_RANGES_FX = [
        (0, 3, '0-3s'),
        (3, 8, '3-8s'),
        (8, 20, '8-20s'),
        (20, float('inf'), '20s+')
    ]

    FX_CLASSIFICATION = 'FX_Oneshot_Longo'

    def __init__(self, destination_root):
        self.destination_root = Path(destination_root)
        self.validator = FileValidator()
        self.copied_files = []
        self.failed_files = []

    def calculate_destination_path(self, metadata):
        """Calculate destination path based on metadata"""
        genre = metadata.get('genre', 'Outros')
        type_name = metadata.get('type', 'Fx')
        classification = metadata.get('classification', 'Oneshot')
        bpm = metadata.get('bpm')
        duration = metadata.get('duration_sec')

        # Sanitize paths
        genre = self._sanitize_path(genre)
        type_name = self._sanitize_path(type_name)
        classification = self._sanitize_path(classification)

        if classification == self._sanitize_path(self.FX_CLASSIFICATION):
            # FX one-shots have no tempo — group by duration instead of BPM
            last_dir = 'unknown_duration'
            if duration is not None:
                for min_d, max_d, range_str in self.DURATION_RANGES_FX:
                    if min_d <= duration < max_d:
                        last_dir = range_str
                        break
        else:
            last_dir = 'unknown_bpm'
            if bpm:
                for min_bpm, max_bpm, range_str in self.BPM_RANGES:
                    if min_bpm <= bpm < max_bpm:
                        last_dir = range_str
                        break

        path = self.destination_root / genre / type_name / classification / last_dir
        return path

    def generate_new_filename(self, original_filename, metadata):
        """
        Generate new filename with metadata suffix. BPM/key brackets are
        only appended when the value is real — a suppressed or unknown
        field (None) is omitted entirely rather than shown as a "[_]"
        placeholder, so the filename never implies data that isn't there.
        """
        base_name = Path(original_filename).stem
        ext = Path(original_filename).suffix

        bpm = metadata.get('bpm')
        key = metadata.get('key')
        brightness = metadata.get('brightness')

        tags = []
        if isinstance(bpm, int):
            tags.append(f"[{bpm} bpm]")
        if isinstance(key, str) and key:
            tags.append(f"[{key}]")
        if isinstance(brightness, str) and brightness:
            tags.append(f"[{brightness}]")

        suffix = (" " + " ".join(tags)) if tags else ""
        new_name = f"{base_name}{suffix}{ext}"

        # Truncate if too long (macOS limit is 255 chars)
        if len(new_name) > 200:
            reserved = len(" [...]") + len(suffix) + len(ext)
            truncate_len = max(200 - reserved, 10)
            new_name = f"{base_name[:truncate_len]} [...]{suffix}{ext}"

        return new_name

    def copy_file(self, source_path, metadata):
        """Copy file to destination with new name"""
        try:
            source_path = Path(source_path)
            dest_dir = self.calculate_destination_path(metadata)
            new_filename = self.generate_new_filename(source_path.name, metadata)
            dest_path = dest_dir / new_filename

            # Create destination directory
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Check if file already exists in destination (duplicated)
            if dest_path.exists():
                logger.info(f"File already exists in destination: {dest_path}")
                return None

            # Copy file
            shutil.copy2(source_path, dest_path)

            # Verify file was copied correctly
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

    def ensure_no_duplicates_in_dest(self):
        """Check for duplicates in destination folder"""
        logger.info("Checking for duplicates in destination...")
        all_files = list(self.destination_root.rglob('*'))
        audio_files = [f for f in all_files if f.is_file() and f.suffix.lower() in {'.wav', '.aif', '.aiff', '.flac', '.mp3'}]
        duplicates = self.validator.find_duplicates(audio_files)
        return duplicates

    def _sanitize_path(self, path_str):
        """Remove invalid characters from path"""
        # Remove invalid filesystem characters
        invalid_chars = '<>:"|?*'
        for char in invalid_chars:
            path_str = path_str.replace(char, '')
        path_str = path_str.strip()
        return path_str if path_str else 'Outros'

    def get_stats(self):
        """Get migration statistics"""
        return {
            'copied': len(self.copied_files),
            'failed': len(self.failed_files),
            'total_dest_files': len(list(self.destination_root.rglob('*')))
        }
