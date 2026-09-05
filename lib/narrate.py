#!/usr/bin/env python3
"""narrate.py -- turn text into speakable narration.

Two modes, both printing clean prose to stdout for piper to synthesize:

  narrate.py <transcript.jsonl>   (default) extract the assistant's latest
      response from a Claude Code session transcript -- everything after the
      last human prompt -- voicing tool calls as short cues, then strip markdown.

  narrate.py --raw <file>         treat <file> as generic text/markdown and just
      strip it down to speakable prose (no transcript parsing). Backs `tts speak`.

Zero network, zero tokens -- pure local text processing.
"""
import json
import re
import sys

# A tool_use block is spoken as a short cue so the listener knows something
# happened without hearing the arguments. Unknown tools fall back to a generic
# phrase (see marker_for); MCP tools collapse to "a connected tool".
TOOL_MARKERS = {
    "Bash": "ran a shell command",
    "Read": "read a file",
    "Edit": "edited a file",
    "Write": "wrote a file",
    "NotebookEdit": "edited a notebook",
    "Glob": "searched for files",
    "Grep": "searched the code",
    "LS": "listed a directory",
    "WebFetch": "fetched a web page",
    "WebSearch": "searched the web",
    "Task": "ran a subagent",
    "Agent": "launched an agent",
    "Skill": "invoked a skill",
    "TodoWrite": "updated the task list",
    "AskUserQuestion": "asked a question",
    "Artifact": "published an artifact",
    "ExitPlanMode": "presented a plan",
    "ToolSearch": "looked up a tool",
}


def marker_for(name):
    if not name:
        return "used a tool"
    if name in TOOL_MARKERS:
        return TOOL_MARKERS[name]
    if name.startswith("mcp__"):
        return "used a connected tool"
    return "used the {} tool".format(name)


def load_records(path):
    recs = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                continue
    return recs


def is_human_prompt(rec):
    """True for a genuine typed user turn, False for tool-result user records."""
    if rec.get("type") != "user":
        return False
    msg = rec.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip() != ""
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                return True
    return False


def _flush_markers(markers):
    """A run of tool cues -> one flowing sentence, not a burst of clipped ones.

    ['read a file'] -> 'I read a file.'
    ['read a file', 'edited a file', 'ran a shell command']
        -> 'I read a file, edited a file, then ran a shell command.'
    Speaking a batch of actions as a single sentence reads far more naturally
    than the machine-gun 'Read a file. Edited a file. Wrote a file.'
    """
    if not markers:
        return None
    if len(markers) == 1:
        body = markers[0]
    elif len(markers) == 2:
        body = "{}, then {}".format(markers[0], markers[1])
    else:
        body = "{}, then {}".format(", ".join(markers[:-1]), markers[-1])
    return "I " + body + "."


def extract_response(recs):
    """Concatenate assistant text after the last human prompt, with tool cues."""
    start = 0
    for i, r in enumerate(recs):
        if is_human_prompt(r):
            start = i + 1
    parts = []
    pending = []          # a run of tool cues awaiting the next text block / end

    def flush():
        sentence = _flush_markers(pending)
        if sentence:
            parts.append(sentence)
        pending.clear()

    for r in recs[start:]:
        if r.get("type") != "assistant":
            continue
        content = (r.get("message") or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                flush()
                parts.append(content.strip())
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                txt = (b.get("text") or "").strip()
                if txt:
                    flush()
                    parts.append(txt)
            elif t == "tool_use":
                m = marker_for(b.get("name"))
                if not pending or pending[-1] != m:   # collapse identical runs
                    pending.append(m)
            # thinking / other block types are not part of the visible reply
    flush()
    return "\n\n".join(parts)


def _table_row(m):
    row = m.group(0).strip().strip("|")
    cells = [c.strip() for c in row.split("|")]
    return ", ".join(c for c in cells if c) + "."


_VOWEL = re.compile(r"[aeiouyAEIOUY]")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# a hex blob that mixes letters and digits (commit SHA, short hash) reads as noise
_HASH = re.compile(r"(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,}")
# a bare token that piper can pronounce: starts with a letter, has a vowel,
# short enough to not be a blob (dots/dashes/underscores allowed for filenames)
_READABLE = re.compile(r"[A-Za-z][\w.\-]{0,31}")


def _humanize(tok):
    """narrate.py -> 'narrate py', foo_bar-baz -> 'foo bar baz'."""
    return re.sub(r"[._\-/]+", " ", tok).strip() or tok


def _is_readable(tok):
    return bool(_READABLE.fullmatch(tok)) and bool(_VOWEL.search(tok))


def speak_code(content):
    """Turn the innards of an inline-code span into a spoken cue.

    Short, pronounceable tokens (a filename, a config key, `on`/`off`) are read
    as-is; anything a listener could not follow by ear -- commands, paths,
    flags, hashes -- collapses to a short category word instead.
    """
    s = content.strip()
    if not s:
        return ""
    if re.search(r"\s", s):                       # more than one token -> a command
        head = s.split()[0].split("/")[-1]        # basename of the first token
        head = head.split(".")[0]                 # drop any extension (.sh/.py)
        verb = _humanize(head)
        if re.fullmatch(r"[A-Za-z][\w \-]{0,23}", verb):
            return "a {} command".format(verb)
        return "a command"
    if s.startswith("-") and not s[1:2].isdigit():
        return "a flag"
    if s.startswith("$"):
        return "a variable"
    if s.startswith(("http://", "https://", "www.")):
        return "a link"
    if _EMAIL.fullmatch(s):
        return "an email address"
    if _UUID.fullmatch(s):
        return "an identifier"
    if "/" in s:                                  # a path -> basename if speakable
        base = s.rstrip("/").split("/")[-1]
        if len(base) >= 3 and _is_readable(base):
            return _humanize(base)
        return "a file path"
    if _HASH.fullmatch(s.lower()):
        return "a hash"
    if re.fullmatch(r"[A-Za-z0-9+/=_]{20,}", s):  # base64-ish blob
        return "an identifier"
    if _is_readable(s):
        return _humanize(s)
    return "some code"


def clean(text):
    """Reduce markdown to speakable prose."""
    # fenced code blocks -> a single spoken cue, as an inline aside (commas, not
    # standalone periods) so it flows inside the surrounding sentence
    text = re.sub(r"```.*?```", ", a code block, ", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", ", a code block, ", text, flags=re.DOTALL)
    # images then links -> their visible text
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # inline code -> a spoken cue (commands/paths/hashes become category words)
    text = re.sub(r"`([^`]*)`", lambda m: " " + speak_code(m.group(1)) + " ", text)
    # headings and blockquote markers
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    # table separators, then table rows -> comma-joined cells
    text = re.sub(r"(?m)^\s*\|?\s*:?-{2,}[-\s|:]*$", "", text)
    text = re.sub(r"(?m)^\s*\|.*\|\s*$", _table_row, text)
    # horizontal rules
    text = re.sub(r"(?m)^\s*([-*_])\1{2,}\s*$", "", text)
    # list bullets / numbers
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    # emphasis markers (after lists, so leading * bullets are already gone)
    text = re.sub(r"(\*\*|\*|__|~~)", "", text)
    # noise that survives outside code spans: URLs, emails, ids, paths, vars.
    # URLs first so their slashes aren't mistaken for a file path.
    text = re.sub(r"https?://\S+", "a link", text)
    text = _EMAIL.sub("an email address", text)
    text = _UUID.sub("an identifier", text)
    text = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]{2,}", "a variable", text)
    # a source location like narrate.py:127 -> "narrate py line 127"
    text = re.sub(
        r"\b([\w\-]+\.[A-Za-z]{1,5}):(\d+)\b",
        lambda m: _humanize(m.group(1)) + " line " + m.group(2),
        text,
    )
    # a bare filesystem path: two or more slash-separated segments
    text = re.sub(r"(?<![\w/])~?(?:/[\w.\-]+){2,}/?", " a file path ", text)
    # a bare hash / commit sha sitting in prose (word-bounded, letters+digits)
    text = re.sub(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,}\b",
                  "a hash", text)
    # drop emoji / dingbats / arrows that piper would mispronounce
    text = re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
        r"←-⇿⌀-⏿⬀-⯿️]",
        "",
        text,
    )
    # whitespace + stray-punctuation cleanup
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:\s*\.\s*){2,}", ". ", text)   # runs of periods -> one
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)      # no space before punctuation
    text = re.sub(r"(?:\s*,\s*){2,}", ", ", text)     # doubled commas -> one
    text = re.sub(r"([.!?;:])\s*,", r"\1", text)      # comma right after a stop
    text = re.sub(r"(?m)^\s*,\s*", "", text)          # a line that starts on a comma
    text = re.sub(r",\s*(?=\n|$)", "", text)          # a dangling trailing comma
    return text.strip()


def narrate_transcript(path):
    """A session transcript -> the latest assistant response as spoken prose."""
    try:
        recs = load_records(path)
    except (FileNotFoundError, PermissionError):
        return ""
    return clean(extract_response(recs))


def narrate_raw(path):
    """A generic text/markdown file -> spoken prose (no transcript parsing)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return ""
    return clean(raw)


def main():
    args = sys.argv[1:]
    raw = False
    if args and args[0] == "--raw":
        raw, args = True, args[1:]
    if not args:
        return 0
    text = narrate_raw(args[0]) if raw else narrate_transcript(args[0])
    if text.strip():
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
