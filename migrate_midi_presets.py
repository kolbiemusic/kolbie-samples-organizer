#!/usr/bin/env python3
"""
KOLBIE PRESETS:MIDI - MIDI + Synth Preset Organizer

Sibling pipeline to migrate_samples.py, for the MIDI and preset files the
audio pipeline never touches (.mid, .fxp, .nki, .serumpreset, .vital,
.sfz, ...). Separate script on purpose — migrate_samples.py's
setup_logging() runs at import time, before argparse even exists, and it's
already-validated code from a real completed run (Cycle 1). Zero risk to
it means zero edits to it, not "careful" edits.

Usage:
    python migrate_midi_presets.py \
      --source-dir "/path/to/source" \
      --dry-run --sample-size 150

By default --destination is the KOLBIE PRESETS:MIDI tree (sibling to
KOLBIE SAMPLES, not nested inside it) and --parallel-workers is 'auto'
(same benchmark-driven auto-calibration as the audio pipeline — see
modules/benchmark.py).
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from tqdm import tqdm

from modules import (
    MidiAnalyzer, PresetAnalyzer, FileValidator,
    MidiPresetOrganizer, MidiPresetReporter, benchmark_worker_count,
    preflight_extract_archives,
)
from modules.logging_setup import setup_logging

DEFAULT_DESTINATION = '/Volumes/SAMPLES & LOOPS/KOLBIE PRESETS:MIDI'
MIDI_EXTENSIONS = {'.mid'}

logger = logging.getLogger('migrate_midi_presets')

# --- Parallel analysis workers (run in child processes) ---
#
# Same reasoning as migrate_samples.py's _init_worker/_analyze_worker: a
# ProcessPoolExecutor needs a top-level picklable callable, so each worker
# process builds its own analyzers once via `initializer` and reuses them.
_worker_midi_analyzer = None
_worker_preset_analyzer = None


def _init_analysis_worker(preset_config, genre_keywords, bpm_patterns=None, key_patterns=None,
                           source_dir=None, pack_genre_overrides=None):
    global _worker_midi_analyzer, _worker_preset_analyzer
    logging.basicConfig(level=logging.WARNING)
    category_keywords = preset_config.get('category_keywords', {})
    _worker_midi_analyzer = MidiAnalyzer(
        genre_keywords=genre_keywords, category_keywords=category_keywords,
        bpm_patterns=bpm_patterns, key_patterns=key_patterns,
        source_dir=source_dir, pack_genre_overrides=pack_genre_overrides,
    )
    _worker_preset_analyzer = PresetAnalyzer(
        preset_config, genre_keywords=genre_keywords,
        source_dir=source_dir, pack_genre_overrides=pack_genre_overrides,
    )


def _analyze_worker(filepath):
    ext = Path(filepath).suffix.lower()
    if ext in MIDI_EXTENSIONS:
        metadata = _worker_midi_analyzer.analyze_file(filepath)
        metadata['kind'] = 'midi'
    else:
        metadata = _worker_preset_analyzer.analyze_file(filepath)
        metadata['kind'] = 'preset'
    return metadata


# --- Parallel validation workers (run in threads — I/O-bound, same
# reasoning as migrate_samples.py's _is_valid_worker/_hash_worker) ---
_VALIDATION_PRESET_CONFIG = None


def _is_valid_worker(filepath):
    ext = Path(filepath).suffix.lower()
    if ext in MIDI_EXTENSIONS:
        ok = MidiAnalyzer().is_valid_midi(filepath)
    else:
        ok = PresetAnalyzer(_VALIDATION_PRESET_CONFIG).is_valid_preset(filepath)
    return (filepath, ok)


def _hash_worker(filepath):
    validator = FileValidator()
    return (filepath, validator.get_file_hash(filepath))


class MidiPresetMigrator:
    def __init__(self, config_path='config/preset_mapping.json', genre_config_path='config/genre_mapping.json'):
        global _VALIDATION_PRESET_CONFIG
        with open(config_path, 'r') as f:
            self.preset_config = json.load(f)
        _VALIDATION_PRESET_CONFIG = self.preset_config

        # Read-only reuse of the audio pipeline's genre taxonomy AND its
        # (corrected) BPM/key filename-regex patterns — same techniques,
        # so classification is consistent across KOLBIE SAMPLES and
        # KOLBIE PRESETS:MIDI. Never writes to this file; genre_mapping.json
        # stays the audio pipeline's alone.
        with open(genre_config_path, 'r') as f:
            genre_config = json.load(f)
        self.genre_keywords = genre_config.get('genre_keywords', {})
        self.bpm_patterns = genre_config.get('bpm_patterns', [])
        self.key_patterns = genre_config.get('key_patterns', [])
        self.pack_genre_overrides = genre_config.get('pack_genre_overrides', {})
        self.source_dir = None  # set in run(), once the source path is known

        self.midi_analyzer = MidiAnalyzer(
            genre_keywords=self.genre_keywords,
            category_keywords=self.preset_config.get('category_keywords', {}),
            bpm_patterns=self.bpm_patterns,
            key_patterns=self.key_patterns,
            pack_genre_overrides=self.pack_genre_overrides,
        )
        self.preset_analyzer = PresetAnalyzer(
            self.preset_config, genre_keywords=self.genre_keywords,
            pack_genre_overrides=self.pack_genre_overrides,
        )
        self.validator = FileValidator()
        self.organizer = None
        self.reporter = None

    def validate_paths(self, source_dir, destination_dir):
        source_path = Path(source_dir)
        dest_path = Path(destination_dir)

        if not source_path.exists():
            logger.error(f"Source directory does not exist: {source_dir}")
            return False

        dest_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Source: {source_path}")
        logger.info(f"Destination: {dest_path}")
        return True

    def find_files(self, source_dir, include='all'):
        """Find MIDI and/or preset files, per --include. Preset extensions come from config, not a hardcoded set."""
        source_path = Path(source_dir)
        preset_extensions = set(self.preset_config.get('extension_plugin_map', {}).keys())

        extensions = set()
        if include in ('all', 'midi'):
            extensions |= MIDI_EXTENSIONS
        if include in ('all', 'presets'):
            extensions |= preset_extensions

        found = []
        for ext in extensions:
            found.extend(source_path.rglob(f'*{ext}'))
            found.extend(source_path.rglob(f'*{ext.upper()}'))

        # A folder can carry an extension-like name too (e.g. an unextracted
        # pack "Cymatics.Roses.for.Xfer.Serum.Pop.FXP/" with a .rar inside) —
        # rglob matches it as a "file" by name alone, and every phase downstream
        # (hash, copy) then fails on it with "Is a directory".
        found = [f for f in found if f.is_file()]

        return sorted(set(found))

    def run_validation_phase(self, files, num_workers=1):
        logger.info("=" * 60)
        logger.info("PHASE 1: VALIDATION")
        logger.info("=" * 60)

        file_paths = [str(f) for f in files]
        logger.info(f"Validating {len(file_paths)} files ({num_workers} worker{'s' if num_workers != 1 else ''})...")

        if num_workers <= 1:
            valid_results = [_is_valid_worker(fp) for fp in tqdm(file_paths, desc="Validating")]
        else:
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                valid_results = list(tqdm(
                    executor.map(_is_valid_worker, file_paths),
                    total=len(file_paths), desc="Validating"
                ))

        valid_files = [Path(fp) for fp, ok in valid_results if ok]
        logger.info(f"✓ Valid files: {len(valid_files)}/{len(files)}")
        logger.info(f"✗ Invalid files: {len(files) - len(valid_files)}")

        # Content hashes — needed later for dedup AND for the organizer's
        # name-collision disambiguation (same computed dest path, different
        # content -> keep both, per user decision on repeated preset names
        # like "Init.fxp" across unrelated packs).
        logger.info("Hashing files (dedup + collision disambiguation)...")
        valid_paths_str = [str(f) for f in valid_files]

        if num_workers <= 1:
            hash_results = [_hash_worker(fp) for fp in tqdm(valid_paths_str, desc="Hashing")]
        else:
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                hash_results = list(tqdm(
                    executor.map(_hash_worker, valid_paths_str),
                    total=len(valid_paths_str), desc="Hashing"
                ))

        hash_map = {fp: h for fp, h in hash_results if h}

        seen_hashes = set()
        duplicate_sets = 0
        for h in hash_map.values():
            if h in seen_hashes:
                duplicate_sets += 1
            seen_hashes.add(h)
        logger.info(f"Found {duplicate_sets} duplicate content hashes")
        logger.info(f"Files to process: {len(valid_files)}")

        return valid_files, hash_map

    def run_analysis_phase(self, files, hash_map, num_workers=1):
        logger.info("=" * 60)
        logger.info("PHASE 2: ANALYSIS")
        logger.info("=" * 60)

        metadata_list = []
        file_paths = [str(f) for f in files]
        logger.info(f"Analyzing {len(file_paths)} files ({num_workers} worker{'s' if num_workers != 1 else ''})...")

        if num_workers <= 1:
            for filepath in tqdm(file_paths, desc="Analyzing"):
                ext = Path(filepath).suffix.lower()
                if ext in MIDI_EXTENSIONS:
                    metadata = self.midi_analyzer.analyze_file(filepath)
                    metadata['kind'] = 'midi'
                else:
                    metadata = self.preset_analyzer.analyze_file(filepath)
                    metadata['kind'] = 'preset'
                metadata_list.append(metadata)
        else:
            chunksize = max(1, len(file_paths) // (num_workers * 4))
            with ProcessPoolExecutor(
                max_workers=num_workers,
                initializer=_init_analysis_worker,
                initargs=(self.preset_config, self.genre_keywords, self.bpm_patterns, self.key_patterns,
                          self.source_dir, self.pack_genre_overrides)
            ) as executor:
                results = executor.map(_analyze_worker, file_paths, chunksize=chunksize)
                for metadata in tqdm(results, total=len(file_paths), desc="Analyzing"):
                    metadata_list.append(metadata)

        for metadata in metadata_list:
            metadata['content_hash'] = hash_map.get(metadata['original_path'])

        midi_count = sum(1 for m in metadata_list if m['kind'] == 'midi')
        preset_count = len(metadata_list) - midi_count
        logger.info(f"✓ Analyzed: {len(metadata_list)}/{len(files)} ({midi_count} MIDI, {preset_count} presets)")

        return metadata_list

    def calibrate_workers(self, files):
        logger.info("=" * 60)
        logger.info("CALIBRAÇÃO AUTOMÁTICA DE WORKERS")
        logger.info("=" * 60)

        import random
        sample_pool = list(files)
        random.shuffle(sample_pool)
        midpoint = len(sample_pool) // 2
        validation_sample = [str(f) for f in sample_pool[:midpoint]][:250]
        analysis_sample = [str(f) for f in sample_pool[midpoint:]][:250]

        logger.info("Fase de validação (I/O em disco):")
        validation_workers, _ = benchmark_worker_count(
            validation_sample, _hash_worker, mode='thread', label='threads'
        )

        logger.info("Fase de análise (CPU):")
        analysis_workers, _ = benchmark_worker_count(
            analysis_sample, _analyze_worker, mode='process',
            init_fn=_init_analysis_worker,
            init_args=(self.preset_config, self.genre_keywords, self.bpm_patterns, self.key_patterns,
                       self.source_dir, self.pack_genre_overrides),
            label='processos'
        )

        logger.info(f"✓ Calibração concluída: validação={validation_workers}, análise={analysis_workers}")
        return validation_workers, analysis_workers

    def run_migration_phase(self, metadata_list, destination_dir, dry_run=False):
        logger.info("=" * 60)
        logger.info("PHASE 3: MIGRATION")
        logger.info("=" * 60)

        self.organizer = MidiPresetOrganizer(destination_dir)
        self.reporter = MidiPresetReporter(destination_dir)

        if dry_run:
            logger.warning("DRY RUN MODE - No files will be copied")

        for metadata in tqdm(metadata_list, desc="Migrating"):
            self.reporter.add_file_metadata(metadata)

            if not dry_run:
                source_path = metadata.get('original_path')
                result = self.organizer.copy_file(source_path, metadata)
                if result:
                    metadata['new_path'] = result

        if not dry_run:
            stats = self.organizer.get_stats()
            logger.info(f"✓ Copied: {stats['copied']}")
            logger.info(f"= Skipped (already migrated): {stats['skipped']}")
            logger.info(f"✗ Failed: {stats['failed']}")

        return self.reporter

    def run_reporting_phase(self, reporter):
        logger.info("=" * 60)
        logger.info("PHASE 4: REPORTING")
        logger.info("=" * 60)

        if not reporter:
            logger.warning("No reporter available")
            return

        stats = self.organizer.get_stats() if self.organizer else {'copied': 0, 'skipped': 0, 'failed': 0}

        csv_path = reporter.generate_csv_index()
        if csv_path:
            logger.info(f"✓ CSV index: {csv_path}")

        json_path = reporter.generate_json_metadata()
        if json_path:
            logger.info(f"✓ JSON metadata: {json_path}")

        html_path = reporter.generate_html_report(stats)
        if html_path:
            logger.info(f"✓ HTML report: {html_path}")

    def run(self, source_dir, destination_dir, dry_run=False, sample_size=None,
            num_workers='auto', include='all'):
        logger.info("🎹 KOLBIE PRESETS:MIDI - Migration Started")
        logger.info(f"Dry run: {dry_run}")
        logger.info(f"Include: {include}")

        if not self.validate_paths(source_dir, destination_dir):
            return False

        # Fallback genre naming needs the source root to compute each
        # file's top-level pack folder — same trick as migrate_samples.py.
        self.source_dir = str(Path(source_dir).resolve())
        self.midi_analyzer.source_dir = self.source_dir
        self.preset_analyzer.source_dir = self.source_dir

        # Pre-flight: extract any still-compressed packs so this pass picks
        # them up, then move the archives to the Trash (never a hard delete).
        preflight_extract_archives(source_dir, dry_run=dry_run)

        files = self.find_files(source_dir, include=include)
        logger.info(f"Found {len(files)} MIDI/preset files")

        if sample_size and sample_size < len(files):
            import random
            files = random.sample(files, sample_size)
            logger.info(f"Using sample of {len(files)} files")

        if not files:
            logger.error("No matching files found!")
            return False

        if num_workers == 'auto':
            validation_workers, analysis_workers = self.calibrate_workers(files)
        else:
            validation_workers = analysis_workers = num_workers

        valid_files, hash_map = self.run_validation_phase(files, num_workers=validation_workers)

        if not valid_files:
            logger.error("No valid files found!")
            return False

        metadata_list = self.run_analysis_phase(valid_files, hash_map, num_workers=analysis_workers)

        if not metadata_list:
            logger.error("No files to analyze!")
            return False

        reporter = self.run_migration_phase(metadata_list, destination_dir, dry_run=dry_run)
        self.run_reporting_phase(reporter)

        logger.info("✓ Migration completed successfully!")
        return True


def main():
    parser = argparse.ArgumentParser(
        description='KOLBIE PRESETS:MIDI - MIDI + Synth Preset Organizer'
    )
    parser.add_argument('--source-dir', required=True, help='Source directory with MIDI/preset files')
    parser.add_argument('--destination', default=DEFAULT_DESTINATION, help='Destination root directory')
    parser.add_argument('--config', default='config/preset_mapping.json', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without copying files')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--sample-size', type=int, help='Process only N random files (for testing)')
    parser.add_argument(
        '--parallel-workers', default='auto',
        help="Worker count for validation + analysis phases. 'auto' (default) benchmarks "
             "a real sample of this run's files on this machine/disk before starting. "
             "Pass an integer to force a specific count and skip calibration."
    )
    parser.add_argument(
        '--include', choices=['midi', 'presets', 'all'], default='all',
        help="Which file group to process — lets a pilot run just one branch first, "
             "since MIDI parsing (mido) and preset parsing (JSON/binary) have different cost profiles."
    )

    args = parser.parse_args()

    global logger
    logger = setup_logging(verbose=args.verbose)

    num_workers = 'auto' if args.parallel_workers == 'auto' else int(args.parallel_workers)

    migrator = MidiPresetMigrator(args.config)
    success = migrator.run(
        args.source_dir,
        args.destination,
        dry_run=args.dry_run,
        sample_size=args.sample_size,
        num_workers=num_workers,
        include=args.include,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
