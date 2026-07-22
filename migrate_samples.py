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

    def run_analysis_phase(self, audio_files):
        """Phase 2: Analyze audio files"""
        logger.info("=" * 60)
        logger.info("PHASE 2: AUDIO ANALYSIS")
        logger.info("=" * 60)

        metadata_list = []
        logger.info(f"Analyzing {len(audio_files)} audio files...")

        for filepath in tqdm(audio_files, desc="Analyzing"):
            metadata = self.analyzer.analyze_file(filepath)
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

    def run(self, source_dir, destination_dir, dry_run=False, sample_size=None):
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
        metadata_list = self.run_analysis_phase(valid_files)

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

    args = parser.parse_args()

    migrator = SampleMigrator(args.config)
    success = migrator.run(
        args.source_dir,
        args.destination,
        dry_run=args.dry_run,
        sample_size=args.sample_size
    )

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
