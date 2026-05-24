# -*- coding: utf-8 -*-
"""
Input classifier: detect links vs AV numbers.
- Links → AI classifies as AV or movie later
- Anything else → treated as AV number, search sukebei
"""
import re

MAGNET_PATTERN = re.compile(r'^magnet:\?xt=urn:btih:', re.IGNORECASE)
ED2K_PATTERN = re.compile(r'^ed2k://', re.IGNORECASE)
THUNDER_PATTERN = re.compile(r'^thunder://', re.IGNORECASE)
AV_CODE_RE = re.compile(r'\b([A-Z]{3,5}-\d{3,5})\b')


def classify(text):
    """Classify input.
    Returns: ('av', code) for bare AV numbers,
             ('link', url) for magnet/ed2k/thunder,
             (None, text) for unrecognized.
    """
    text = text.strip()
    if not text:
        return (None, text)

    if MAGNET_PATTERN.match(text):
        return ('link', text)
    if ED2K_PATTERN.match(text):
        return ('link', text)
    if THUNDER_PATTERN.match(text):
        return ('link', text)

    # Multi-line batch links
    if '\n' in text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        valid = [l for l in lines if MAGNET_PATTERN.match(l) or ED2K_PATTERN.match(l) or THUNDER_PATTERN.match(l)]
        if valid:
            return ('link', '\n'.join(valid))
        return (None, text)

    # Check if it looks like an AV number
    m = AV_CODE_RE.search(text.upper())
    if m:
        code = m.group(1).upper()
        return ('av', code)

    # Everything else: treat as movie/search
    return ('movie_search', text.strip())
