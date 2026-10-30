# Czytacz: read AI coding agents' replies aloud

Czytacz ("reader" in Polish) reads the replies of AI coding agents (Claude Code, Antigravity, Codex) aloud, sentence by sentence, in Polish, using a local text-to-speech model on an Intel iGPU. You can look away from the screen while agents work and still hear what they finished.

## How it works

- **`daemon.py`** keeps the OmniVoice model loaded on the Intel iGPU (XPU) and serves a small HTTP API. It generates sentence N+1 while sentence N is playing, so speech starts fast and has no gaps.
  - `POST /speak` queues text for local playback, `POST /wav` returns one WAV file (for remote playback), `POST /stop` silences it, `GET /health`.
- **`voice.py`** (installed as `czytacz`) is a stdlib-only client: a Claude Code Stop hook, a herdr event hook for other agents, and commands to mute a pane, change the voice or the tempo.
- **`textclean.py`** turns Markdown into speakable text: it drops code blocks, URLs, file paths and hashes, and splits the rest into sentences.
- **`herdr-plugin/`** integrates with the [herdr](https://github.com/herdrdev/herdr) terminal workspace: reading starts when an agent finishes, and every pane can be muted.

## Requirements

- Linux with an Intel GPU supported by PyTorch XPU
- [OmniVoice](https://github.com/k2-fsa/OmniVoice) in a Python virtual environment
- herdr (optional, for the plugin)

The plugin manifest and `install.sh` contain absolute paths from my machine; adjust them to your setup before installing.

## Usage

```bash
czytacz say "Testy przeszły."
czytacz off all        # mute everywhere
czytacz tempo 1.7
```

## License

MIT
