#!/usr/bin/env python3
"""
KOLBIE SAMPLES — genre-marker-driven migration (rewrite, 2026-07-26)

Complete replacement for the old audio-analysis pipeline (migrate_samples.py).
No BPM/key/brightness/classification, no librosa, no per-file renaming. The
user did a full manual sweep of the 3 source libraries and dropped an empty
".txt" file (named after the genre) directly inside every pack folder they
wanted organized — see DECISIONS.md 2026-07-26 for the full rationale.

Two kinds of "copy unit", each copied as a single intact folder (exact
structure/filenames preserved, nothing renamed or reorganized inside it):

1. MARKED — any folder, at any depth in the 3 source trees, that has an
   empty (or whitespace-only) .txt file directly inside it. The marker
   filename (minus extension) IS the genre. This is authoritative and
   always wins — including for packs bundled inside an aggregator folder
   (NAO TRANSFERIDAS, Packs Installed, Splice, ...), and including nested
   sub-packs inside one bigger pack that only partially got marked (e.g.
   "Cymatics - Strangers Bonus Packs" splits into 4 independently-marked
   sub-packs).

2. FALLBACK — a top-level pack root (skipping known aggregator container
   folders) that has NO marker anywhere inside it. Its own folder name is
   matched against a flattened, subgenre-free keyword list
   (config/main_genres.json) — first match wins, no per-file digging.
   Packs that already contain at least one marker anywhere inside them are
   never fallback-matched as a whole, even if some of their subfolders
   went unmarked — those leftovers are simply left out of this run (user's
   explicit call, 2026-07-26: mark them later if wanted, don't guess).

Destination: KOLBIE SAMPLES/{genre}/{original pack folder name}/... — a
straight recursive copy (shutil.copytree), never touching the source.
"""
import argparse
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

GENERIC_PACK_CONTAINERS = {'splice', 'slate samples', 'algonautcontent', 'packs installed'}
IGNORE_DIRS = {'__MACOSX'}
MARKER_MAX_BYTES = 200  # empty/whitespace-only marker files are 0-1 bytes in practice; generous ceiling


def load_config(config_path):
    with open(config_path) as f:
        return json.load(f)


def is_genre_marker(path):
    """A genre marker is a .txt file with no real content — empty or
    whitespace-only. Distinguishes it from real documentation (README,
    license, lyrics) that happens to also be a .txt file in the same pack."""
    try:
        if path.stat().st_size > MARKER_MAX_BYTES:
            return False
        with open(path, 'rb') as f:
            content = f.read(MARKER_MAX_BYTES)
        return content.strip() == b''
    except OSError:
        return False


def normalize_genre_label(raw_name, typo_fixes):
    label = raw_name.strip().upper()
    return typo_fixes.get(label, label)


def find_all_markers(source_dirs, typo_fixes):
    """Returns {folder_path: genre_label} for every directory anywhere in
    the source trees that has a genre-marker .txt directly inside it."""
    markers = {}
    for src in source_dirs:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for fn in files:
                if not fn.lower().endswith('.txt'):
                    continue
                fp = Path(root) / fn
                if is_genre_marker(fp):
                    genre = normalize_genre_label(fn[:-4], typo_fixes)
                    if root in markers and markers[root] != genre:
                        logger.warning(f"Multiple genre markers in the same folder, keeping first: {root} ({markers[root]} vs {genre})")
                        continue
                    markers[root] = genre
    return markers


def find_pack_roots(source_dirs):
    """Top-level pack folders under each source dir, descending through
    known generic aggregator containers (possibly nested) to reach the
    real pack names."""
    roots = []

    def collect(base):
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            return
        for entry in entries:
            full = os.path.join(base, entry)
            if not os.path.isdir(full) or entry in IGNORE_DIRS:
                continue
            if entry.lower() in GENERIC_PACK_CONTAINERS:
                collect(full)
            else:
                roots.append(full)

    for src in source_dirs:
        collect(src)
    return roots


def match_main_genre(name, genre_keywords):
    """Word-boundary match against a flattened main-genre keyword list —
    normalizes _/-/. to spaces first (scene-release-style pack names join
    words with periods, e.g. 'Rawcutz.ill.Spark.Hip.Hop.Beats')."""
    text = re.sub(r'[_\-.]+', ' ', name.lower())
    for genre, keywords in genre_keywords.items():
        for keyword in keywords:
            kw = keyword.lower()
            pattern = r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])'
            if re.search(pattern, text):
                return genre
    return None


def resolve_copy_units(source_dirs, config):
    """Returns (copy_units, unresolved_pack_roots).
    copy_units: list of (folder_path, genre) — everything that will actually be copied.
    unresolved_pack_roots: pack roots with no marker anywhere inside and no fallback match — reported, not copied."""
    markers = find_all_markers(source_dirs, config['marker_typo_fixes'])
    marked_dirs = set(markers)

    marked_ancestors = set()
    source_dirs_norm = {os.path.normpath(s) for s in source_dirs}
    for d in marked_dirs:
        p = d
        while True:
            parent = os.path.dirname(p)
            if parent == p or os.path.normpath(parent) in source_dirs_norm or parent == '':
                break
            marked_ancestors.add(parent)
            p = parent

    copy_units = [(folder, genre) for folder, genre in markers.items()]

    pack_roots = find_pack_roots(source_dirs)
    unresolved = []
    for root in pack_roots:
        if root in marked_dirs or root in marked_ancestors:
            continue  # handled by marker(s) inside it (whole or partial)
        genre = match_main_genre(os.path.basename(root), config['genre_keywords'])
        if genre:
            copy_units.append((root, genre))
        else:
            unresolved.append(root)

    return copy_units, unresolved


def copy_unit(folder, genre, destination_root, dry_run=False):
    """Copy one folder intact into destination_root/genre/<same folder name>.
    Idempotent: if the destination already exists, skip (assume already
    migrated) rather than re-copying or diffing — this is a fresh-build
    tool, not an incremental sync."""
    dest_dir = Path(destination_root) / genre
    dest_path = dest_dir / Path(folder).name

    if dest_path.exists():
        return 'skipped'

    if dry_run:
        return 'would_copy'

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(folder, dest_path)
        return 'copied'
    except Exception as e:
        logger.error(f"Failed copying {folder} -> {dest_path}: {e}")
        return 'failed'


def main():
    parser = argparse.ArgumentParser(description='KOLBIE SAMPLES — genre-marker-driven migration')
    parser.add_argument('--sources', nargs='+', required=True, help='Source directories to scan')
    parser.add_argument('--destination', required=True, help='Destination root (e.g. .../KOLBIE SAMPLES)')
    parser.add_argument('--config', default='config/main_genres.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    config = load_config(args.config)
    copy_units, unresolved = resolve_copy_units(args.sources, config)

    logger.info(f"Copy units resolved: {len(copy_units)}")
    logger.info(f"Pack roots with no genre (marker or fallback) — left out: {len(unresolved)}")

    stats = {'copied': 0, 'skipped': 0, 'would_copy': 0, 'failed': 0}
    for folder, genre in copy_units:
        result = copy_unit(folder, genre, args.destination, dry_run=args.dry_run)
        stats[result] += 1
        logger.info(f"[{result}] {genre} <- {folder}")

    logger.info("=" * 60)
    logger.info(f"Copied: {stats['copied']}  Skipped (already there): {stats['skipped']}  "
                f"Would copy (dry-run): {stats['would_copy']}  Failed: {stats['failed']}")

    if unresolved:
        report_path = Path(args.destination).parent / 'sem_genero_report.txt'
        try:
            report_path.write_text('\n'.join(sorted(unresolved)) + '\n')
            logger.info(f"Unresolved pack roots written to: {report_path}")
        except OSError as e:
            logger.warning(f"Could not write unresolved report: {e}")


if __name__ == '__main__':
    main()
