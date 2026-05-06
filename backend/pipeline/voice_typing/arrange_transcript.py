"""
Voice Typing Pipeline - Arrange Transcript
Calls OpenAI to filter the transcript down to ONLY the stocks on which
Pradip Halder personally gave analysis, and reformat that subset into the
strict line-pair shape the Bulk Rationale tool expects:

    STOCK_NAME
    Analysis text for that stock (one or more lines, kept exactly as-is).
    STOCK_NAME
    Analysis text...

The analysis text itself MUST be preserved verbatim. We only:
  - identify each stock callout that Pradip Halder discussed,
  - drop everything else (other speakers, greetings, unrelated chatter),
  - put the stock symbol on its own line,
  - put the analysis text on the next line(s).

CHUNKING
========
The model has a per-minute token budget (TPM). A long Vosk transcript
(40k+ tokens for an hour-long video) blows past the limit in a single
call and the request 429s before it even gets to OpenAI's processing.

We break the transcript into paragraph/sentence-aligned chunks small
enough that input + output fit comfortably under one minute's TPM
window (~22k input tokens → ~70k chars, conservatively), arrange each
chunk independently with the same system prompt, sleep enough between
calls to let the TPM bucket refill, and concatenate the arranged
outputs. Each chunk is independently parsable in the
"STOCK\nanalysis\nSTOCK\nanalysis" shape so concatenation just works.
"""

import os
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


# Approximate chars-per-token for mixed Hindi/English transcripts. Pure
# English is ~4 chars/token; Devanagari is ~1.5 chars/token; Vosk output
# is mostly Hindi-with-Latin-script transliteration, so 3 is a safe
# middle estimate (errs on the side of overestimating tokens).
CHARS_PER_TOKEN = 3

# Per-request input budget. The org's TPM cap is 30k; we keep one
# chunk's worth of input + output under ~18k tokens so a single chunk
# never trips the rate limit even with a chatty output and the ~500-
# token system prompt. 18k tokens × 3 chars/token = ~54k chars; we use
# 45k for extra headroom against the chars/token estimate being off
# (English-heavy text tokenizes denser than 3 chars/token, so we'd
# under-count). With max_tokens=8192 output, total budget per request
# stays well under the 30k TPM cap.
MAX_CHUNK_CHARS = 45_000

# Paced wait between consecutive chunk calls. The TPM window is rolling
# 60s; we wait a touch over that so the previous chunk's tokens fully
# fall out of the window before we send the next.
INTER_CHUNK_SLEEP_SECS = 65


SYSTEM_PROMPT = """You are an editor who FILTERS and REFORMATS a free-form spoken financial
transcript so the Bulk Rationale tool can parse it.

The transcript is from a financial show hosted by Pradip Halder. Other
speakers (guests, callers, anchors, ad reads) may also speak in it. Your
job is to keep ONLY the stocks on which **Pradip Halder personally** gave
analysis, and discard everything else.

PROCEDURE:
1. Read the transcript line by line.
2. For every stock mentioned, decide: did Pradip Halder himself give the
   analysis for this stock? (Not a guest, not a caller, not the anchor
   reading sponsor copy.)
3. If yes → output the stock name on its own line, followed by Pradip
   Halder's verbatim analysis for that stock on the next line(s).
4. If no (someone else's view, casual mention with no analysis, filler,
   greetings, ads) → drop it.
5. Continue through the entire transcript in spoken order.

OUTPUT FORMAT (STRICT):
- For every stock kept, FIRST LINE = the stock name (or symbol) alone.
- NEXT LINE(S) = Pradip Halder's analysis for that stock, verbatim.
- Then the next stock name on its own line, then its analysis. Repeat.
- Do NOT add headings, numbering, bullet points, markdown, or commentary.
- Do NOT translate. Keep the analysis in the original language exactly.
- Do NOT rewrite, paraphrase, summarize, "polish", or "improve" anything.
  Do NOT fix grammar. Do NOT remove duplicated words. Copy each word
  verbatim, in the original spoken order.
- The ONLY transformations allowed are:
    a) Removing speech that is not Pradip Halder analyzing a stock.
    b) Cutting at stock boundaries.
    c) Inserting a newline between the stock name line and its analysis.
- If two stocks share the same analysis from Pradip Halder, list them
  comma-separated on one stock-name line followed by that single
  analysis (e.g. `RELIANCE, TCS\\nbreakout above ...`).
- A stock name line should be the bare ticker / company name only — no
  "buy", "call", "stock", "the", brackets, or labels. Strip those words
  ONLY from the stock-name line, never from the analysis body.
- If Pradip Halder gave NO stock analysis in this segment, output an
  empty response.

RESPOND WITH ONLY THE REFORMATTED TRANSCRIPT, NOTHING ELSE."""


def _split_into_chunks(text: str, max_chars: int) -> list:
    """Greedy chunker that respects paragraph and sentence boundaries.

    Vosk output usually has no paragraph breaks (it's one giant blob), so
    the second pass — splitting on sentence enders including the Hindi
    danda `।` — does most of the work. Only as a last resort do we
    hard-cut mid-sentence."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # First pass: paragraph blocks.
    paragraphs = [p for p in text.split('\n') if p.strip()]
    chunks: list = []
    current: list = []
    current_len = 0

    def _flush():
        nonlocal current, current_len
        if current:
            chunks.append('\n'.join(current).strip())
            current = []
            current_len = 0

    for p in paragraphs:
        if len(p) > max_chars:
            # Paragraph itself too big — flush what we have and split it
            # at sentence boundaries.
            _flush()
            sentences = re.split(r'(?<=[.।!?])\s+', p)
            buf: list = []
            buf_len = 0
            for s in sentences:
                if len(s) > max_chars:
                    # Sentence itself too big (rare, but Vosk can run on
                    # for thousands of chars without punctuation). Hard-
                    # cut into max_chars-sized pieces.
                    if buf:
                        chunks.append(' '.join(buf).strip())
                        buf, buf_len = [], 0
                    for i in range(0, len(s), max_chars):
                        chunks.append(s[i:i + max_chars].strip())
                    continue
                if buf_len + len(s) + 1 > max_chars and buf:
                    chunks.append(' '.join(buf).strip())
                    buf = [s]
                    buf_len = len(s)
                else:
                    buf.append(s)
                    buf_len += len(s) + 1
            if buf:
                chunks.append(' '.join(buf).strip())
            continue

        if current_len + len(p) + 1 > max_chars and current:
            _flush()
        current.append(p)
        current_len += len(p) + 1

    _flush()
    return [c for c in chunks if c]


def _arrange_one_chunk(client, chunk_text: str) -> tuple:
    """Single OpenAI call for one chunk. Raises on error so the caller
    can decide whether to fail-fast or accumulate partial results.

    Returns (arranged_text, total_tokens_used) so the caller can log
    real token consumption (vs our coarse char/3 estimate) and verify
    we're staying within the TPM budget."""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chunk_text},
        ],
        temperature=0.0,
        # Output budget — kept small so input+output stays well under the
        # 30k TPM cap for a single chunk. Pradip-Halder-only filtering
        # also tends to shrink the output vs the input.
        max_tokens=8192,
    )
    text = (resp.choices[0].message.content or '').strip()
    # `usage` is None on streaming responses but always present on
    # non-streaming. Default to 0 so logging never crashes.
    total_tokens = getattr(resp.usage, 'total_tokens', 0) if resp.usage else 0
    return text, total_tokens


def run(transcript_text: str) -> dict:
    """Filter & rearrange transcript_text via OpenAI.

    Returns:
        { 'success': bool, 'arranged_text': str, 'error': str|None }
    """
    print("\n" + "=" * 60)
    print("VOICE TYPING: ARRANGE TRANSCRIPT (Pradip Halder filter)")
    print("=" * 60)

    if not transcript_text or not transcript_text.strip():
        return {'success': False, 'arranged_text': '', 'error': 'Transcript is empty'}

    key = _get_openai_key()
    if not key:
        return {
            'success': False,
            'arranged_text': '',
            'error': 'OpenAI API key not found. Add it under API Keys.',
        }

    chunks = _split_into_chunks(transcript_text, MAX_CHUNK_CHARS)
    print(f"📝 Input transcript: {len(transcript_text)} chars (~{len(transcript_text)//CHARS_PER_TOKEN} tokens)")
    print(f"📦 Split into {len(chunks)} chunk(s) of up to {MAX_CHUNK_CHARS} chars each")

    try:
        client = openai.OpenAI(api_key=key)
        arranged_parts: list = []

        for i, chunk in enumerate(chunks, start=1):
            print(f"  ↪ Chunk {i}/{len(chunks)}: {len(chunk)} chars (~{len(chunk)//CHARS_PER_TOKEN} tokens estimated)")
            arranged, used_tokens = _arrange_one_chunk(client, chunk)
            print(f"    ⓘ Actual tokens used (input+output): {used_tokens}")
            if arranged:
                arranged_parts.append(arranged)
                print(f"    ✓ Arranged: {len(arranged)} chars")
            else:
                # Empty result for this chunk = no Pradip Halder analysis
                # in that segment, which is allowed by the prompt. Skip.
                print("    · No Pradip Halder analysis in this chunk — skipped.")

            # Pace between chunks so the TPM window has time to refill.
            # Skip the wait after the last chunk.
            if i < len(chunks):
                print(f"    ⏳ Waiting {INTER_CHUNK_SLEEP_SECS}s before next chunk (TPM cooldown)...")
                time.sleep(INTER_CHUNK_SLEEP_SECS)

        if not arranged_parts:
            return {
                'success': False,
                'arranged_text': '',
                'error': 'OpenAI returned no Pradip Halder analysis for any chunk. Check the transcript content.',
            }

        # Each chunk's output is already in the strict
        # STOCK\nanalysis\nSTOCK\nanalysis... shape. A blank line
        # between chunks keeps the boundary visible without breaking
        # the parser (Bulk Rationale skips blank lines between blocks).
        arranged = '\n'.join(arranged_parts).strip()

        print(f"✅ Final arranged length: {len(arranged)} chars from {len(arranged_parts)} chunk(s)")
        print("📋 Preview:")
        print("-" * 40)
        print(arranged[:500] + ("..." if len(arranged) > 500 else ""))
        return {'success': True, 'arranged_text': arranged, 'error': None}

    except openai.RateLimitError as e:
        # Bubble up a clearer message than the raw 429 body.
        msg = (
            f"OpenAI rate limit hit even after chunking ({e}). "
            "Try again in a minute, or shorten the transcript before clicking Arrange."
        )
        print(f"❌ Arrange rate-limit error: {e}")
        return {'success': False, 'arranged_text': '', 'error': msg}
    except Exception as e:
        print(f"❌ Arrange error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'arranged_text': '', 'error': str(e)}
