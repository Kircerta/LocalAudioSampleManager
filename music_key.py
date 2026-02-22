import re
from typing import Iterable, Optional


_KEY_PATTERN = re.compile(
    r"^\s*([A-Ga-g])\s*([#b]?)\s*(maj(?:or)?|min(?:or)?|m|M)?\s*$",
    re.IGNORECASE,
)
_NOTE_ONLY_PATTERN = re.compile(r"^[A-Ga-g][#b]?$")
_MINOR_WORDS = {"m", "min", "minor"}
_MAJOR_WORDS = {"maj", "major"}


def _normalize_accidental(symbol: str) -> str:
    return symbol


def _clean_token(token: str) -> str:
    return token.strip("()[]{}<>.,")


def normalize_key_query(key_text: Optional[str]) -> Optional[str]:
    """
    Convert key text into canonical format:
    - Major: A, Bb, F#
    - Minor: Am, Bbm, F#m
    """
    if key_text is None:
        return None

    normalized_input = key_text.replace("_", " ").replace("-", " ").strip()
    if not normalized_input:
        return None

    match = _KEY_PATTERN.fullmatch(normalized_input)
    if not match:
        return None

    note = match.group(1).upper()
    accidental = _normalize_accidental(match.group(2))
    suffix = match.group(3)

    is_minor = False
    if suffix:
        if suffix == "M":
            is_minor = False
        elif suffix.lower() in _MINOR_WORDS:
            is_minor = True
        elif suffix.lower().startswith("maj"):
            is_minor = False
        elif suffix.lower().startswith("min"):
            is_minor = True
        else:
            return None

    return f"{note}{accidental}{'m' if is_minor else ''}"


def extract_key_from_name_tokens(tokens: Iterable[str]) -> Optional[str]:
    """
    Extract key from filename tokens, preferring explicit major/minor markers.
    """
    cleaned_tokens = []
    for token in tokens:
        cleaned = _clean_token(token)
        if cleaned:
            cleaned_tokens.append(cleaned)
    if not cleaned_tokens:
        return None

    # Pass 1: explicit key tokens like "Amin", "Bbmaj", "F#m".
    for token in cleaned_tokens:
        match = _KEY_PATTERN.fullmatch(token)
        if not match or match.group(3) is None:
            continue
        parsed = normalize_key_query(token)
        if parsed:
            return parsed

    # Pass 2: note + separate mode token, e.g. "A minor", "Bb min".
    for idx in range(len(cleaned_tokens) - 1):
        note_token = cleaned_tokens[idx]
        mode_token = cleaned_tokens[idx + 1].lower()

        if not _NOTE_ONLY_PATTERN.fullmatch(note_token):
            continue

        if mode_token in _MINOR_WORDS:
            parsed = normalize_key_query(f"{note_token}m")
            if parsed:
                return parsed
        if mode_token in _MAJOR_WORDS:
            parsed = normalize_key_query(note_token)
            if parsed:
                return parsed

    # Pass 3: bare key token like "A", "Bb", "F#".
    for token in cleaned_tokens:
        if _NOTE_ONLY_PATTERN.fullmatch(token):
            if len(token) == 1 and token != token.upper():
                # Avoid treating stray lowercase letters (for example "b") as a key.
                continue
            parsed = normalize_key_query(token)
            if parsed:
                return parsed

    return None
