#!/usr/bin/env bash
# install-synth-units.sh -- deploy + enable the dev-side text->speech watcher.
#
# The clipboard/text bridge needs a watcher on the DEV side (piper lives in
# ~dev, which is 0700, so ethan cannot synthesize -- the text has to cross the
# shared spool to dev). This installs the two systemd USER units that do it:
#
#   claude-tts-synth.path     watches /srv/dev/tts/queue/text-incoming
#   claude-tts-synth.service  runs `tts speak-drain` on each drop
#
# Runs as dev. Idempotent. Standalone here; my-system's claude-tts installer
# calls the same steps so a full deploy wires it up too. dev has lingering
# enabled, so the .path stays armed across logouts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
UNIT_DIR="$HOME/.config/systemd/user"
SPOOL="${TTS_SPOOL:-/srv/dev/tts/queue}"

# systemctl --user needs a runtime dir + bus; fill them in for a non-login shell
# (e.g. a Claude Code session), relying on dev's enabled lingering.
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

for u in claude-tts-synth.path claude-tts-synth.service; do
    [ -f "$REPO/systemd/$u" ] || { echo "install-synth-units: missing $REPO/systemd/$u" >&2; exit 1; }
    install -D -m 0644 "$REPO/systemd/$u" "$UNIT_DIR/$u"
    echo "install-synth-units: deployed $UNIT_DIR/$u"
done

# The spool subtree is dev-owned; make sure the text dirs exist (the play/queue
# dirs are created by the main installer, but this keeps standalone runs working).
mkdir -p "$SPOOL"/text-incoming "$SPOOL"/text-failed
chgrp developers "$SPOOL"/text-incoming "$SPOOL"/text-failed 2>/dev/null || true
chmod 2775 "$SPOOL"/text-incoming "$SPOOL"/text-failed 2>/dev/null || true

if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable --now claude-tts-synth.path
    echo "install-synth-units: enabled claude-tts-synth.path"
    systemctl --user --no-pager --lines=0 status claude-tts-synth.path >/dev/null 2>&1 \
        && echo "install-synth-units: OK"
else
    echo "install-synth-units: could not reach dev's user systemd (XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR)" >&2
    echo "install-synth-units: units are deployed; enable later with:" >&2
    echo "  systemctl --user enable --now claude-tts-synth.path" >&2
    exit 1
fi
