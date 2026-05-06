"""
Live Transcribe — Step 3: extract Pradip Halder's stock analyses.

Functionally identical to backend/pipeline/voice_typing/arrange_transcript.py
but tuned for the speaker-diarized input format produced by the diarized
finalize pass. The diarized transcript looks like:

    [00:00:12] Speaker A: …
    [00:00:18] Speaker B: …

…where one of the speakers is Pradip Halder. The OpenAI prompt is told to
identify Pradip's speaker line and only keep stocks he personally analyses.

Output is the strict line-pair format Bulk Rationale parses:

    STOCK_NAME
    Analysis text…
    STOCK_NAME
    Analysis text…
"""

import re
import time
import openai
from backend.utils.database import get_db_cursor


def _get_openai_key():
    with get_db_cursor() as cursor:
        cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'openai'")
        row = cursor.fetchone()
        if row and row['key_value']:
            return row['key_value'].strip()
    return None


CHARS_PER_TOKEN = 3
MAX_CHUNK_CHARS = 45_000
INTER_CHUNK_SLEEP_SECS = 65


SYSTEM_PROMPT = """You are an editor who FILTERS and REFORMATS a speaker-attributed
transcript so the Bulk Rationale tool can parse it.

The transcript is from a financial show hosted by **Pradip Halder**. Each
line is prefixed with a timestamp and a speaker label, e.g.

    [00:00:12] Speaker A: <text>
    [00:00:18] Speaker B: <text>

One of those speakers is Pradip Halder. Your job is to:

1. Identify which speaker label corresponds to Pradip Halder (the host —
   typically the one introducing the show, naming guests, asking
   questions, AND the one giving structured stock-by-stock buy/sell/hold
   analysis with prices, stop-losses, and targets).
2. Keep ONLY the stocks on which Pradip Halder personally gave analysis.
3. Discard guest opinions, callers, anchor chatter, ads, greetings, and
   anything that isn't Pradip's own stock analysis.

OUTPUT FORMAT (STRICT):
- For every stock kept, FIRST LINE = the stock name (or symbol) alone.
- NEXT LINE(S) = Pradip Halder's analysis for that stock, verbatim.
- Then the next stock name on its own line, then its analysis. Repeat.
- Do NOT add timestamps, speaker labels, headings, numbering, bullet
  points, markdown, or commentary in the output.
- Do NOT translate. Keep the analysis in the original language exactly.
- Do NOT rewrite, paraphrase, summarize, "polish", or "improve". Copy
  each word verbatim, in the original spoken order.
- Strip the leading "[HH:MM:SS] Speaker X:" prefix from the analysis
  body — the Bulk Rationale parser doesn't want it.
- The ONLY transformations allowed are:
    a) Removing speech that isn't Pradip Halder analysing a stock.
    b) Cutting at stock boundaries.
    c) Inserting a newline between the stock name line and its analysis.
    d) Stripping the "[HH:MM:SS] Speaker X:" prefix.
- If two stocks share the same analysis from Pradip Halder, list them
  comma-separated on one stock-name line followed by that single
  analysis (e.g. `RELIANCE, TCS\\nbreakout above ...`).
- A stock name line should be the bare ticker / company name only — no
  "buy", "call", "stock", "the", brackets, or labels.
- If Pradip Halder gave NO stock analysis in this segment, output an
  empty response.

RESPOND WITH ONLY THE REFORMATTED TRANSCRIPT, NOTHING ELSE."""


def _split_into_chunks(text: str, max_chars: int) -> list:
    """Greedy chunker that respects line, paragraph and sentence boundaries.
    The diarized transcript has one utterance per line, so line-splitting
    is the natural break."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    lines = [ln for ln in text.split('\n') if ln.strip()]
    chunks: list = []
    buf: list = []
    buf_len = 0

    def _flush():
        nonlocal buf, buf_len
        if buf:
            chunks.append('\n'.join(buf).strip())
            buf, buf_len = [], 0

    for ln in lines:
        if len(ln) > max_chars:
            _flush()
            # A single utterance shouldn't exceed max_chars in practice,
            # but defend against pathological input.
            sentences = re.split(r'(?<=[.।!?])\s+', ln)
            sbuf, slen = [], 0
            for s in sentences:
                if len(s) > max_chars:
                    if sbuf:
                        chunks.append(' '.join(sbuf).strip()); sbuf, slen = [], 0
                    for i in range(0, len(s), max_chars):
                        chunks.append(s[i:i + max_chars].strip())
                    continue
                if slen + len(s) + 1 > max_chars and sbuf:
                    chunks.append(' '.join(sbuf).strip()); sbuf = [s]; slen = len(s)
                else:
                    sbuf.append(s); slen += len(s) + 1
            if sbuf:
                chunks.append(' '.join(sbuf).strip())
            continue

        if buf_len + len(ln) + 1 > max_chars and buf:
            _flush()
        buf.append(ln)
        buf_len += len(ln) + 1

    _flush()
    return [c for c in chunks if c]


def _arrange_one_chunk(client, chunk_text: str) -> tuple:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chunk_text},
        ],
        temperature=0.0,
        max_tokens=8192,
    )
    text = (resp.choices[0].message.content or '').strip()
    total_tokens = getattr(resp.usage, 'total_tokens', 0) if resp.usage else 0
    return text, total_tokens


def run(transcript_text: str) -> dict:
    """Filter & rearrange a diarized transcript into the Bulk-Rationale
    line-pair format. Returns dict with 'success', 'arranged_text', 'error'."""
    print("\n" + "=" * 60)
    print("LIVE TRANSCRIBE: EXTRACT PRADIP HALDER ANALYSIS")
    print("=" * 60)

    if not transcript_text or not transcript_text.strip():
        return {'success': False, 'arranged_text': '', 'error': 'Transcript is empty'}

    key = _get_openai_key()
    if not key:
        return {
            'success': False, 'arranged_text': '',
            'error': 'OpenAI API key not found. Add it under API Keys.',
        }

    chunks = _split_into_chunks(transcript_text, MAX_CHUNK_CHARS)
    print(f"📝 Input transcript: {len(transcript_text)} chars (~{len(transcript_text)//CHARS_PER_TOKEN} tokens)")
    print(f"📦 Split into {len(chunks)} chunk(s) of up to {MAX_CHUNK_CHARS} chars each")

    try:
        client = openai.OpenAI(api_key=key)
        arranged_parts: list = []

        for i, chunk in enumerate(chunks, start=1):
            print(f"  ↪ Chunk {i}/{len(chunks)}: {len(chunk)} chars")
            arranged, used_tokens = _arrange_one_chunk(client, chunk)
            print(f"    ⓘ tokens used: {used_tokens}")
            if arranged:
                arranged_parts.append(arranged)
            else:
                print("    · No Pradip Halder analysis in this chunk — skipped.")

            if i < len(chunks):
                print(f"    ⏳ Waiting {INTER_CHUNK_SLEEP_SECS}s (TPM cooldown)...")
                time.sleep(INTER_CHUNK_SLEEP_SECS)

        if not arranged_parts:
            return {
                'success': False, 'arranged_text': '',
                'error': 'OpenAI returned no Pradip Halder analysis for any chunk.',
            }

        arranged = '\n'.join(arranged_parts).strip()
        print(f"✅ Final arranged length: {len(arranged)} chars")
        return {'success': True, 'arranged_text': arranged, 'error': None}

    except openai.RateLimitError as e:
        msg = (
            f"OpenAI rate limit hit even after chunking ({e}). "
            "Try again in a minute, or shorten the transcript before extracting."
        )
        return {'success': False, 'arranged_text': '', 'error': msg}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'arranged_text': '', 'error': str(e)}
