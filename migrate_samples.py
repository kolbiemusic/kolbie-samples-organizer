#!/usr/bin/env python3
"""
KOLBIE SAMPLES - Audio File Organizer and Metadata Extractor

Migrates and organizes large audio sample collections with automatic
metadata extraction (BPM, tonalidade, gênero, Loop vs One-shot).

Usage:
    python migrate_samples.py \
      --source-dir "/path/to/source" \
      --destination "/path/to/dest" \
      --dry-run
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm
import colorlog

from modules import AudioAnalyzer, FileValidator, FileOrganizer, Reporter

# Configure logging
def setup_logging(verbose=False, log_dir='logs'):
    Path(log_dir).mkdir(exist_ok=True)

    log_level = logging.DEBUG if verbose else logging.INFO

    # Console handler with colors
    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s[%(levelname)s]%(reset)s %(message)s',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    ))

    # File handler
    file_handler = logging.FileHandler(f'{log_dir}/migration.log')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return logging.getLogger(__name__)

logger = setup_logging()

# --- Parallel analysis worker (runs in child processes) ---
#
# ProcessPoolExecutor needs a top-level, picklable callable — an instance
# method on SampleMigrator won't work here because the whole instance (with
# its logging handlers etc.) would have to be pickled. Instead each worker
# process builds its own AudioAnalyzer once (via `initializer`) and reuses
# it for every file that lands on that worker, avoiding per-file setup cost.
#
# Analysis is CPU-bound (STFT, chroma, onset detection per file are all
# independent of each other), so this is the phase that benefits from
# multiple processes — threads wouldn't help due to the GIL. Validation and
# copy stay sequential: validation is light I/O, and copy throughput is
# capped by the disks, not the CPU, so parallel copy risks thrashing an HDD
# instead of speeding anything up.
_worker_analyzer = None

def _init_worker(config):
    global _worker_analyzer
    # Child processes (spawned, not forked, on macOS) start with no logging
    # configuration — keep it minimal here (warnings/errors to stderr only)
    # rather than duplicating file handlers across processes, which would
    # interleave writes to the same log file.
    logging.basicConfig(level=logging.WARNING)
    _worker_analyzer = AudioAnalyzer(config)

def _analyze_worker(filepath):
    return _worker_analyzer.analyze_file(filepath)

class SampleMigrator:
    def __init__(self, config_path='config/genre_mapping.json'):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.analyzer = AudioAnalyzer(self.config)
        self.validator = FileValidator()
        self.organizer = None
        self.reporter = None

    def validate_paths(self, source_dir, destination_dir):
        """Validate source and destination paths"""
        source_path = Path(source_dir)
        dest_path = Path(destination_dir)

        if not source_path.exists():
            logger.error(f"Source directory does not exist: {source_dir}")
            return False

        dest_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Source: {source_path}")
        logger.info(f"Destination: {dest_path}")
        return True

    def find_audio_files(self, source_dir):
        """Find all audio files in source directory"""
        source_path = Path(source_dir)
        audio_extensions = {'.wav', '.aif', '.aiff', '.flac', '.mp3'}

        audio_files = []
        for ext in audio_extensions:
            audio_files.extend(source_path.rglob(f'*{ext}'))
            audio_files.extend(source_path.rglob(f'*{ext.upper()}'))

        return sorted(list(set(audio_files)))

    def run_validation_phase(self, audio_files):
        """Phase 1: Validate and clean audio files"""
        logger.info("=" * 60)
        logger.info("PHASE 1: VALIDATION & CLEANING")
        logger.info("=" * 60)

        valid_files = []
        logger.info(f"Validating {len(audio_files)} audio files...")

        for filepath in tqdm(audio_files, desc="Validating"):
            if self.validator.is_valid_audio(filepath):
                valid_files.append(filepath)

        logger.info(f"✓ Valid files: {len(valid_files)}/{len(audio_files)}")
        logger.info(f"✗ Invalid files: {len(audio_files) - len(valid_files)}")

        # Find duplicates
        logger.info("Scanning for duplicate files...")
        duplicates = self.validator.find_duplicates(valid_files)
        logger.info(f"Found {len(duplicates)} duplicate sets")

        # Summary
        logger.info(f"Files to process: {len(valid_files)}")
        return valid_files

    def run_analysis_phase(self, audio_files, num_workers=1):
        """Phase 2: Analyze audio files (parallel across processes when num_workers > 1)"""
        logger.info("=" * 60)
        logger.info("PHASE 2: AUDIO ANALYSIS")
        logger.info("=" * 60)

        metadata_list = []
        logger.info(f"Analyzing {len(audio_files)} audio files ({num_workers} worker{'s' if num_workers != 1 else ''})...")

        # str() paths: Path objects pickle fine, but keeping this explicit
        # since it's what crosses the process boundary on every task.
        file_paths = [str(f) for f in audio_files]

        if num_workers <= 1:
            for filepath in tqdm(file_paths, desc="Analyzing"):
                metadata = self.analyzer.analyze_file(filepath)
                if metadata:
                    metadata_list.append(metadata)
        else:
            # chunksize > 1 cuts inter-process round trips — with ~20k fast
            # (~0.3s) tasks, sending one file per IPC message dominates
            # overhead. ~4 chunks per worker balances load without letting
            # one slow chunk stall a worker for too long.
            chunksize = max(1, len(file_paths) // (num_workers * 4))
            with ProcessPoolExecutor(
                max_workers=num_workers,
                initializer=_init_worker,
                initargs=(self.config,)
            ) as executor:
                results = executor.map(_analyze_worker, file_paths, chunksize=chunksize)
                for metadata in tqdm(results, total=len(file_paths), desc="Analyzing"):
                    if metadata:
                        metadata_list.append(metadata)

        logger.info(f"✓ Analyzed: {len(metadata_list)}/{len(audio_files)}")

        # Statistics
        genres = {}
        for m in metadata_list:
            genre = m.get('genre', 'Unknown')
            genres[genre] = genres.get(genre, 0) + 1

        logger.info("Genre distribution:")
        for genre, count in sorted(genres.items()):
            logger.info(f"  {genre}: {count}")

        return metadata_list

    def run_migration_phase(self, metadata_list, destination_dir, dry_run=False):
        """Phase 5: Copy and rename files"""
        logger.info("=" * 60)
        logger.info("PHASE 5: MIGRATION")
        logger.info("=" * 60)

        self.organizer = FileOrganizer(destination_dir)
        self.reporter = Reporter(destination_dir)

        if dry_run:
            logger.warning("DRY RUN MODE - No files will be copied")

        copied = 0
        failed = 0

        for metadata in tqdm(metadata_list, desc="Migrating"):
            self.reporter.add_file_metadata(metadata)

            if not dry_run:
                source_path = metadata.get('original_path')
                result = self.organizer.copy_file(source_path, metadata)

                if result:
                    metadata['new_path'] = result
                    copied += 1
                else:
                    failed += 1

        logger.info(f"✓ Copied: {copied}")
        logger.info(f"✗ Failed: {failed}")

        return self.reporter

    def run_reporting_phase(self, reporter):
        """Phase 6: Generate reports"""
        logger.info("=" * 60)
        logger.info("PHASE 6: REPORTING")
        logger.info("=" * 60)

        if not reporter:
            logger.warning("No reporter available")
            return

        stats = self.organizer.get_stats() if self.organizer else {'copied': 0, 'failed': 0}

        # Generate CSV
        csv_path = reporter.generate_csv_index()
        if csv_path:
            logger.info(f"✓ CSV index: {csv_path}")

        # Generate JSON
        json_path = reporter.generate_json_metadata()
        if json_path:
            logger.info(f"✓ JSON metadata: {json_path}")

        # Generate HTML
        html_path = reporter.generate_html_report(stats)
        if html_path:
            logger.info(f"✓ HTML report: {html_path}")

    def run(self, source_dir, destination_dir, dry_run=False, sample_size=None, num_workers=1):
        """Execute complete migration"""
        logger.info("🎵 KOLBIE SAMPLES - Migration Started")
        logger.info(f"Dry run: {dry_run}")

        # Validate paths
        if not self.validate_paths(source_dir, destination_dir):
            return False

        # Phase 1: Find and validate files
        audio_files = self.find_audio_files(source_dir)
        logger.info(f"Found {len(audio_files)} audio files")

        if sample_size and sample_size < len(audio_files):
            import random
            audio_files = random.sample(audio_files, sample_size)
            logger.info(f"Using sample of {len(audio_files)} files")

        valid_files = self.run_validation_phase(audio_files)

        if not valid_files:
            logger.error("No valid audio files found!")
            return False

        # Phase 2: Analyze
        metadata_list = self.run_analysis_phase(valid_files, num_workers=num_workers)

        if not metadata_list:
            logger.error("No files to analyze!")
            return False

        # Phase 5: Migrate
        reporter = self.run_migration_phase(metadata_list, destination_dir, dry_run=dry_run)

        # Phase 6: Report
        self.run_reporting_phase(reporter)

        logger.info("✓ Migration completed successfully!")
        return True

def main():
    parser = argparse.ArgumentParser(
        description='KOLBIE SAMPLES - Audio File Organizer and Metadata Extractor'
    )
    parser.add_argument('--source-dir', required=True, help='Source directory with audio files')
    parser.add_argument('--destination', required=True, help='Destination root directory')
    parser.add_argument('--config', default='config/genre_mapping.json', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without copying files')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--sample-size', type=int, help='Process only N random files (for testing)')
    parser.add_argument(
        '--parallel-workers', type=int, default=1,
        help='Number of processes for the analysis phase (CPU-bound; leaves other phases sequential). '
             'Use 0 to auto-detect (CPU count - 1). Default: 1 (sequential, original behavior).'
    )

    args = parser.parse_args()

    num_workers = args.parallel_workers
    if num_workers == 0:
        num_workers = max(1, (os.cpu_count() or 2) - 1)

    migrator = SampleMigrator(args.config)
    success = migrator.run(
        args.source_dir,
        args.destination,
        dry_run=args.dry_run,
        sample_size=args.sample_size,
        num_workers=num_workers
    )

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
