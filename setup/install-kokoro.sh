#!/usr/bin/env bash
# install-kokoro.sh -- set up the Kokoro (ONNX, CPU) synth engine in dev's home.
#
# Kokoro-82M is the synth engine: it carries prosody across a whole utterance,
# so multi-sentence replies flow instead of sounding clipped. It runs on CPU via
# onnxruntime -- no GPU, no tokens, no
# network at synth time. This creates a self-contained venv and downloads the
# model, so nothing here needs root (dev has no sudo). espeak-ng comes bundled
# via the espeakng-loader wheel, so there is no system package to install.
#
# Deliberately NOT committed to git: the venv, the model (~311 MB) and the
# voices (~27 MB). This script reproduces them and is idempotent (skips what
# already exists). Run as dev; invoked by my-system's claude-tts installer, or
# standalone. `tts` refuses to synthesize until this has run.
set -euo pipefail

VENV="${KOKORO_VENV:-$HOME/.local/opt/kokoro-venv}"
MODEL_DIR="${KOKORO_DIR:-$HOME/.local/share/kokoro}"
MODEL="$MODEL_DIR/kokoro-v1.0.onnx"
VOICES="$MODEL_DIR/voices-v1.0.bin"
REL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

# Also deploy the synth script next to narrate.py, the same way install-narrate
# does, so `tts` runs a stable copy independent of the repo checkout.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
SYNTH_SRC="$REPO/lib/kokoro_synth.py"
SYNTH_DEST="${KOKORO_SYNTH:-$HOME/.local/share/claude-tts/kokoro_synth.py}"

mkdir -p "$MODEL_DIR" "$(dirname "$SYNTH_DEST")"

# --- venv + package ---
if [ ! -x "$VENV/bin/python" ]; then
    echo "install-kokoro: creating venv at $VENV ..."
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip >/dev/null
if ! "$VENV/bin/python" -c "import kokoro_onnx" 2>/dev/null; then
    echo "install-kokoro: installing kokoro-onnx (pulls onnxruntime, numpy) ..."
    "$VENV/bin/pip" install -q kokoro-onnx
    echo "install-kokoro: installed kokoro-onnx"
else
    echo "install-kokoro: kokoro-onnx already present"
fi

# --- model + voices ---
if [ ! -f "$MODEL" ]; then
    echo "install-kokoro: downloading model (~311 MB) ..."
    curl -fsSL -o "$MODEL" "$REL/kokoro-v1.0.onnx"
else
    echo "install-kokoro: model already present"
fi
if [ ! -f "$VOICES" ]; then
    echo "install-kokoro: downloading voices (~27 MB) ..."
    curl -fsSL -o "$VOICES" "$REL/voices-v1.0.bin"
else
    echo "install-kokoro: voices already present"
fi

# --- deploy the synth script ---
[ -f "$SYNTH_SRC" ] || { echo "install-kokoro: source not found at $SYNTH_SRC" >&2; exit 1; }
install -m 0644 "$SYNTH_SRC" "$SYNTH_DEST"
echo "install-kokoro: deployed $SYNTH_SRC -> $SYNTH_DEST"

# --- self-test: synthesize a throwaway sample ---
t="$(mktemp --suffix=.wav)"
if printf '%s\n' "Kokoro is installed and speaking in full sentences." \
        | "$VENV/bin/python" "$SYNTH_DEST" \
            --model "$MODEL" --voices "$VOICES" --out "$t" 2>/dev/null \
        && [ -s "$t" ]; then
    rm -f "$t"; echo "install-kokoro: OK"
else
    rm -f "$t"; echo "install-kokoro: self-test FAILED" >&2; exit 1
fi
