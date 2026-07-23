"""
Sound-role category extraction from filename tokens (BS -> Bass, PD -> Pad,
SQ -> Sequence, ...). See config/preset_mapping.json's category_keywords
for the researched + real-data-validated abbreviation list.

Unlike genre_matcher's substring-in-path search, this needs whole-token
matching: genre keywords are mostly full words ("techno", "house") where
an accidental substring hit is rare, but 2-3 letter role abbreviations
("bs", "ld", "sq") would false-positive constantly as plain substrings
(e.g. "bs" inside "Obsidian"). Splitting the filename stem into tokens on
non-alphanumeric characters and requiring an exact token match avoids that.
"""
import re
from pathlib import Path

_TOKEN_SPLIT = re.compile(r'[^a-zA-Z0-9]+')


def extract_category_from_filename(filename, category_keywords):
    """Whole-token match against the filename stem (not full path — pack folder names are noisy here)."""
    stem = Path(filename).stem
    tokens = {t.lower() for t in _TOKEN_SPLIT.split(stem) if t}

    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword.lower() in tokens:
                return category
    return None
