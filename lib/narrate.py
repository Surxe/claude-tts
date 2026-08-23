#!/usr/bin/env python3
"""narrate.py -- turn a Claude Code transcript into speakable narration.

Reads a session .jsonl transcript (path as argv[1]), extracts the assistant's
latest response (everything after the last human prompt), replaces tool calls
with a short spoken marker so the listener knows a command ran, strips markdown
down to clean prose, and prints the result to stdout for piper to synthesize.

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


def extract_response(recs):
    """Concatenate assistant text after the last human prompt, with tool cues."""
    start = 0
    for i, r in enumerate(recs):
        if is_human_prompt(r):
            start = i + 1
    parts = []
    last_marker = None
    for r in recs[start:]:
        if r.get("type") != "assistant":
            continue
        content = (r.get("message") or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                parts.append(content.strip())
                last_marker = None
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
                    parts.append(txt)
                    last_marker = None
            elif t == "tool_use":
                m = marker_for(b.get("name"))
                if m != last_marker:          # collapse runs of identical calls
                    parts.append(m[0].upper() + m[1:] + ".")
                    last_marker = m
            # thinking / other block types are not part of the visible reply
    return "\n\n".join(parts)


def _table_row(m):
    row = m.group(0).strip().strip("|")
    cells = [c.strip() for c in row.split("|")]
    return ", ".join(c for c in cells if c) + "."


def clean(text):
    """Reduce markdown to speakable prose."""
    # fenced code blocks -> a single spoken cue
    text = re.sub(r"```.*?```", " . code block . ", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", " . code block . ", text, flags=re.DOTALL)
    # images then links -> their visible text
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # inline code
    text = re.sub(r"`([^`]*)`", r"\1", text)
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
    # bare URLs
    text = re.sub(r"https?://\S+", "a link", text)
    # drop emoji / dingbats / arrows that piper would mispronounce
    text = re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
        r"←-⇿⌀-⏿⬀-⯿️]",
        "",
        text,
    )
    # whitespace + stray-period cleanup
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:\s*\.\s*){2,}", ". ", text)
    return text.strip()


def main():
    if len(sys.argv) < 2:
        return 0
    try:
        recs = load_records(sys.argv[1])
    except (FileNotFoundError, PermissionError):
        return 0
    text = clean(extract_response(recs))
    if text.strip():
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
