"""Resident OmniVoice TTS daemon: keeps the model on the Intel iGPU (XPU), reads text sentence by sentence.

POST /speak {"text","voice"}   queue text, play locally (generate N+1 while N plays)
POST /wav   {"text","voice"}   return one WAV (for remote playback, e.g. a web page)
POST /stop                     drop queue, silence
GET  /health
"""
import json, os, queue, re, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fcntl
Path.home().joinpath(".cache/voice").mkdir(parents=True, exist_ok=True)
_lock = open(Path.home() / ".cache/voice/daemon.lock", "w")  # held for the process lifetime
try:
    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(0)  # another instance is running or still loading the model

import numpy as np
import soundfile as sf
import torch

PORT = int(os.environ.get("VOICE_PORT", 8765))
NUM_STEP = int(os.environ.get("VOICE_STEPS", 8))
SPEED = float(os.environ.get("VOICE_SPEED", 1.4))
TEMPO = float(os.environ.get("VOICE_TEMPO", 1.0))  # ffmpeg atempo on top of the model speed: exact, keeps pitch
MAX_CHARS = int(os.environ.get("VOICE_MAX_CHARS", 1000))
SR = 24000
CACHE = Path.home() / ".cache/voice"
VOICES = {  # name -> OmniVoice voice-design attributes
    "m1": "male, low pitch",
    "f1": "female, moderate pitch",
    "m2": "male, moderate pitch",
    "f2": "female, high pitch",
}
REF_TEXT = "Cześć, czytam ci odpowiedzi."

from omnivoice import OmniVoice
from textclean import sentences

model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="xpu", dtype=torch.float16)
prompts, gen_lock = {}, threading.Lock()


def voice_prompt(name):
    """Fixed voice per name: design it once, then clone it so every sentence sounds alike."""
    name = name if name in VOICES else "m1"
    if name not in prompts:
        f = CACHE / f"{name}.pt"
        from omnivoice import VoiceClonePrompt
        if f.exists():
            prompts[name] = VoiceClonePrompt.load(str(f))
        else:
            ref = model.generate(text=REF_TEXT, instruct=VOICES[name], num_step=32)[0]
            p = model.create_voice_clone_prompt(
                ref_audio=(torch.from_numpy(ref).float().unsqueeze(0), SR), ref_text=REF_TEXT)
            CACHE.mkdir(parents=True, exist_ok=True)
            p.save(str(f))
            prompts[name] = p
    return prompts[name]


def synth(sentence, voice, speed=None):
    with gen_lock:
        a = model.generate(text=sentence, voice_clone_prompt=voice_prompt(voice),
                           num_step=NUM_STEP, speed=speed or SPEED)[0]
    return np.concatenate([a, np.zeros(int(SR * 0.15), dtype=a.dtype)])  # tail pad: model clips endings


USAGE = CACHE / "usage.log"


def log_usage(path, text, full):
    """Append 'Y-m-d H:i:s path received spoken' (spoken = chars after cleaning and cap): TTS billing is per char."""
    spoken = sum(len(s) for s in sentences(text, None if full else MAX_CHARS))
    with open(USAGE, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {path} {len(text)} {spoken}\n")


jobs, plays = queue.Queue(), queue.Queue()
epoch, player = [0], [None]


def generator():
    while True:
        text, voice, ep, tempo, full = jobs.get()
        for s in sentences(text, None if full else MAX_CHARS):
            if ep != epoch[0]:
                break
            try:
                f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                sf.write(f.name, synth(s, voice), SR)
                out = f.name
                if tempo != 1:  # ffmpeg post-speedup: off by default (VOICE_TEMPO=1), kept for later
                    out = f.name + ".t.wav"
                    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", f.name, "-filter:a", f"atempo={tempo}", out], check=True)
                    os.unlink(f.name)
                plays.put((out, ep))
            except Exception as e:  # keep the daemon alive
                print("synth error:", e, file=sys.stderr, flush=True)


def playback():
    while True:
        path, ep = plays.get()
        if ep == epoch[0]:
            player[0] = subprocess.Popen(["paplay", path])
            player[0].wait()
        os.unlink(path)


def stop():
    epoch[0] += 1
    for q in (jobs, plays):
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break
    if player[0] and player[0].poll() is None:
        player[0].kill()


class H(BaseHTTPRequestHandler):
    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def _send(self, code, data=b"ok", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, b"ok")

    def do_POST(self):
        b = self._body()
        if self.path in ("/speak", "/wav"):
            log_usage(self.path, b.get("text", ""), bool(b.get("full")))
        if self.path == "/speak":
            jobs.put((b.get("text", ""), b.get("voice", "m1"), epoch[0], float(b.get("tempo") or TEMPO), bool(b.get("full"))))
            self._send(200)
        elif self.path == "/stop":
            stop()
            self._send(200)
        elif self.path == "/wav":
            parts = [synth(s, b.get("voice", "m1"), b.get("speed")) for s in sentences(b.get("text", ""), MAX_CHARS)]
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                sf.write(f.name, np.concatenate(parts) if parts else np.zeros(1), SR)
                self._send(200, Path(f.name).read_bytes(), "audio/wav")
        else:
            self._send(404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    for t in (generator, playback):
        threading.Thread(target=t, daemon=True).start()
    voice_prompt("m1")  # warm up: JIT kernels + default voice
    print(f"voice daemon ready on :{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
