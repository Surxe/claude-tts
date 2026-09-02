# claude-tts

Speak Claude Code's terminal output aloud on this Debian workstation -- **zero
Claude tokens, no GPU, nothing running while idle.**

Claude Code runs as the unprivileged `dev` user, which is walled off from Ethan's
audio server by the multi-user security setup. So this is a two-sided bridge over
a `developers`-group spool, mirroring the `clip-discord` queue in `my-system`:

```
dev session                       shared spool (2775)             ethan session
 tts say / Stop hook            /srv/dev/tts/queue/               systemd --user
   read transcript                ├─ incoming/  <- dev drops .wav  path units (idle
   narrate.py -> prose            ├─ building/  (synth scratch)    until a file lands)
   piper -> WAV  ───────────────▶ ├─ failed/                          │
 tts stop ─────write STOP───────▶ └─ control/STOP                     ▼
                                                                  tts-speak: paplay
                                                                  each WAV, oldest first
```

- **dev** only ever synthesizes a WAV and drops it (piper's CPU cost stays here).
- **ethan** side is minimal and privileged: two path-activated user units, no
  resident daemon. One plays queued WAVs; one handles an instant stop (dev cannot
  signal an ethan-owned `paplay`, so the interrupt crosses via a `STOP` file).

### Speaking text from outside a Claude session

`tts speak FILE` narrates any text/markdown file, not just a transcript. To speak
something produced in Ethan's session -- the clipboard, say -- the text has to
reach dev for synthesis, because piper lives in `~dev` (mode `0700`) and Ethan
cannot run it. So the bridge is symmetric: a producer drops a `.txt` in
`text-incoming/`, and a **dev-side** path unit drains it:

```
producer (ethan)          shared spool               dev session
  wl-paste ─ write .txt ─▶ text-incoming/ ─┐
                                           ▼  claude-tts-synth.path (systemd --user)
                                     tts speak-drain: narrate --raw + piper
                                           └─▶ incoming/ ─▶ (ethan plays, as above)
```

Same "nothing running while idle" property: the dev-side watcher is a path unit,
idle until a file lands. dev has lingering enabled, so it stays armed across
logouts. A bad file is parked in `text-failed/`, never retried in a loop.

## Layout

| Path | Runs as | Role |
|------|---------|------|
| `bin/tts` | dev | CLI: `say`, `speak FILE`, `stop`, `on`, `off`, `volume`, `status`, `hook`, `speak-drain` |
| `lib/narrate.py` | dev | transcript (or `--raw` file) -> speakable prose (strips markdown, voices tool calls) |
| `bin/tts-speak` | ethan | drains the spool, plays each WAV via `paplay` |
| `systemd/claude-tts-play.{path,service}` | ethan | play queued speech on file drop |
| `systemd/claude-tts-stop.{path,service}` | ethan | kill playback + clear queue on `STOP` |
| `systemd/claude-tts-synth.{path,service}` | dev | synth queued text (`speak-drain`) on drop in `text-incoming/` |
| `setup/install-piper.sh` | dev | fetch piper binary + voice into `~dev` (idempotent; blobs not in git) |
| `setup/install-synth-units.sh` | dev | deploy + enable the dev-side synth path unit |

## Usage (type in the Claude Code prompt with a leading `!`)

```
!tts say         # speak my latest response now, once  (primary mode)
!tts stop        # cut off playback immediately
!tts on          # auto-speak every reply in THIS session (needs the Stop hook)
!tts off         # stop auto-speaking this session
!tts volume 80   # set playback volume to 80% (0-150); no arg prints current
!tts status      # show this session's state + queue depth + volume
```

Volume is a single global level, not per-session: it lives in the shared spool
(`control/volume`) so it crosses the dev->ethan boundary the same way `stop`
does. dev's `tts volume N` writes the percent; the ethan-side player reads it and
passes `paplay --volume` at play time (non-destructive -- the WAV is untouched,
and values above 100% soft-amplify). Absent = 100%.

Per-session and **default off**: nothing speaks unless you run `!tts say` or
`!tts on`. State is keyed to `$CLAUDE_CODE_SESSION_ID`, so sessions are independent.

## Always-on (optional)

`tts on/off` set a per-session flag (`~dev/.claude/tts/<session>.on`). A `Stop`
hook in dev's `settings.json` calls `tts hook`, which no-ops unless the current
session's flag exists -- so when off it costs one file check per reply and never
loads piper.

## Install / deploy

Deployed by `my-system` (`users/install.sh`, run as ethan): copies `tts` +
`narrate.py` to dev's `~/.local`, runs `setup/install-piper.sh`, review-gated
copies `tts-speak` + the units to Ethan's home, creates the spool, and enables
the path units in Ethan's user systemd.

## Voice

Default `en_US-lessac-medium`. Change it in `~/.config/claude-tts/config`
(see `config.example`).
