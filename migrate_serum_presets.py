#!/usr/bin/env python3
"""
Serum / Serum 2 preset migration — genre-marker-driven (rewrite, 2026-07-26)

Scope narrowed to Serum only, per explicit user decision: every other
preset/synth format (Kontakt, EXS24, Massive, Diva, Arturia, generic FXP
banks, ...) is out of scope for this pass. Destination is the REAL Serum 2
plugin user-presets folder (not the KOLBIE PRESETS:MIDI tree), so presets
show up directly inside the plugin:

    /Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets/User/{genre}/...

Serum 2 already symlinks back to the original Serum 1 presets folder
("S1 Presets"), so dropping both .serumpreset (Serum's native format) and
plain .fxp (Serum's legacy format, pre-.serumpreset) here covers both
versions — confirmed with the user.

`.fxp` is shared by many different synths (Massive, Sylenth1, generic VST2
presets, ...), not just Serum — a `.fxp` sitting inside a folder whose path
names a DIFFERENT synth is excluded, since it almost certainly won't load
in Serum despite the shared extension (explicit user catch, 2026-07-26).

Reuses the same genre-marker / fallback-genre-from-pack-root resolution as
migrate_by_genre.py (imported, not duplicated) — a preset pack gets the
exact same genre as an audio pack would from the same marker/fallback rules.
"""
import argparse
import logging
import re
import shutil
from pathlib import Path

from migrate_by_genre import load_config, resolve_copy_units

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SERUM_EXTENSIONS = {'.serumpreset', '.fxp'}

# Other synths that also use .fxp — if any of these names appears anywhere
# in a .fxp file's path (case-insensitive, word-boundary), it's excluded:
# the shared extension doesn't mean it's a Serum preset.
OTHER_SYNTH_NAMES = [
    'sylenth', 'sylenth1', 'massive', 'diva', 'spire', 'nexus', 'omnisphere',
    'kontakt', 'absynth', 'zebra', 'zebra2', 'pigments', 'analog lab',
    'analoglab', 'fm8', 'reaktor', 'vital', 'nki', 'gforce', 'minimoog',
    'prophet', 'jupiter', 'arp2600', 'arp 2600', 'jup-8000', 'jup8000',
    'cs-80', 'cs80', 'ms-20', 'ms20', 'buchla',
]
_OTHER_SYNTH_RE = re.compile(
    r'(?<![a-z0-9])(' + '|'.join(re.escape(n) for n in OTHER_SYNTH_NAMES) + r')(?![a-z0-9])',
    re.IGNORECASE
)


def normalize(text):
    return re.sub(r'[_\-.]+', ' ', text.lower())


def is_other_synth_fxp(filepath):
    return bool(_OTHER_SYNTH_RE.search(normalize(str(filepath))))


def copy_serum_presets(folder, genre, destination_root, dry_run=False):
    """Filtered recursive copy of a copy-unit: only .serumpreset and
    eligible .fxp files, preserving the pack's relative folder structure."""
    dest_pack_root = Path(destination_root) / genre / Path(folder).name
    copied, skipped, excluded_other_synth = 0, 0, 0

    for src_file in Path(folder).rglob('*'):
        if not src_file.is_file():
            continue
        ext = src_file.suffix.lower()
        if ext not in SERUM_EXTENSIONS:
            continue

        rel = src_file.relative_to(folder)
        # Check the path RELATIVE TO THE COPY UNIT only -- not the full
        # absolute path. A folder is sometimes named to advertise every
        # synth format it bundles (e.g. "... (Serum, Sylenth1)"), with a
        # genuine Serum/ subfolder inside; checking the full path let the
        # folder's own name false-positive-exclude every .fxp in it,
        # including real Serum ones (same bug found and fixed in
        # migrate_vuze_serum.py, 2026-08-29).
        if ext == '.fxp' and is_other_synth_fxp(rel):
            excluded_other_synth += 1
            continue

        dest_file = dest_pack_root / rel

        if dest_file.exists():
            skipped += 1
            continue

        if dry_run:
            copied += 1
            continue

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src_file, dest_file)
            copied += 1
        except OSError as e:
            logger.error(f"Failed copying {src_file} -> {dest_file}: {e}")

    return copied, skipped, excluded_other_synth


def main():
    parser = argparse.ArgumentParser(description='Serum/Serum 2 preset migration')
    parser.add_argument('--sources', nargs='+', required=True)
    parser.add_argument('--destination', default='/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets/User')
    parser.add_argument('--config', default='config/main_genres.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    config = load_config(args.config)
    copy_units, unresolved = resolve_copy_units(args.sources, config)
    total = len(copy_units)
    logger.info(f"Copy units resolved: {total} (genre pipeline shared with audio migration)")

    total_copied, total_skipped, total_excluded = 0, 0, 0
    packs_with_presets = 0
    for i, (folder, genre) in enumerate(copy_units, start=1):
        copied, skipped, excluded = copy_serum_presets(folder, genre, args.destination, dry_run=args.dry_run)
        logger.info(f"PROGRESS {i}/{total}")
        if copied or skipped or excluded:
            packs_with_presets += 1
            logger.info(f"[{genre}] {Path(folder).name}: {copied} copied, {skipped} skipped, {excluded} excluded (other synth)")
        total_copied += copied
        total_skipped += skipped
        total_excluded += excluded

    logger.info("=" * 60)
    logger.info(f"Packs with Serum presets: {packs_with_presets}")
    logger.info(f"Total: {total_copied} copied, {total_skipped} skipped (already there), "
                f"{total_excluded} excluded (other synth's .fxp)")


if __name__ == '__main__':
    main()
