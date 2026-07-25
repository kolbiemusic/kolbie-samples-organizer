"""
Synth/DAW preset metadata extraction — tier-aware, deliberately shallow.

Tier A formats (.serumpreset, .vital, .sfz) are text/JSON under the hood in
at least some versions, so a real parse is attempted: JSON first, then a
plain-text fallback. Neither format is fully documented publicly, so a
failed parse is never treated as an invalid file — it just degrades to
filename-only metadata with parse_confidence=0.0. Tier B formats (.fxp,
.nki, .nmsv, .repatch, .spf/.spf2, .h2p, .sxt/.flx/.kit, .exs) are
undocumented proprietary binaries; no attempt is made to read their
content at all — reverse-engineering ~10 different binary formats for a
personal sample library has poor ROI compared to just copying+indexing
them by filename and inferred plugin family.

Category priority — reversed 2026-07-25 at explicit user request: filename
is checked first, Tier A's parsed content only fills the category in when
the filename didn't already resolve one. Same "folder/filename text is the
majority source" rule as the audio pipeline and MIDI tempo, extended here
too even though Tier A content is a real field read out of the preset's
own data, not a discretionary tag.
"""
import json
import logging
import os
from pathlib import Path

from .genre_matcher import extract_genre_from_path, fallback_genre_from_pack
from .category_matcher import extract_category_from_filename

logger = logging.getLogger(__name__)

TIER_A_EXTENSIONS = {'.serumpreset', '.vital', '.sfz'}


def _parse_tier_a_content(filepath):
    """Best-effort JSON-then-text parse. Never raises. Returns (name, category, confidence, method)."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        logger.debug(f"Could not read {filepath} as text: {e}")
        return None, None, 0.0, 'filename_fallback'

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        data = None
    except Exception as e:
        logger.debug(f"Unexpected error JSON-parsing {filepath}: {e}")
        data = None

    if isinstance(data, dict):
        preset_name = None
        for name_key in ('name', 'preset_name', 'title'):
            value = data.get(name_key)
            if isinstance(value, str) and value.strip():
                preset_name = value.strip()
                break

        category = None
        for cat_key in ('category', 'type', 'preset_type', 'tags'):
            value = data.get(cat_key)
            if isinstance(value, str) and value.strip():
                category = value.strip()
                break
            if isinstance(value, list) and value:
                category = str(value[0]).strip()
                break

        return preset_name, category, 1.0, 'json'

    # Not JSON (or not a JSON object) — .sfz and similar are plain text with
    # opcode=value lines, no reliable "name" field. Just confirm it's real
    # readable text worth indexing as such, rather than guessing at content.
    if content.strip():
        return None, None, 0.4, 'text'

    return None, None, 0.0, 'filename_fallback'


class PresetAnalyzer:
    def __init__(self, config, genre_keywords=None, source_dir=None, pack_genre_overrides=None):
        self.extension_map = config.get('extension_plugin_map', {})
        self.default_plugin_family = config.get('default_plugin_family', 'Unknown_Plugin')
        self.default_category = config.get('default_category', 'Uncategorized')
        self.category_keywords = config.get('category_keywords', {})
        self.genre_keywords = genre_keywords or {}
        self.source_dir = source_dir
        self.pack_genre_overrides = pack_genre_overrides or {}

    def is_valid_preset(self, filepath):
        """Weak validation by design — see module docstring. Just existence + non-empty + known extension."""
        try:
            path = Path(filepath)
            ext = path.suffix.lower()
            if ext not in self.extension_map:
                return False
            return path.stat().st_size > 0
        except Exception as e:
            logger.warning(f"Could not stat preset file {filepath}: {e}")
            return False

    def analyze_file(self, filepath):
        filepath = str(filepath)
        path = Path(filepath)
        ext = path.suffix.lower()
        ext_info = self.extension_map.get(ext, {})
        plugin_family = ext_info.get('plugin_family', self.default_plugin_family)
        config_tier = ext_info.get('tier', 'B')

        result = {
            'original_path': filepath,
            'filename': path.name,
            'extension': ext,
            'genre': 'Outros',
            'plugin_family': plugin_family,
            'tier': 'A_parsed' if config_tier == 'A' else 'B_indexed',
            'preset_name': path.stem,
            'category': self.default_category,
            'parse_confidence': 0.0,
            'parse_method': 'unparsed_binary',
            'file_size_bytes': 0,
            'source': ['filename'],
        }

        try:
            genre = extract_genre_from_path(filepath, self.genre_keywords)
            if genre:
                result['genre'] = genre
                result['source'].append('filename_genre')
            else:
                result['genre'] = fallback_genre_from_pack(filepath, self.source_dir, self.pack_genre_overrides)
                result['source'].append('default_genre')
        except Exception as e:
            logger.debug(f"Could not determine genre for {filepath}: {e}")

        try:
            result['file_size_bytes'] = path.stat().st_size
        except Exception as e:
            logger.debug(f"Could not stat {filepath}: {e}")

        # Filename-based category (BS -> Bass, PD -> Pad, ...) checked FIRST
        # now (priority-order change, 2026-07-25, explicit user request):
        # folder/filename text is the majority source across this whole
        # project — same rule as the audio pipeline and MIDI tempo, applied
        # here too even though Tier A content is a real field parsed out of
        # the preset's own data, not a discretionary tag. This is also the
        # path that populates most Tier B files, which never get
        # content-parsed at all.
        try:
            category = extract_category_from_filename(path.name, self.category_keywords)
            if category:
                result['category'] = category
                result['source'].append('filename_category')
        except Exception as e:
            logger.debug(f"Could not determine category from filename for {filepath}: {e}")

        if config_tier == 'A' and ext in TIER_A_EXTENSIONS:
            name, category, confidence, method = _parse_tier_a_content(filepath)
            result['parse_confidence'] = confidence
            result['parse_method'] = method
            if name:
                result['preset_name'] = name
                result['source'].append('content_name')
            # Only fills the category in when the filename didn't already
            # resolve one — reversed from before, see comment above.
            if category and result['category'] == self.default_category:
                result['category'] = category
                result['source'].append('content_category')

        return result
