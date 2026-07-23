#!/usr/bin/env python3
"""
Pre-flight audit: run before any real migration cycle.

Walks a source folder and classifies every audio file's genre the same
way migrate_samples.py will, without touching audio content (no librosa
load — this is a path/keyword sweep only, seconds not hours). Reports:
  - how many files match a registered genre keyword
  - how many fall back to their real pack folder name (and which names)
  - how many have no pack folder at all (literal 'Outros')

Run this whenever config/genre_mapping.json changes, or before starting
a new source folder for the first time, to catch taxonomy gaps (a real
style name sitting in a folder that isn't registered yet) before they
turn into thousands of miscategorized files.

Usage:
  python3 audit_genre_coverage.py --source-dir "/path/to/source"
  python3 audit_genre_coverage.py --all-known-sources
"""
import argparse
import json
import os
from pathlib import Path
from collections import Counter

from modules.audio_analyzer import AudioAnalyzer

AUDIO_EXT = {'.wav', '.aif', '.aiff', '.mp3', '.flac'}

KNOWN_SOURCES = [
    "/Volumes/Gui 2TB Dados/-ELETRONIC MUSIC-",
    "/Volumes/Gui 2TB Dados/SAMPLES ABLETON",
    "/Volumes/Gui 2TB Dados/NEW SAMPLES N PRESETS",
]


def audit_source(source_dir, config, genre_hits, researched_hits, pack_fallback_hits, literal_outros_examples):
    source_dir = str(Path(source_dir).resolve())
    cfg = dict(config)
    cfg['_source_dir'] = source_dir
    analyzer = AudioAnalyzer(cfg)
    gk = config['genre_keywords']
    overrides = config.get('pack_genre_overrides', {})

    total = 0
    for root, _dirs, files in os.walk(source_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in AUDIO_EXT:
                continue
            total += 1
            fp = os.path.join(root, f)
            path_lower = fp.lower()

            matched = None
            for genre, kws in gk.items():
                if any(kw.lower() in path_lower for kw in kws):
                    matched = genre
                    break

            if matched:
                genre_hits[matched] += 1
                continue

            pack_name = analyzer._resolve_pack_name(fp)
            if pack_name and (overrides.get(pack_name) or overrides.get(pack_name.lower())):
                researched_hits[analyzer._fallback_genre_from_pack(fp)] += 1
                continue

            fallback = analyzer._fallback_genre_from_pack(fp)
            pack_fallback_hits[fallback] += 1
            if fallback == 'Outros' and len(literal_outros_examples) < 20:
                literal_outros_examples.append(fp)

    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source-dir', help='Single source folder to audit')
    parser.add_argument('--all-known-sources', action='store_true',
                         help='Audit all 3 project source folders')
    parser.add_argument('--config', default='config/genre_mapping.json')
    args = parser.parse_args()

    if not args.source_dir and not args.all_known_sources:
        parser.error('Pass --source-dir or --all-known-sources')

    config = json.load(open(args.config))
    sources = KNOWN_SOURCES if args.all_known_sources else [args.source_dir]

    genre_hits = Counter()
    researched_hits = Counter()
    pack_fallback_hits = Counter()
    literal_outros_examples = []
    grand_total = 0

    for src in sources:
        if not os.path.isdir(src):
            print(f"[skip] not found: {src}")
            continue
        n = audit_source(src, config, genre_hits, researched_hits, pack_fallback_hits, literal_outros_examples)
        grand_total += n
        print(f"[ok] {src}: {n} audio files scanned")

    matched_total = sum(genre_hits.values())
    researched_total = sum(researched_hits.values())
    fallback_total = sum(pack_fallback_hits.values())
    literal_outros = pack_fallback_hits.get('Outros', 0)

    print()
    print("=" * 70)
    print(f"Total de arquivos de áudio: {grand_total}")
    print(f"Gênero real (keyword cadastrada): {matched_total} ({100*matched_total/grand_total:.1f}%)")
    print(f"Gênero via pesquisa (pack_genre_overrides): {researched_total} ({100*researched_total/grand_total:.1f}%)")
    print(f"Fallback (nome do pack original, sem gênero conhecido): {fallback_total} ({100*fallback_total/grand_total:.1f}%)")
    print(f"  dos quais 'Outros' literal (sem pasta-pack): {literal_outros}")
    print("=" * 70)

    if literal_outros:
        print("\nExemplos de arquivo sem nenhuma pasta-pack acima (Outros literal):")
        for ex in literal_outros_examples:
            print(f"  {ex}")

    print("\nTop 20 pastas-pack AINDA sem gênero conhecido (candidatas a pesquisa —")
    print("nome de artista/label/empresa que pode revelar um gênero real):")
    for name, cnt in pack_fallback_hits.most_common(20):
        if name == 'Outros':
            continue
        print(f"  {cnt:6d}  {name}")

    if researched_hits:
        print("\nGêneros já resolvidos via pesquisa nesta sessão:")
        for name, cnt in researched_hits.most_common():
            print(f"  {cnt:6d}  {name}")


if __name__ == '__main__':
    main()
