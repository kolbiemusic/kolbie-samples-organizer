#!/usr/bin/env python3
"""
Second remediation pass: re-run the corrected _classify_sound_type (peak-
count + peak-coverage based, replacing the unreliable onset-regularity /
chroma-similarity signals) against every already-migrated file under
Loop/, FX_Oneshot_Longo/, and Oneshot/ in KOLBIE SAMPLES, and move any
file whose classification disagrees to its correct location — in either
direction (Loop<->Oneshot, Loop<->FX_Oneshot_Longo, etc).

For files newly classified as Loop, BPM is recovered from the filename
(regex) or, failing that, estimated from the audio — it was previously
suppressed as None under the old classification. Key is preserved from
the existing filename tag when present, or estimated fresh if it isn't
(e.g. a Drums+Oneshot file moving to a non-suppressed classification).

Usage:
  python3 fix_classification_v2.py --dry-run [--workers N]
  python3 fix_classification_v2.py [--workers N]
"""
import argparse
import csv
import hashlib
import json
import logging
import random
import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import librosa
from tqdm import tqdm

from modules.audio_analyzer import AudioAnalyzer
from modules.file_organizer import FileOrganizer

TAG_RE = re.compile(r'(\s*\[[^\]]+\])+$')
BRIGHTNESS_VALUES = {'Escuro', 'Medio', 'Claro', 'Full_Spectro'}
CLASSIFICATIONS = {'Loop', 'FX_Oneshot_Longo', 'Oneshot'}

logging.basicConfig(level=logging.WARNING)

_worker_analyzer = None


def _init_worker(config):
    global _worker_analyzer
    _worker_analyzer = AudioAnalyzer(config)


def strip_tags(stem):
    return TAG_RE.sub('', stem).strip()


def parse_existing_tags(stem):
    tags = re.findall(r'\[([^\]]+)\]', stem)
    brightness = next((t for t in tags if t in BRIGHTNESS_VALUES), None)
    bpm_tag = next((t for t in tags if 'bpm' in t.lower()), None)
    key_tag = next((t for t in tags if t not in BRIGHTNESS_VALUES and t != bpm_tag), None)
    return brightness, key_tag


def _process_file(args):
    path_str, dest_root_str, report_all = args
    p = Path(path_str)
    dest_root = Path(dest_root_str)

    try:
        rel = p.relative_to(dest_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 4:
        return None
    genre, type_name, old_classification = parts[0], parts[1], parts[2]
    if old_classification not in CLASSIFICATIONS:
        return None

    try:
        y, sr = librosa.load(str(p), sr=None, mono=True)
    except Exception as e:
        return {'error': f"{p}: load failed: {e}"}
    duration = len(y) / sr

    stem = p.stem
    brightness, key_tag = parse_existing_tags(stem)
    clean_stem = strip_tags(stem)

    # Filename-priority check first (see AudioAnalyzer._classify_from_path).
    # Deliberately passed the bare clean_stem, NOT the destination path `p`:
    # `p`'s own folders spell out the *current* classification
    # (".../FX_Oneshot_Longo/...", which itself contains the word "Oneshot")
    # so checking the full destination path would just confirm whatever a
    # file already got tagged, defeating the point of a re-check. The
    # original source folder hints are gone post-migration anyway — the
    # filename is the only textual evidence left to trust.
    new_classification = _worker_analyzer._classify_from_path(clean_stem, duration)
    if not new_classification:
        new_classification = _worker_analyzer._classify_sound_type(y, sr, duration, type_name)
    unchanged = (not new_classification) or (new_classification == old_classification)
    if unchanged and not report_all:
        return None

    effective_classification = new_classification or old_classification

    if unchanged:
        # No move needed — report the unchanged outcome as-is (don't
        # recompute/estimate key or bpm, the existing file already has them).
        return {
            'old_path': str(p), 'genre': genre, 'type': type_name,
            'old_classification': old_classification,
            'new_classification': effective_classification,
            'unchanged': True,
        }

    if new_classification == 'Oneshot' and type_name == 'Drums':
        new_key = None
    elif key_tag:
        new_key = key_tag
    else:
        new_key = _worker_analyzer._estimate_key(y, sr)

    new_bpm = None
    if new_classification == 'Loop':
        bpm_from_name = _worker_analyzer._extract_bpm_from_name(clean_stem)
        if bpm_from_name:
            new_bpm = bpm_from_name
        else:
            estimated = _worker_analyzer._estimate_bpm(y, sr)
            new_bpm = int(estimated) if estimated else None

    return {
        'old_path': str(p),
        'genre': genre,
        'type': type_name,
        'old_classification': old_classification,
        'new_classification': new_classification,
        'brightness': brightness,
        'key': new_key,
        'bpm': new_bpm,
        'clean_stem': clean_stem,
        'ext': p.suffix,
        'unchanged': False,
    }


def file_hash(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--destination', default='/Volumes/SAMPLES & LOOPS/KOLBIE SAMPLES')
    ap.add_argument('--config', default='config/genre_mapping.json')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--sample-size', type=int, default=None,
                     help='Process only a random sample of N files (for manual review before a full run). '
                          'Also writes a per-file CSV report covering every sampled file, moved or not.')
    ap.add_argument('--seed', type=int, default=None, help='Random seed for --sample-size (for reproducible samples)')
    ap.add_argument('--report', default=None, help='CSV report path (default: auto-named under logs/)')
    args = ap.parse_args()

    dest_root = Path(args.destination)
    config = json.load(open(args.config))
    organizer = FileOrganizer(dest_root)

    candidates = [p for p in dest_root.rglob('*')
                  if p.is_file() and p.suffix.lower() in {'.wav', '.aif', '.aiff', '.flac', '.mp3'}
                  and any(f'/{c}/' in str(p) for c in CLASSIFICATIONS)]
    print(f"Found {len(candidates)} files under Loop/FX_Oneshot_Longo/Oneshot.")

    report_all = args.sample_size is not None
    if args.sample_size is not None:
        rng = random.Random(args.seed)
        candidates = rng.sample(candidates, min(args.sample_size, len(candidates)))
        print(f"Sampled {len(candidates)} files for this run.")

    tasks = [(str(p), str(dest_root), report_all) for p in candidates]

    moves = {'Loop->Oneshot': 0, 'Loop->FX_Oneshot_Longo': 0,
             'FX_Oneshot_Longo->Loop': 0, 'FX_Oneshot_Longo->Oneshot': 0,
             'Oneshot->Loop': 0, 'Oneshot->FX_Oneshot_Longo': 0}
    errors = []
    collisions_disambiguated = 0
    deduped = 0
    moved_count = 0
    unchanged_count = 0

    report_rows = []
    if report_all:
        from datetime import datetime
        report_path = Path(args.report) if args.report else Path('logs') / f"fix_classification_v2_SAMPLE_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker, initargs=(config,)) as executor:
        for result in tqdm(executor.map(_process_file, tasks, chunksize=16), total=len(tasks)):
            if result is None:
                continue
            if 'error' in result:
                errors.append(result['error'])
                continue

            if result.get('unchanged'):
                unchanged_count += 1
                if report_all:
                    report_rows.append({
                        'old_path': result['old_path'], 'new_path': result['old_path'],
                        'genre': result['genre'], 'type': result['type'],
                        'old_classification': result['old_classification'],
                        'new_classification': result['new_classification'],
                        'moved': False,
                    })
                continue

            transition = f"{result['old_classification']}->{result['new_classification']}"
            moves[transition] = moves.get(transition, 0) + 1

            metadata = {
                'genre': result['genre'], 'type': result['type'],
                'classification': result['new_classification'],
                'bpm': result['bpm'], 'key': result['key'], 'brightness': result['brightness'],
            }
            new_dir = organizer.calculate_destination_path(metadata)
            new_filename = organizer.generate_new_filename(result['clean_stem'] + result['ext'], metadata)
            new_path = new_dir / new_filename
            old_path = Path(result['old_path'])

            if args.dry_run:
                moved_count += 1
                if report_all:
                    report_rows.append({
                        'old_path': str(old_path), 'new_path': str(new_path),
                        'genre': result['genre'], 'type': result['type'],
                        'old_classification': result['old_classification'],
                        'new_classification': result['new_classification'],
                        'moved': 'would move',
                    })
                continue

            new_dir.mkdir(parents=True, exist_ok=True)
            deduped_this = False
            if new_path.exists():
                if file_hash(old_path) == file_hash(new_path):
                    subprocess.run(['/usr/bin/trash', str(old_path)], capture_output=True)
                    deduped += 1
                    deduped_this = True
                else:
                    stem2, ext2 = new_path.stem, new_path.suffix
                    n = 1
                    candidate = new_path.parent / f"{stem2} [dup{n}]{ext2}"
                    while candidate.exists():
                        n += 1
                        candidate = new_path.parent / f"{stem2} [dup{n}]{ext2}"
                    new_path = candidate
                    collisions_disambiguated += 1

            if not deduped_this:
                shutil.move(str(old_path), str(new_path))
                moved_count += 1

            if report_all:
                report_rows.append({
                    'old_path': str(old_path),
                    'new_path': 'TRASHED (duplicate content already at destination)' if deduped_this else str(new_path),
                    'genre': result['genre'], 'type': result['type'],
                    'old_classification': result['old_classification'],
                    'new_classification': result['new_classification'],
                    'moved': 'deduped' if deduped_this else True,
                })

    if report_all:
        with open(report_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['old_path', 'new_path', 'genre', 'type', 'old_classification', 'new_classification', 'moved'])
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"\nCSV report: {report_path}")

    print()
    print("=" * 60)
    print("Transitions:" if args.dry_run else "Moved by transition:")
    for k, v in moves.items():
        if v:
            print(f"  {k}: {v}")
    print(f"Total {'would move' if args.dry_run else 'moved'}: {moved_count}")
    print(f"Unchanged (already correct): {unchanged_count}")
    if not args.dry_run:
        print(f"Deduped (identical content already at new path): {deduped}")
        print(f"Collisions disambiguated: {collisions_disambiguated}")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == '__main__':
    main()
