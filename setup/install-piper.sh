#!/usr/bin/env bash
# install-piper.sh -- fetch the Piper TTS binary + a voice into dev's home.
#
# The binary (~26 MB) and voice (~63 MB) are deliberately NOT committed to git;
# this script reproduces the install and is idempotent (skips what already exists).
# Run as dev. Invoked by my-system's claude-tts installer, or standalone.
set -euo pipefail

PIPER_VER="2023.11.14-2"
VOICE_NAME="en_US-lessac-medium"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

OPT="$HOME/.local/opt"
BIN="$HOME/.local/bin"
VOICES="$HOME/.local/share/piper/voices"
mkdir -p "$OPT" "$BIN" "$VOICES"

if [ ! -x "$OPT/piper/piper" ]; then
    echo "install-piper: downloading piper $PIPER_VER ..."
    tmp="$(mktemp -d)"
    curl -fsSL -o "$tmp/piper.tgz" \
        "https://github.com/rhasspy/piper/releases/download/$PIPER_VER/piper_linux_x86_64.tar.gz"
    tar -xzf "$tmp/piper.tgz" -C "$OPT"       # extracts an $OPT/piper/ dir
    rm -rf "$tmp"
    echo "install-piper: installed piper to $OPT/piper"
else
    echo "install-piper: piper already present ($OPT/piper/piper)"
fi
ln -sf "$OPT/piper/piper" "$BIN/piper"

if [ ! -f "$VOICES/$VOICE_NAME.onnx" ]; then
    echo "install-piper: downloading voice $VOICE_NAME ..."
    curl -fsSL -o "$VOICES/$VOICE_NAME.onnx"      "$VOICE_BASE/$VOICE_NAME.onnx"
    curl -fsSL -o "$VOICES/$VOICE_NAME.onnx.json" "$VOICE_BASE/$VOICE_NAME.onnx.json"
    echo "install-piper: installed voice to $VOICES"
else
    echo "install-piper: voice already present ($VOICE_NAME)"
fi

# self-test: synthesize a throwaway sample
t="$(mktemp --suffix=.wav)"
if echo "Piper is installed." | "$OPT/piper/piper" \
        --model "$VOICES/$VOICE_NAME.onnx" --output_file "$t" 2>/dev/null; then
    rm -f "$t"; echo "install-piper: OK"
else
    rm -f "$t"; echo "install-piper: self-test FAILED" >&2; exit 1
fi
