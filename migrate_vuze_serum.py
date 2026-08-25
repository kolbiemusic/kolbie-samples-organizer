#!/usr/bin/env python3
"""
Third-party Serum preset library migration — deep-genre-resolution rewrite (2026-08-25)

Recreation of a one-off scratchpad script from 2026-08-12 (vuze_serum_migrate.py +
reorg_bundles.py, lost when that session's temp scratchpad was cleaned up),
rewritten as a single proper, reusable, git-tracked script under a new name.

Migrates a downloaded third-party Serum preset library (default use case:
VUZE/SERUM PRESETS) straight into the real Xfer Serum 2 plugin folder — NOT
the KOLBIE SAMPLES tree. Presets go to Presets/User/{genre}/..., and any new
wavetables/samples that ship alongside the presets go to sibling Tables/User
and Samples/User folders, matching Serum's own SaveYourTablesHere.txt /
SaveYourContentHere.txt convention.

Genre resolution, tried per FILE (not just once per pack), in order:
  1. Deepest-path-component-wins: walk the file's path relative to its pack
     root from deepest to shallowest, word-boundary-matching each component
     against config/main_genres.json (same list/logic as migrate_by_genre.py,
     imported not duplicated). This single pass handles both ordinary
     single-genre packs AND "bundle" packs that already organize themselves
     by genre internally (e.g. W.A Production - Total Presets Bundle/.../
     WAP - Serum Presets/House/...) — no separate bundle-splitting script
     needed this time.
  2. If nothing in the path matches, fall back to a pack-level genre:
     a. MANUAL_OVERRIDES — hardcoded substring-matched dict for packs whose
        genre isn't spelled out anywhere in their own path and had to be
        found by web research (WebSearch) in the original 2026-08-12 run.
        Extend this dict as more packs get researched.
     b. Keyword match against the pack's own root folder name.
     c. Last resort: the pack's own folder name, verbatim, becomes its own
        genre folder — better than silently dropping it; fix later once
        its real genre is known (rename the folder or extend the config).

Usage:
    python3 migrate_vuze_serum.py --source "/Volumes/Gui 2TB Dados/VUZE/SERUM PRESETS" --dry-run
    python3 migrate_vuze_serum.py --source "/Volumes/Gui 2TB Dados/VUZE/SERUM PRESETS"
"""
import argparse
import logging
import re
import shutil
from pathlib import Path

from migrate_by_genre import load_config, match_main_genre, IGNORE_DIRS

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

PRESET_EXTENSIONS = {'.serumpreset', '.fxp'}
WAVETABLE_EXTENSIONS = {'.wt'}
SAMPLE_AUDIO_EXTENSIONS = {'.wav', '.aif', '.aiff'}

# Other synths that also use .fxp -- same reasoning as migrate_serum_presets.py:
# same extension does not mean same plugin, so exclude when the path names a
# different synth.
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

# Web-researched genre for packs whose own path doesn't spell out a genre
# anywhere -- confirmed against artist bios / label / Splice pack pages in
# the original 2026-08-12 run. Matched as a case-insensitive substring
# against the pack's root folder name. Extend as more packs get researched.
MANUAL_OVERRIDES = {
    'cruels': 'Trap',
    'late night nostalgia': 'LoFi',
    'freshly squeezed definitive collection': 'Pop',
    'overdrive': 'Techno',
    'dimension essentials': 'Techno',
    'bass drops': 'Dubstep',
}

DEMO_PREVIEW_RE = re.compile(r'(?<![a-z0-9])(demo|preview)(?![a-z0-9])', re.IGNORECASE)


def normalize(text):
    return re.sub(r'[_\-.]+', ' ', text.lower())


def is_other_synth_fxp(filepath):
    return bool(_OTHER_SYNTH_RE.search(normalize(str(filepath))))


def is_demo_preview(filepath):
    return bool(DEMO_PREVIEW_RE.search(filepath.stem))


def find_pack_roots(source_dir):
    """Top-level folders directly under source_dir -- each is one pack."""
    try:
        entries = sorted(Path(source_dir).iterdir())
    except OSError:
        return []
    return [e for e in entries if e.is_dir() and e.name not in IGNORE_DIRS]


def deepest_genre_in_path(rel_path, genre_keywords):
    """Check each path component from deepest to shallowest; first
    word-boundary keyword match wins. Handles bundle packs organized
    internally by genre, and ordinary packs alike."""
    for part in reversed(rel_path.parts):
        genre = match_main_genre(part, genre_keywords)
        if genre:
            return genre
    return None


def resolve_pack_genre(pack_root, genre_keywords):
    """Pack-level fallback genre, used only for files whose own relative
    path has no genre keyword anywhere in it."""
    name_l = pack_root.name.lower()
    for phrase, genre in MANUAL_OVERRIDES.items():
        if phrase in name_l:
            return genre
    genre = match_main_genre(pack_root.name, genre_keywords)
    if genre:
        return genre
    return pack_root.name  # last resort: pack keeps its own name as its genre


def migrate_pack(pack_root, genre_keywords, dest_root, dry_run=False):
    stats = {'presets': 0, 'wavetables': 0, 'samples': 0,
              'skipped': 0, 'excluded_other_synth': 0, 'excluded_demo': 0}
    fallback_genre = resolve_pack_genre(pack_root, genre_keywords)

    for src_file in pack_root.rglob('*'):
        if not src_file.is_file() or src_file.name == '.DS_Store':
            continue

        rel = src_file.relative_to(pack_root)
        ext = src_file.suffix.lower()
        genre = deepest_genre_in_path(rel, genre_keywords) or fallback_genre

        if ext in PRESET_EXTENSIONS:
            if ext == '.fxp' and is_other_synth_fxp(src_file):
                stats['excluded_other_synth'] += 1
                continue
            dest_file = Path(dest_root) / 'Presets' / 'User' / genre / pack_root.name / rel
            kind = 'presets'
        elif ext in WAVETABLE_EXTENSIONS:
            dest_file = Path(dest_root) / 'Tables' / 'User' / genre / pack_root.name / rel
            kind = 'wavetables'
        elif ext in SAMPLE_AUDIO_EXTENSIONS:
            if is_demo_preview(src_file):
                stats['excluded_demo'] += 1
                continue
            dest_file = Path(dest_root) / 'Samples' / 'User' / genre / pack_root.name / rel
            kind = 'samples'
        else:
            continue

        if dest_file.exists():
            stats['skipped'] += 1
            continue
        if dry_run:
            stats[kind] += 1
            continue

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src_file, dest_file)
            stats[kind] += 1
        except OSError as e:
            logger.error(f"Failed copying {src_file} -> {dest_file}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description='Third-party Serum preset library migration (deep genre resolution)')
    parser.add_argument('--source', required=True, help='Root folder containing downloaded preset packs (one subfolder per pack)')
    parser.add_argument('--destination', default='/Library/Audio/Presets/Xfer Records/Serum 2 Presets',
                         help='Serum 2 plugin root -- Presets/User, Tables/User, Samples/User are created under it')
    parser.add_argument('--config', default='config/main_genres.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    config = load_config(args.config)
    pack_roots = find_pack_roots(args.source)
    total = len(pack_roots)
    logger.info(f"Pack roots found: {total}")

    totals = {'presets': 0, 'wavetables': 0, 'samples': 0,
              'skipped': 0, 'excluded_other_synth': 0, 'excluded_demo': 0}
    for i, pack_root in enumerate(pack_roots, start=1):
        stats = migrate_pack(pack_root, config['genre_keywords'], args.destination, dry_run=args.dry_run)
        logger.info(f"PROGRESS {i}/{total}")
        logger.info(f"[{pack_root.name}] {stats}")
        for k, v in stats.items():
            totals[k] += v

    logger.info("=" * 60)
    logger.info(f"Totals: {totals}")


if __name__ == '__main__':
    main()
