"""Make LLM markdown listenable: drop code/paths/hashes/URLs, keep prose, bullets and pauses."""
import re

EXT = r"py|rs|js|ts|tsx|jsx|php|md|json|toml|yml|yaml|sh|log|sql|html|css|go|env|txt|lock|pt|wav"


def clean(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)                       # code blocks
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.M)                   # table rows
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)                   # links -> label
    text = re.sub(r"https?://\S+", " ", text)
    # inline code: keep plain words, drop anything that looks like code/path/command
    text = re.sub(r"`([^`\n]*)`", lambda m: m.group(1) if re.fullmatch(r"[^\W\d_][\w ]{0,24}", m.group(1)) else " ", text)
    text = re.sub(r"(?<![\w/])(?:~|\.{1,2})?(?:/[\w.\-@+]+)+/?", " ", text)   # absolute / ~ paths
    text = re.sub(r"(?<![\w/])[\w.\-@+]+(?:/[\w.\-@+]+){2,}", " ", text)      # a/b/c relative paths
    text = re.sub(rf"\b[\w\-]+\.(?:{EXT})\b", "plik", text)                   # file names
    text = re.sub(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", " ", text)  # UUID
    text = re.sub(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", " ", text)  # git-like hashes
    text = re.sub(r"\b(?=\w*[^\W\d])(\w+)_(\w+(?:_\w+)*)\b", lambda m: m.group(0).replace("_", " "), text)  # snake_case
    text = re.sub(r"^\s*#+\s*(.*?)\s*$", r"\1.", text, flags=re.M)             # headers -> sentence
    text = re.sub(r"^(\s*)[*•]\s+", r"\1- ", text, flags=re.M)                 # bullets normalised, kept
    text = re.sub(r"[*_~>`]+", "", text)                                       # emphasis markers
    text = re.sub(r"[^\w\s.,!?;:()%/+\-–—…'\"]", " ", text)                    # emoji, box chars, symbols
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def sentences(text, cap=None):
    """Cleaned text -> list of sentences; with `cap`, stop after the last sentence that still fits."""
    out, total = [], 0
    for s in re.split(r"(?<=[.!?…])\s+|\n+", clean(text)):
        s = s.strip()
        if not s:
            continue
        if cap and out and total + len(s) > cap:  # always keep at least the first sentence
            break
        total += len(s) + 1
        if out and len(out[-1]) < 40:  # glue tiny pieces, very short clips get clipped by the model
            out[-1] += " " + s
        else:
            out.append(s)
    return out


def _check():
    t = clean("## Wynik\n* Plik `daemon.py` w /home/leszek/kody/tts/voice/daemon.py działa.\n"
              "- Commit a1b2c3d4e5 i `rm -rf /` oraz sanitize_summary, zobacz https://x.y/z.\n```py\nx=1\n```\nGotowe ✅")
    assert "/home" not in t and "rm -rf" not in t and "a1b2c3d4e5" not in t and "```" not in t and "✅" not in t, t
    assert "sanitize summary" in t and "\n- Commit" in t and t.startswith("Wynik."), t
    long = " ".join(f"Zdanie numer {i} jest całkiem zwyczajne." for i in range(200))
    cut = sentences(long, 4000)
    assert 3500 < len(" ".join(cut)) <= 4000 and cut[-1].endswith("."), len(" ".join(cut))
    assert len(sentences(long)) > len(cut) and sentences("x" * 5000 + ". Drugie.", 100)[0].startswith("xxx")
    assert clean("TCP/IP i i/lub 3.5 oraz `plan`") == "TCP/IP i i/lub 3.5 oraz plan"


if __name__ == "__main__":
    _check()
    print("textclean ok")
