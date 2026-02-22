import re
from pathlib import Path
import soundfile as sf

from music_key import extract_key_from_name_tokens, normalize_key_query


_TOKEN_SPLIT = re.compile(r"[_\s\-]+")
_BPM_TOKEN = re.compile(r"(?:bpm)?(\d{2,3})(?:bpm)?", re.IGNORECASE)


def parse_sample_info(filepath):
    p = Path(filepath)
    tokens = [t for t in _TOKEN_SPLIT.split(p.stem) if t]
    lower_tokens = [t.lower() for t in tokens]

    result = {
        "filename": p.name,
        "path": str(p),
        "type": None,
        "form": None,
        "bpm": None,
        "key": None,
        "time": None
    }

    type_keywords = ["kick", "snare", "clap", "hat", "bass", "fx", "perc", "vocal", "melody", "drum"]
    form_keywords = {"loop", "one_shot", "oneshot", "shot", "fill"}

    for token in lower_tokens:
        if token in type_keywords and result["type"] is None:
            result["type"] = token

        if token in form_keywords and result["form"] is None:
            if "loop" in token:
                result["form"] = "loop"
            elif "fill" in token:
                result["form"] = "fill"
            else:
                result["form"] = "one-shot"

        bpm_match = _BPM_TOKEN.fullmatch(token)
        if bpm_match and result["bpm"] is None:
            bpm_val = int(bpm_match.group(1))

            if "bpm" in token:
                result["bpm"] = bpm_val

            elif 60 <= bpm_val <= 200:
                result["bpm"] = bpm_val

    result["key"] = extract_key_from_name_tokens(tokens)

    try:
        with sf.SoundFile(str(p)) as f:
            total_seconds = len(f) / f.samplerate
            result["time"] = f"{total_seconds:.2f}s"

    except Exception as e:
        print(f"[DEBUG: SoundFile Error] Failed to read time for {p.name}: {e}")
        result["time"] = "Err"

    return result


def normalize_key(key_str):
    return normalize_key_query(key_str)


def scan_folder(folder_path):
    folder = Path(folder_path)
    all_wav_files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() == ".wav"]
    parsed_results = []

    for f in all_wav_files:
        parsed = parse_sample_info(str(f))
        parsed_results.append(parsed)

    return parsed_results


def search_samples(samples, keywords, bpm_min, bpm_max, key, form):
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

        if form.lower() != "all" and sample["form"] != form.lower():
            return False

        return True

    return [s for s in samples if matches(s)]
