#!/usr/bin/env python3
"""Czytacz client for the voice daemon (stdlib only). Reading is ON by default in every pane; you mute.

  czytacz off [all] | on [all] [m1|f1|m2|f2] | toggle [all] | status
  czytacz full     read the whole last reply of this pane (no length cap)
  czytacz say "text" | speak (text on stdin) | stop | tempo 1.7
  czytacz hook     Claude Code Stop hook: reads the last assistant message
  czytacz event    herdr plugin event hook (pane.agent_status_changed): reads non-Claude agents when they finish
Pane key: HERDR_PANE_ID (or the pane in the herdr plugin context), else 'default'.
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

URL = f"http://127.0.0.1:{os.environ.get('VOICE_PORT', 8765)}"
ROOT = Path.home() / ".cache/voice"
MUTE, VOICE, STATE, LAST = ROOT / "mute", ROOT / "voice", ROOT / "state", ROOT / "last"
VOICES = ["m1", "f1", "m2", "f2"]
pane = os.environ.get("HERDR_PANE_ID", "default")


def key():
    return pane.replace(":", "_")


def _post(path, data=None):
    req = urllib.request.Request(URL + path, json.dumps(data or {}).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def start_daemon():
    """Launch the daemon detached; it holds a lock, so concurrent clients never load the model twice."""
    py = Path(__file__).resolve().parent.parent / "OmniVoice/.venv/bin/python"
    log = open(ROOT / "daemon.log", "a")
    subprocess.Popen([str(py), str(Path(__file__).resolve().parent / "daemon.py")], stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True)


def post(path, data=None):
    """Send to the daemon, starting it when down. /stop is moot without a daemon. When starting, the
    send is finished by a detached child (model load takes a while; hooks must return fast)."""
    try:
        return _post(path, data)
    except OSError:
        if path == "/stop":
            return
    start_daemon()
    if os.fork():
        return  # parent: caller (hook/CLI) returns immediately
    os.setsid()
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):  # release the hook's pipes so the caller does not wait for us
        os.dup2(null, fd)
    for _ in range(90):  # child: wait up to ~3 min for the model to load, then deliver
        time.sleep(2)
        try:
            _post(path, data)
            break
        except OSError:
            pass
    os._exit(0)


def muted():
    return (MUTE / key()).exists() or (MUTE / "ALL").exists()


def voice_for():
    f = VOICE / key()
    v = f.read_text().strip() if f.exists() else ""
    return v if v in VOICES else "m1"


def speak(text, full=False):
    tempo = ROOT / "tempo"
    data = {"text": text, "voice": voice_for(), "full": full}
    if tempo.exists():
        data["tempo"] = float(tempo.read_text())
    post("/speak", data)


def herdr(*a):
    out = subprocess.run(["herdr", *a], capture_output=True, text=True, timeout=5).stdout
    return json.loads(out)["result"]


def tab_label(tab_id):
    try:
        return herdr("tab", "get", tab_id)["tab"].get("label") or ""
    except Exception:
        return ""


def find(obj, name):
    """First value for `name` anywhere in nested JSON (herdr payloads nest their data)."""
    if isinstance(obj, dict):
        if isinstance(obj.get(name), str):
            return obj[name]
        for v in obj.values():
            r = find(v, name)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find(v, name)
            if r:
                return r
    return None


def last_assistant_text(payload):
    if payload.get("last_assistant_message"):
        return payload["last_assistant_message"]
    last = ""
    with open(payload["transcript_path"]) as f:
        for line in f:
            e = json.loads(line)
            m = e.get("message") or {}
            if e.get("type") == "assistant" and isinstance(m.get("content"), list):
                t = "\n".join(c.get("text", "") for c in m["content"] if c.get("type") == "text")
                if t.strip():
                    last = t
    return last


def toast(msg):
    subprocess.run(["herdr", "notification", "show", msg, "--position", "bottom-right"], capture_output=True, timeout=5)


def main():
    global pane
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    for d in (MUTE, VOICE, STATE, LAST):
        d.mkdir(parents=True, exist_ok=True)
    ctx = os.environ.get("HERDR_PLUGIN_CONTEXT_JSON")  # set when run as a herdr plugin action
    if ctx:
        pane = find(json.loads(ctx), "pane_id") or pane
    target = "ALL" if "all" in args[1:] else key()
    pick = next((a for a in args[1:] if a in VOICES), None)

    if cmd == "toggle":
        cmd = "on" if (MUTE / target).exists() else "off"
    if cmd == "off":
        (MUTE / target).touch()
        post("/stop")
        msg = f"czytacz OFF ({target})"
    elif cmd == "on":
        (MUTE / target).unlink(missing_ok=True)
        if pick:
            (VOICE / key()).write_text(pick)
        msg = f"czytacz ON ({target}, voice {voice_for()})"
    elif cmd == "status":
        msg = " ".join(["OFF" if muted() else "ON", key(), voice_for(), "(ALL muted)" if (MUTE / "ALL").exists() else ""])
    elif cmd == "tempo":
        (ROOT / "tempo").write_text(args[1])
        msg = f"czytacz tempo {args[1]}"
    elif cmd == "say":
        speak(" ".join(args[1:]))
        return
    elif cmd == "speak":
        if not muted():
            speak(sys.stdin.read())
        return
    elif cmd == "full":
        f = LAST / key()
        if f.exists():
            speak(f.read_text(), full=True)
        else:
            print("no stored reply for this pane yet")
        return
    elif cmd == "stop":
        post("/stop")
        return
    elif cmd == "hook":
        try:
            text = last_assistant_text(json.load(sys.stdin))
            if text:
                (LAST / key()).write_text(text)  # kept for `czytacz full`, even when muted
            if text and not muted():
                label = tab_label(os.environ.get("HERDR_TAB_ID", ""))
                speak((f"Zakładka {label}. " if label else "") + text)
        except Exception:
            pass  # a hook must never break the agent
        return
    elif cmd == "event":
        try:
            ev = json.loads(os.environ.get("HERDR_PLUGIN_EVENT_JSON") or sys.stdin.read())
            pane, status, agent = find(ev, "pane_id"), find(ev, "agent_status"), find(ev, "agent") or ""
            prev = (STATE / key()).read_text() if (STATE / key()).exists() else ""
            (STATE / key()).write_text(status or "")
            # speak once when work finishes; Claude Code is read by its own Stop hook (clean text)
            if prev == "working" and status in ("done", "idle") and agent != "claude" and not muted():
                from clean_transcript import extract
                raw = subprocess.run(["herdr", "agent", "read", pane, "--source", "recent-unwrapped", "--lines", "80"],
                                     capture_output=True, text=True, timeout=10).stdout
                text = extract(raw)
                if text:
                    label = tab_label(herdr("agent", "get", pane)["agent"]["tab_id"])
                    speak((f"Zakładka {label}. " if label else "") + text)
        except Exception:
            pass
        return
    else:
        msg = __doc__
    print(msg)
    if ctx:  # invoked from a herdr key binding: show feedback
        toast(msg)


main()
