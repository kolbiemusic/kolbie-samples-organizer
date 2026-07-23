"""
Shared genre-from-path matching for MIDI + Presets.

Same technique AudioAnalyzer._extract_genre_from_path() uses for audio
files: genre in this whole library is signaled by keywords in folder/pack
names (e.g. ".../HYPNOTICTECHNO Zenhiser/..." matches "techno" as a
substring), not by any audio-content analysis — so it's exactly as valid
for a .mid or .fxp file's path as for a .wav's. Kept as a small standalone
function (not an import from audio_analyzer.py) to keep this pipeline
fully isolated from the audio one, per the existing architecture decision.
Reads config/genre_mapping.json's genre_keywords read-only — never writes
to it, so the audio pipeline's config stays untouched.
"""


def extract_genre_from_path(filepath, genre_keywords):
    """Search the full path (not just filename) for a genre keyword. Returns the genre name or None."""
    path_lower = str(filepath).lower()
    for genre, keywords in genre_keywords.items():
        for keyword in keywords:
            if keyword.lower() in path_lower:
                return genre
    return None


# Mirrors AudioAnalyzer.GENERIC_PACK_CONTAINERS (audio_analyzer.py) — same
# real-data finding, same reasoning: these are aggregator folders that
# bundle many distinct packs one level down, not packs themselves.
GENERIC_PACK_CONTAINERS = {
    'splice', 'slate samples', 'algonautcontent', 'packs installed',
}


def resolve_pack_name(filepath, source_dir):
    """Return the source pack's own folder name for a file, skipping
    generic aggregator folders. None if there's no pack folder (file sits
    directly in the source root) or source_dir is unknown."""
    if not source_dir:
        return None
    from pathlib import Path
    try:
        rel = Path(filepath).resolve().relative_to(source_dir)
    except ValueError:
        return None

    parts = rel.parts[:-1]  # drop the filename itself
    if not parts:
        return None

    for part in parts:
        if part.lower() not in GENERIC_PACK_CONTAINERS:
            return part
    return parts[-1]


def fallback_genre_from_pack(filepath, source_dir, pack_genre_overrides=None):
    """When no genre keyword matches, resolve to a researched genre
    (pack_genre_overrides, keyed by exact pack folder name — see
    config/genre_mapping.json) or the pack's own folder name, instead of
    a meaningless generic bucket. Returns 'Outros' only when there's truly
    no pack folder to name the file after."""
    pack_name = resolve_pack_name(filepath, source_dir)
    if pack_name is None:
        return 'Outros'

    overrides = pack_genre_overrides or {}
    researched_genre = overrides.get(pack_name) or overrides.get(pack_name.lower())
    return researched_genre or pack_name
