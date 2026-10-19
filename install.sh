#!/bin/sh
# One-shot install: link the herdr plugin, add key bindings, reload herdr config.
set -e
herdr plugin link /home/leszek/kody/experiments/tts/voice/herdr-plugin
CFG=/home/leszek/.config/herdr/config.toml
grep -q "leszek.czytacz" "$CFG" || cat >> "$CFG" <<'KEYS'

# czytacz (TTS)
[[keys.command]]
key = "prefix+v"
type = "plugin_action"
command = "leszek.czytacz.toggle"
description = "czytacz: mute/unmute this pane"

[[keys.command]]
key = "prefix+s"
type = "plugin_action"
command = "leszek.czytacz.stop"
description = "czytacz: stop speaking"
KEYS
herdr server reload-config
echo "czytacz installed: prefix+v toggle pane, prefix+s stop"
