import re
from pathlib import Path

from music_key import extract_key_from_name_tokens, normalize_key_query


_TOKEN_SPLIT = re.compile(r"[_\s\-]+")
_BPM_TOKEN = re.compile(r"(?:bpm)?(\d{2,3})(?:bpm)?", re.IGNORECASE)


def parse_midi_info(filepath):
    p = Path(filepath)
    tokens = [t for t in _TOKEN_SPLIT.split(p.stem) if t]
    lower_tokens = [t.lower() for t in tokens]

    result = {
        "filename": p.name,
        "path": str(p),
        "bpm": None,
        "key": None,
        "type": "MIDI"
    }

    for token in lower_tokens:

        bpm_match = _BPM_TOKEN.fullmatch(token)
        if bpm_match and result["bpm"] is None:
            bpm_val = int(bpm_match.group(1))
            if "bpm" in token:
                result["bpm"] = bpm_val

            elif 60 <= bpm_val <= 200:
                result["bpm"] = bpm_val

    result["key"] = extract_key_from_name_tokens(tokens)

    return result


def normalize_key(key_str):
    return normalize_key_query(key_str)


def scan_midi_folder(folder_path):

    folder = Path(folder_path)
    all_midi_files = [
        f for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() in {".mid", ".midi"}
    ]
    parsed_results = []

    for f in all_midi_files:
        parsed = parse_midi_info(str(f))
        parsed_results.append(parsed)

    return parsed_results


def search_midi_samples(samples, keywords, bpm_min, bpm_max, key):

    def matches(sample):
        name = sample["filename"].lower()
        if not all(k in name for k in keywords):
            return False

        bpm = sample["bpm"]
        if bpm_min is not None or bpm_max is not None:
            if bpm is None: return False
            if bpm_min is not None and bpm < bpm_min: return False
            if bpm_max is not None and bpm > bpm_max: return False

        if key:
            normalized_search_key = normalize_key(key)
            normalized_sample_key = normalize_key(sample["key"])
            if normalized_sample_key != normalized_search_key:
                return False

        return True

    return [s for s in samples if matches(s)]
