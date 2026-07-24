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

By default, --parallel-workers is 'auto': before the real run, a quick
benchmark times a handful of worker counts on a real sample of this run's
files on this machine/disk and picks the fastest per phase — no manual
tuning needed, and it re-adapts automatically on a different computer or a
different drive. Pass an explicit integer to skip calibration.
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from tqdm import tqdm
import colorlog

from modules import AudioAnalyzer, FileValidator, FileOrganizer, Reporter, benchmark_worker_count, preflight_extract_archives

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
# multiple processes — threads wouldn't help due to the GIL. Validation is
# parallelized separately with threads (see _is_valid_worker/_hash_worker
# below — it's I/O-bound, not CPU-bound). Copy stays sequential: throughput
# there is capped by the disks, not the CPU, so parallel copy risks
# thrashing an HDD instead of speeding anything up.
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

# --- Parallel validation workers (run in threads, not processes) ---
#
# Validation is mostly waiting on disk (mutagen header parse, then a
# full-file read for the MD5 hash) rather than crunching numbers — I/O
# calls and hashlib's C implementation both release the GIL, so threads
# get real concurrency here without the process-spawn overhead a
# ProcessPoolExecutor would add for ~20k short-lived tasks. FileValidator
# has no heavyweight setup (empty dicts), so building one per call is cheap.
def _is_valid_worker(filepath):
    validator = FileValidator()
    return (filepath, validator.is_valid_audio(filepath))

def _hash_worker(filepath):
    validator = FileValidator()
    return (filepath, validator.get_file_hash(filepath))

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

        # A folder can carry an extension-like name too (e.g. an unextracted
        # pack folder named "....wav/" with the real archive inside) — rglob
        # matches it as a "file" by name alone, and every phase downstream
        # (hash, copy) then fails on it with "Is a directory".
        audio_files = [f for f in audio_files if f.is_file()]

        return sorted(list(set(audio_files)))

    def run_validation_phase(self, audio_files, num_workers=1):
        """Phase 1: Validate and clean audio files (threaded I/O when num_workers > 1)"""
        logger.info("=" * 60)
        logger.info("PHASE 1: VALIDATION & CLEANING")
        logger.info("=" * 60)

        file_paths = [str(f) for f in audio_files]
        logger.info(f"Validating {len(file_paths)} audio files ({num_workers} worker{'s' if num_workers != 1 else ''})...")

        if num_workers <= 1:
            valid_results = [(fp, self.validator.is_valid_audio(fp)) for fp in tqdm(file_paths, desc="Validating")]
        else:
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                valid_results = list(tqdm(
                    executor.map(_is_valid_worker, file_paths),
                    total=len(file_paths), desc="Validating"
                ))

        valid_files = [Path(fp) for fp, ok in valid_results if ok]

        logger.info(f"✓ Valid files: {len(valid_files)}/{len(audio_files)}")
        logger.info(f"✗ Invalid files: {len(audio_files) - len(valid_files)}")

        # Find duplicates (full-file MD5 — the expensive read, same reasoning
        # for threading as above)
        logger.info("Scanning for duplicate files...")
        valid_paths_str = [str(f) for f in valid_files]

        if num_workers <= 1:
            hash_results = [(fp, self.validator.get_file_hash(fp)) for fp in tqdm(valid_paths_str, desc="Hashing")]
        else:
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                hash_results = list(tqdm(
                    executor.map(_hash_worker, valid_paths_str),
                    total=len(valid_paths_str), desc="Hashing"
                ))

        content_by_hash = {}
        duplicate_sets = 0
        path_to_hash = {}
        for fp, file_hash in hash_results:
            if file_hash:
                path_to_hash[fp] = file_hash
                if file_hash in content_by_hash:
                    duplicate_sets += 1
                else:
                    content_by_hash[file_hash] = fp
        logger.info(f"Found {duplicate_sets} duplicate sets")

        # Summary
        logger.info(f"Files to process: {len(valid_files)}")
        return valid_files, path_to_hash

    def run_analysis_phase(self, audio_files, path_to_hash, num_workers=1):
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

        for metadata in metadata_list:
            metadata['content_hash'] = path_to_hash.get(metadata['original_path'])

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

    def calibrate_workers(self, audio_files):
        """
        Pre-flight benchmark: times a handful of candidate worker counts on
        a real sample of THIS run's files, on THIS machine and disk, and
        picks the fastest for each phase independently (validation is
        threaded I/O, analysis is multi-process CPU work — their optimal
        counts don't have to match, e.g. an external HDD can cap both at a
        low number while a fast internal SSD might let analysis scale
        much higher).
        """
        logger.info("=" * 60)
        logger.info("CALIBRAÇÃO AUTOMÁTICA DE WORKERS")
        logger.info("=" * 60)

        import random
        sample_pool = list(audio_files)
        random.shuffle(sample_pool)
        # Split into two disjoint halves — one per phase — so the analysis
        # benchmark doesn't get an unfair cache-warm boost from files the
        # validation benchmark (which reads whole files for hashing) just
        # touched. Each half still gets sliced further per-candidate inside
        # benchmark_worker_count.
        midpoint = len(sample_pool) // 2
        validation_sample = [str(f) for f in sample_pool[:midpoint]][:250]
        analysis_sample = [str(f) for f in sample_pool[midpoint:]][:250]

        logger.info("Fase de validação (I/O em disco):")
        # Calibrate on the hashing step, not the header-only validity check
        # — hashing reads the whole file (same "full read from disk"
        # pattern as analysis), so it's the realistic worst case for this
        # phase. The header check is cheap enough that whatever worker
        # count works for hashing works fine for it too.
        validation_workers, _ = benchmark_worker_count(
            validation_sample, _hash_worker, mode='thread', label='threads'
        )

        logger.info("Fase de análise (CPU):")
        analysis_workers, _ = benchmark_worker_count(
            analysis_sample, _analyze_worker, mode='process',
            init_fn=_init_worker, init_args=(self.config,), label='processos'
        )

        logger.info(f"✓ Calibração concluída: validação={validation_workers}, análise={analysis_workers}")
        return validation_workers, analysis_workers

    def run_migration_phase(self, metadata_list, destination_dir, dry_run=False):
        """Phase 5: Copy and rename files"""
        logger.info("=" * 60)
        logger.info("PHASE 5: MIGRATION")
        logger.info("=" * 60)

        self.organizer = FileOrganizer(destination_dir)
        self.reporter = Reporter(destination_dir)

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

    def run(self, source_dir, destination_dir, dry_run=False, sample_size=None, num_workers='auto'):
        """
        Execute complete migration.

        num_workers: an int applies the same worker count to both the
        validation and analysis phases (power-user override — skips
        calibration, useful once you already know your machine's number).
        'auto' (default) benchmarks this run's actual files on this
        machine/disk and picks independently-tuned counts per phase.
        """
        logger.info("🎵 KOLBIE SAMPLES - Migration Started")
        logger.info(f"Dry run: {dry_run}")

        # Validate paths
        if not self.validate_paths(source_dir, destination_dir):
            return False

        # Fallback genre naming needs to know the source root to compute
        # each file's top-level pack folder — stashed on the shared config
        # dict so it rides along to worker processes via initargs.
        self.config['_source_dir'] = str(Path(source_dir).resolve())

        # Pre-flight: extract any still-compressed packs so this pass picks
        # them up, then move the archives to the Trash (never a hard delete).
        preflight_extract_archives(source_dir, dry_run=dry_run)

        # Phase 1: Find and validate files
        audio_files = self.find_audio_files(source_dir)
        logger.info(f"Found {len(audio_files)} audio files")

        if sample_size and sample_size < len(audio_files):
            import random
            audio_files = random.sample(audio_files, sample_size)
            logger.info(f"Using sample of {len(audio_files)} files")

        if num_workers == 'auto':
            validation_workers, analysis_workers = self.calibrate_workers(audio_files)
        else:
            validation_workers = analysis_workers = num_workers

        valid_files, path_to_hash = self.run_validation_phase(audio_files, num_workers=validation_workers)

        if not valid_files:
            logger.error("No valid audio files found!")
            return False

        # Phase 2: Analyze
        metadata_list = self.run_analysis_phase(valid_files, path_to_hash, num_workers=analysis_workers)

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
        '--parallel-workers', default='auto',
        help="Worker count for validation + analysis phases. 'auto' (default) benchmarks "
             "a real sample of this run's files on this machine/disk before starting, and "
             "picks independently-tuned counts per phase — portable across machines and "
             "drives with no manual tuning. Pass an integer to force a specific count for "
             "both phases and skip calibration (e.g. '1' for the original sequential behavior)."
    )

    args = parser.parse_args()

    if args.parallel_workers == 'auto':
        num_workers = 'auto'
    else:
        num_workers = int(args.parallel_workers)

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
