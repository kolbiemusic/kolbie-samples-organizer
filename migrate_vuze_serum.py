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
# anywhere -- confirmed against artist bios / label / Splice pack pages.
# Matched as a case-insensitive substring against the pack's root folder
# name. Extend as more packs get researched (don't reintroduce a "pack's
# own name becomes the genre" fallback -- that's what caused the 2026-08-25
# mess of ~40 junk one-pack "genre" folders; unresolved packs are reported
# and skipped instead, see main()).
MANUAL_OVERRIDES = {
    'cruels': 'Trap',
    'late night nostalgia': 'LoFi',
    'serum 2 definitive collection': 'Pop',
    'overdrive': 'Techno',
    'dimension essentials': 'Techno',
    'bass drops': 'Dubstep',
    # researched 2026-08-25 (VUZE remediation pass):
    'cyberpunk essentials': 'Synthwave',
    'future progressive': 'House',
    'cloudpop': 'Pop',
    'jilax': 'Trance',
    'neo electronica': 'Synthwave',
    'the 80s for serum': 'Synthwave',
    'music production biz': 'Techno',
    'odd frequency - pulse': 'Indie Dance',
    'portify': 'Future Bass',
    'feelings vol.2': 'House',
    'renraku serum 2 bass one': 'Dubstep',
    'ultimate reese': 'DnB',
    'tisoki sounds vol. 2': 'Dubstep',
    'unmute - places': 'Techno',
    'bad royale': 'Future Bass',
    'crnkn': 'Future Bass',
    'continuity vol. 3 by gill chang': 'Future Bass',
    'words unspoken': 'Chillwave',
    'kompany kollection': 'Dubstep',
    'mike hawkins': 'House',
    'morgan page sample pack': 'House',
    'paperwhite presents the feels': 'Pop',
    'smle sample pack': 'Future Bass',
    'spirix sounds': 'Future Bass',
    'stélouse loose sounds': 'Future Bass',
    'subtronics': 'Dubstep',
    'the sounds u need': 'Dubstep',
    'vaski serum pack': 'Dubstep',
    'donuts & dinosaurs': 'Future Bass',
    'heavenly keys with eric butler': 'HipHop',
    'serum fire with von xon': 'RnB',
    'fabian mazur - wubz': 'Dubstep',
    'oliver power tools': 'Disco',
    'wax motif': 'House',
    'world club sounds': 'Dancehall',
    'karra': 'Pop',
    'og parker': 'HipHop',
    'virtual riot': 'Dubstep',
    'swag type beats': 'Pop',
    'vital serum preset': 'Future Bass',
    # user's own manual rename of the destination folder (confirmed
    # intentional, not a bug, 2026-08-12) -- keyword-matches "pluggnb"
    # otherwise, which would keep recreating a duplicate Pluggnb copy.
    'serum 2 pluggnb - new jazz': 'NEW JAZZ',
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
    """Check each DIRECTORY component (not the preset's own filename) from
    deepest to shallowest; first word-boundary keyword match wins (also
    checking MANUAL_OVERRIDES phrases as a substring on each component --
    bundle packs often organize by a sub-product name, like PML's
    "Overdrive"/"Bass Drops", that only resolves to a genre via research,
    not a keyword). Handles bundle packs organized internally by genre, and
    ordinary packs alike.

    The filename itself is deliberately excluded: a preset's own name is a
    TIMBRE/sound-type descriptor ("Pad - Ambient Rave", "LEAD - Ambient"),
    not a genre marker -- matching genre keywords against it pulled single
    presets like an ambient-flavored pad out of an otherwise all-Pop pack
    into a fake one-file "Ambient" folder (caught 2026-08-25, user: "ambient
    e subcategoria do timbre, nao genero"). Folder names are much more
    reliably genuine genre organization (bundle subfolders, pack names)."""
    for part in reversed(rel_path.parts[:-1]):
        # MANUAL_OVERRIDES checked first -- a curated research decision
        # (or a user's own explicit rename, e.g. NEW JAZZ) must win over a
        # generic keyword substring match on the same folder name.
        part_norm = normalize(part)
        for phrase, override_genre in MANUAL_OVERRIDES.items():
            if normalize(phrase) in part_norm:
                return override_genre
        genre = match_main_genre(part, genre_keywords)
        if genre:
            return genre
    return None


def resolve_pack_genre(pack_root, genre_keywords):
    """Pack-level fallback genre, used only for files whose own relative
    path has no genre keyword anywhere in it. Returns None if nothing
    matches -- callers must NOT invent a genre from the pack's own name
    (that's what caused the 2026-08-25 mess); unresolved packs get
    reported and skipped instead, see main()."""
    name_norm = normalize(pack_root.name)  # scene-release names join words with '.', not spaces
    for phrase, genre in MANUAL_OVERRIDES.items():
        if normalize(phrase) in name_norm:
            return genre
    return match_main_genre(pack_root.name, genre_keywords)


def migrate_pack(pack_root, genre_keywords, dest_root, dry_run=False):
    stats = {'presets': 0, 'wavetables': 0, 'samples': 0,
              'skipped': 0, 'excluded_other_synth': 0, 'excluded_demo': 0,
              'excluded_unresolved': 0}
    fallback_genre = resolve_pack_genre(pack_root, genre_keywords)

    for src_file in pack_root.rglob('*'):
        if not src_file.is_file() or src_file.name == '.DS_Store':
            continue

        rel = src_file.relative_to(pack_root)
        ext = src_file.suffix.lower()
        genre = deepest_genre_in_path(rel, genre_keywords) or fallback_genre

        if genre is None:
            stats['excluded_unresolved'] += 1
            continue

        if ext in PRESET_EXTENSIONS:
            # Check the path RELATIVE TO THE PACK ROOT only -- not the full
            # absolute path. A pack root is often named to advertise every
            # format it bundles (e.g. "... (WAV, SERUM, SYLENTH1)" or
            # "...Wav.Sylenth1.Serum.Spire"), with genuine per-synth
            # subfolders (Presets/Serum/, Presets/Sylenth1/) inside. Checking
            # the full path made the pack's own name false-positive-exclude
            # every single .fxp, including the real Presets/Serum/ ones --
            # silently dropped two whole packs (caught 2026-08-29, user:
            # "vc nao migrou nenhum pack do serum de Progressive?").
            if ext == '.fxp' and is_other_synth_fxp(rel):
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
              'skipped': 0, 'excluded_other_synth': 0, 'excluded_demo': 0,
              'excluded_unresolved': 0}
    unresolved_packs = []
    for i, pack_root in enumerate(pack_roots, start=1):
        stats = migrate_pack(pack_root, config['genre_keywords'], args.destination, dry_run=args.dry_run)
        logger.info(f"PROGRESS {i}/{total}")
        logger.info(f"[{pack_root.name}] {stats}")
        if stats['excluded_unresolved']:
            unresolved_packs.append(pack_root.name)
        for k, v in stats.items():
            totals[k] += v

    logger.info("=" * 60)
    logger.info(f"Totals: {totals}")

    if unresolved_packs:
        logger.info(f"Packs with no resolvable genre (skipped, not copied): {len(unresolved_packs)}")
        report_path = Path(args.destination) / 'vuze_sem_genero_report.txt'
        try:
            report_path.write_text('\n'.join(sorted(unresolved_packs)) + '\n')
            logger.info(f"Unresolved packs written to: {report_path}")
            logger.info("Add an entry to MANUAL_OVERRIDES in this script (web-research the genre) and re-run to pick them up.")
        except OSError as e:
            logger.warning(f"Could not write unresolved report: {e}")


if __name__ == '__main__':
    main()
