#!/usr/bin/env bash
# install-narrate.sh -- deploy lib/narrate.py to where `tts` runs it.
#
# bin/tts executes the narrator from $TTS_NARRATE (default
# ~/.local/share/claude-tts/narrate.py), NOT from the repo -- so an edit to
# lib/narrate.py has no effect until it is copied there. This script does that
# copy. It is idempotent and safe to re-run. Run as dev; invoked by my-system's
# claude-tts installer, or standalone after editing the narrator.
#
# The destination is read from the same $TTS_NARRATE variable bin/tts uses, so
# the two can never point at different files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
SRC="$REPO/lib/narrate.py"

DEST="${TTS_NARRATE:-$HOME/.local/share/claude-tts/narrate.py}"

[ -f "$SRC" ] || { echo "install-narrate: source not found at $SRC" >&2; exit 1; }

mkdir -p "$(dirname "$DEST")"
install -m 0644 "$SRC" "$DEST"
echo "install-narrate: deployed $SRC -> $DEST"

# self-test: the deployed narrator must at least parse and run cleanly. Feed it
# a one-line transcript and confirm it exits 0 (behaviour is version-specific,
# so we assert it runs, not what it says).
tmp="$(mktemp --suffix=.jsonl)"
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Install self test."}]}}' > "$tmp"
if out="$(python3 "$DEST" "$tmp")" && [ -n "$out" ]; then
    rm -f "$tmp"; echo "install-narrate: OK"
else
    rm -f "$tmp"; echo "install-narrate: self-test FAILED" >&2; exit 1
fi
