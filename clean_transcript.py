#!/usr/bin/env python3
"""summary_command for herdr-announcer: raw terminal tail on stdin -> the agent's last reply as plain text.

Heuristic (agy/codex-style TUIs): drop the bottom prompt box, tool-call and 'Thought' lines,
keep the trailing block of prose. Good enough for listening; not a parser.
"""
import re, sys

def extract(raw):
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", raw)
    lines = text.splitlines()
    # cut at the last horizontal rule (start of the prompt box)
    rules = [i for i, l in enumerate(lines) if re.fullmatch(r"\s*[─━═-]{20,}\s*", l)]
    if rules:
        lines = lines[: rules[-2] if len(rules) > 1 else rules[-1]]
    # keep everything after the last tool/thought marker line
    marks = [i for i, l in enumerate(lines) if re.match(r"\s*[●▸•⏺]\s", l)]
    if marks:
        last = marks[-1]
        is_thought = re.match(r"\s*▸\s+Thought", lines[last])
        lines = lines[last + 1:]
        # a "Thought" marker is followed by one truncated (ellipsis) paragraph: drop it
        if is_thought and lines and lines[0].rstrip().endswith(("...", "…")):
            lines = lines[1:]
    keep = [l.strip() for l in lines if l.strip() and "ctrl+o" not in l and not re.match(r"^\W*\?? ?for shortcuts", l.strip())]
    out = " ".join(keep)
    out = re.sub(r"https?://\S+|`+|[*_#>|]+", " ", out)
    return re.sub(r"\s+", " ", out).strip()[-2500:]


if __name__ == "__main__":
    print(extract(sys.stdin.read()))
