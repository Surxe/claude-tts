#!/usr/bin/env python3
"""kokoro_synth.py -- synthesize prose into a WAV with Kokoro (ONNX, CPU).

The higher-quality successor to the piper path in `tts`. Reads speakable prose
on stdin (already stripped by narrate.py) and writes a 24 kHz mono WAV.

Why this exists / how it improves flow
--------------------------------------
Piper synthesizes one sentence at a time and glues them with a fixed silence,
so a multi-sentence reply comes out as a string of independently-intoned
sentences -- the "words in a sentence" choppiness. Kokoro carries prosody
across a whole synthesis call, so the win here is to feed it as much text per
call as the model allows: we greedily PACK consecutive sentences into a chunk
(up to a phoneme-safe character budget) and synthesize the chunk as one flowing
utterance. Intonation then rises and falls across sentence boundaries the way a
person reads a paragraph. Only BETWEEN packed chunks do we insert a short,
tunable gap -- never between sentences inside a chunk.

Runs from the Kokoro venv (see setup/install-kokoro.sh). Zero network, zero
tokens: local ONNX inference only.

Usage:
    narrate.py ... | kokoro_synth.py --model M.onnx --voices V.bin --out OUT.wav
                     [--voice af_heart] [--speed 1.0] [--lang en-us] [--gap 0.12]

Exit non-zero on any failure so `tts` can fall back to piper.
"""
import argparse
import re
import sys
import wave

import numpy as np


# Kokoro's acoustic model has a hard cap around 510 phoneme tokens per call.
# Characters are a rough proxy for phonemes; keep a conservative budget so a
# packed chunk never overruns the model (which would truncate or error).
CHUNK_CHAR_BUDGET = 350

# Split points, in descending preference, for a single sentence that is itself
# longer than the budget: clause boundaries first, then any whitespace.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT = re.compile(r"(?<=[;:,])\s+")


def _split_sentences(text):
    """Text -> list of sentence-ish strings, whitespace-normalized."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _hard_wrap(piece, budget):
    """Break an over-long sentence into <=budget pieces without losing words.

    Tries clause boundaries (comma/semicolon/colon) first so the breaks land
    where a reader would naturally pause; falls back to word boundaries only if
    a single clause is still too long.
    """
    out = []
    for clause in _CLAUSE_SPLIT.split(piece):
        clause = clause.strip()
        if not clause:
            continue
        if len(clause) <= budget:
            out.append(clause)
            continue
        # still too long -> pack whole words up to the budget
        cur = ""
        for word in clause.split(" "):
            if cur and len(cur) + 1 + len(word) > budget:
                out.append(cur)
                cur = word
            else:
                cur = word if not cur else cur + " " + word
        if cur:
            out.append(cur)
    return out


def pack_chunks(text, budget=CHUNK_CHAR_BUDGET):
    """Greedily pack whole sentences into <=budget chunks.

    Keeping several sentences together lets Kokoro intone them as one connected
    passage -- the core of the "flowing sentence" behavior.
    """
    chunks = []
    cur = ""
    for sent in _split_sentences(text):
        pieces = [sent] if len(sent) <= budget else _hard_wrap(sent, budget)
        for piece in pieces:
            if not cur:
                cur = piece
            elif len(cur) + 1 + len(piece) <= budget:
                cur = cur + " " + piece
            else:
                chunks.append(cur)
                cur = piece
    if cur:
        chunks.append(cur)
    return chunks


def synth(text, model, voices, voice, speed, lang, gap):
    """Return (int16 PCM samples, sample_rate) for the whole text."""
    # Imported lazily so --help and arg errors don't pay the ONNX import cost.
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(model, voices)
    chunks = pack_chunks(text)
    if not chunks:
        return np.zeros(0, dtype="<i2"), 24000

    sample_rate = 24000
    audio_parts = []
    gap_samples = None
    for i, chunk in enumerate(chunks):
        samples, sample_rate = kokoro.create(
            chunk, voice=voice, speed=speed, lang=lang
        )
        arr = np.asarray(samples, dtype=np.float32)
        if gap_samples is None and gap > 0:
            gap_samples = np.zeros(int(sample_rate * gap), dtype=np.float32)
        if i > 0 and gap > 0:
            audio_parts.append(gap_samples)
        audio_parts.append(arr)

    audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, np.float32)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    return pcm, sample_rate


def write_wav(path, pcm, sample_rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser(description="Synthesize stdin prose to a WAV with Kokoro.")
    ap.add_argument("--model", required=True, help="path to kokoro-v1.0.onnx")
    ap.add_argument("--voices", required=True, help="path to voices-v1.0.bin")
    ap.add_argument("--out", required=True, help="output WAV path")
    ap.add_argument("--voice", default="af_heart", help="Kokoro voice name")
    ap.add_argument("--speed", type=float, default=1.0, help="speaking rate (1.0 = normal)")
    ap.add_argument("--lang", default="en-us", help="language code")
    ap.add_argument("--gap", type=float, default=0.12,
                    help="seconds of silence between packed chunks")
    args = ap.parse_args()

    text = sys.stdin.read()
    if not text.strip():
        sys.stderr.write("kokoro_synth: nothing to speak\n")
        return 1

    try:
        pcm, sr = synth(text, args.model, args.voices, args.voice,
                        args.speed, args.lang, args.gap)
    except Exception as exc:  # any failure -> let tts fall back to piper
        sys.stderr.write("kokoro_synth: {}\n".format(exc))
        return 1

    if pcm.size == 0:
        sys.stderr.write("kokoro_synth: no audio produced\n")
        return 1

    try:
        write_wav(args.out, pcm, sr)
    except Exception as exc:
        sys.stderr.write("kokoro_synth: writing WAV failed: {}\n".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
