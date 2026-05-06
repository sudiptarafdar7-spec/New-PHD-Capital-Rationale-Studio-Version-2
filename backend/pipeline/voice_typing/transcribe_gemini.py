"""
Voice Typing — Server-side Gemini transcription worker.

Replaces the Vosk small-model pipeline with Google Gemini 2.5 Pro audio
understanding for **dramatically better Hindi multi-speaker accuracy** on
Indian financial TV / podcast content.

Why Gemini (and not AssemblyAI):
- AssemblyAI is reserved for the AI Transcribe tool. Voice Typing needed
  its own engine.
- Vosk small-hi-0.22 (the previous engine) is ~40 MB and word-error-rate
  on real Hindi business audio is poor. The big Vosk model is 1.5 GB+
  and still no speaker diarization.
- Gemini 2.5 Pro accepts raw audio, transcribes Hindi (Devanagari) with
  near-human accuracy, preserves English brand / ticker words verbatim,
  and we can ask it to label distinct speakers via prompt.

Pipeline:
  1. Reuse the existing 16 kHz mono WAV produced by step01_download_audio
     (or by ffmpeg-converting the user's manual upload).
  2. Re-encode to a small mono 16 kHz MP3 (~64 kbps) and split into
     CHUNK_SECONDS-long segments via ffmpeg `-f segment`. Chunking keeps
     per-call latency bounded and lets us stream live progress into
     jobs.payload between segments.
  3. For each chunk, upload to Gemini Files API, call generate_content
     with the Hindi multi-speaker transcription prompt, append to the
     running transcript, and flush progress + partial text to the DB.
  4. On completion flip jobs.status to `awaiting_review` so the existing
     5-step Voice Typing review UI takes over (Translate → Arrange → Bulk).

Cancellation, orphan recovery, and JSONB-merge progress writes are all
delegated to the helpers already defined in `transcribe_vosk.py` so the
two engines share the same DB plumbing.
"""

import os
import time
import wave
import threading
import subprocess

from backend.pipeline.voice_typing.transcribe_vosk import (
    _patch_progress,
    _mark_failed,
    _is_cancelled,
)


# Per-chunk wall-clock target. 5 minutes keeps a single Gemini call under
# ~60s for typical Hindi business audio while still giving 12 progress
# ticks per hour of input.
CHUNK_SECONDS = 300

# Ask Gemini to transcribe in the *original* language (no translation),
# label distinct speakers, and avoid hallucinating commentary. The
# downstream Voice Typing review pipeline (translate → arrange → bulk)
# expects Hindi-script source text, so explicitly tell the model to keep
# Devanagari for Hindi and ASCII for English brand names / tickers.
GEMINI_TRANSCRIBE_PROMPT_HI = """\
You are an expert Hindi audio transcriber for an Indian stock-market TV show / podcast.

The audio MAY contain multiple speakers (anchor + analyst, panel discussion, interview, etc.).
Transcribe it with the highest possible accuracy following these rules:

1. Output the transcript in the ORIGINAL spoken language. Hindi must be in Devanagari (देवनागरी).
   Keep English words, English company names and stock tickers (e.g. "Reliance", "TCS", "INFY",
   "Nifty 50") in English / ASCII exactly as spoken — do NOT transliterate them.
2. Identify each distinct speaker. Label every speech turn at the start of its line as
   "वक्ता 1:", "वक्ता 2:", "वक्ता 3:" … and reuse the same number every time the same person
   speaks. If you can confidently infer a name from the audio (e.g. "धन्यवाद Pradip जी"),
   you may add it in brackets like "वक्ता 2 (Pradip):".
3. Add natural punctuation — commas, full stops, question marks, dashes — so each line reads
   as a fluent sentence.
4. Do NOT translate. Do NOT summarise. Do NOT add headings, bullet points, markdown, or any
   commentary of your own. No code fences.
5. Preserve numbers, prices, percentages and stock symbols EXACTLY. Examples:
   "Reliance का target 1450", "Nifty 24,800 के पास", "stop loss 92.50".
6. If a stretch is inaudible, write [अस्पष्ट]. If it is music or background noise only,
   write [संगीत]. Never invent words to fill silence.
7. One speaker turn per line. If two speakers overlap, transcribe each on its own line in
   the order they finish speaking.

Output: plain text only. One line per speaker turn. Nothing else.
"""


# ---------------------------------------------------------------------------
# Audio prep helpers
# ---------------------------------------------------------------------------

def _wav_duration_seconds(audio_path: str) -> float:
    """Best-effort duration probe. Tries the stdlib wave module first
    (works for our canonical 16 kHz mono PCM WAV), then falls back to
    ffprobe for any other format."""
    try:
        with wave.open(audio_path, 'rb') as wf:
            rate = wf.getframerate() or 1
            return wf.getnframes() / rate
    except Exception:
        pass
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True, timeout=30,
        )
        return float((r.stdout or '0').strip() or 0)
    except Exception:
        return 0.0


def _encode_and_chunk(src_audio: str, out_dir: str, chunk_seconds: int) -> list[str]:
    """Re-encode `src_audio` to mono 16 kHz MP3 @ 64 kbps and split into
    `chunk_seconds`-long segments. Returns the ordered list of chunk
    file paths.

    Using mp3 (instead of the original WAV) keeps each Files-API upload
    around 2-3 MB per 5 minutes — well under Gemini's per-file limits and
    fast to upload over typical server bandwidth.
    """
    os.makedirs(out_dir, exist_ok=True)
    # Wipe any leftovers from a previous attempt — chunk numbering must
    # restart at 000 or sorted() will interleave old + new segments.
    for f in os.listdir(out_dir):
        if f.startswith('chunk_'):
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass

    pattern = os.path.join(out_dir, 'chunk_%04d.mp3')
    cmd = [
        'ffmpeg', '-y',
        '-i', src_audio,
        '-ac', '1', '-ar', '16000',
        '-codec:a', 'libmp3lame', '-b:a', '64k',
        '-f', 'segment',
        '-segment_time', str(chunk_seconds),
        '-reset_timestamps', '1',
        pattern,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg chunking failed: {(r.stderr or "")[-400:]}')

    chunks = sorted(
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith('chunk_') and f.endswith('.mp3')
    )
    return chunks


# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------

def _gemini_module():
    """Resolve the GEMINI_API_KEY (env var or DB-backed api_keys table)
    and return the configured `google.generativeai` module."""
    api_key = (os.environ.get('GEMINI_API_KEY') or '').strip()
    if not api_key:
        # Fall back to the DB-stored key if present (matches the pattern
        # used by other Gemini callers in this project).
        try:
            from backend.utils.database import get_db_cursor
            with get_db_cursor() as cursor:
                cursor.execute(
                    "SELECT key_value FROM api_keys WHERE key_name = 'gemini' LIMIT 1"
                )
                row = cursor.fetchone()
                if row:
                    api_key = (row.get('key_value') or '').strip()
        except Exception:
            pass
    if not api_key:
        raise RuntimeError(
            'GEMINI_API_KEY is not configured. Add it under Admin → API Keys, '
            'or set the GEMINI_API_KEY environment variable.'
        )
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    return genai


def _transcribe_chunk(genai, audio_path: str) -> str:
    """Upload one audio chunk to Gemini Files API and return the
    transcribed text. Caller handles retries."""
    from google.generativeai import GenerativeModel

    mime = 'audio/mpeg' if audio_path.lower().endswith('.mp3') else 'audio/wav'
    audio_file = genai.upload_file(path=audio_path, mime_type=mime)

    # Poll until ACTIVE — uploaded files start in PROCESSING state.
    deadline = time.time() + 120
    while audio_file.state.name == 'PROCESSING' and time.time() < deadline:
        time.sleep(1.0)
        audio_file = genai.get_file(audio_file.name)

    if audio_file.state.name != 'ACTIVE':
        raise RuntimeError(
            f'Gemini file upload did not become ACTIVE '
            f'(state={audio_file.state.name})'
        )

    try:
        model = GenerativeModel('gemini-2.5-pro')
        resp = model.generate_content(
            [GEMINI_TRANSCRIBE_PROMPT_HI, audio_file],
            generation_config={
                'temperature': 0.1,
                'max_output_tokens': 32768,
            },
        )
        text = (getattr(resp, 'text', '') or '').strip()
        return text
    finally:
        # Best-effort cleanup so the user's Files-API quota doesn't fill up.
        try:
            genai.delete_file(audio_file.name)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Shared transcription loop (used by both YouTube and upload paths)
# ---------------------------------------------------------------------------

def _run_gemini_on_audio(job_id: str, audio_path: str, language: str = 'hi-IN'):
    """Chunk → upload → transcribe loop. Streams partial transcript +
    progress percentage into jobs.payload after every chunk."""
    if not _patch_progress(job_id, '[Loading Gemini speech model…]', 4):
        print(f"🛑 [gemini-vt] {job_id} disappeared before model load")
        return

    try:
        genai = _gemini_module()
    except Exception as e:
        _mark_failed(job_id, f'Gemini setup failed: {e}')
        return

    if _is_cancelled(job_id):
        print(f"🛑 [gemini-vt] {job_id} cancelled before transcription")
        return

    duration = _wav_duration_seconds(audio_path)
    print(f"🎧 [gemini-vt] Audio duration ≈ {duration:.0f}s")

    chunk_dir = os.path.join(os.path.dirname(audio_path), 'gemini_chunks')
    try:
        if not _patch_progress(job_id, '[Preparing audio chunks for Gemini…]', 6):
            return
        chunks = _encode_and_chunk(audio_path, chunk_dir, CHUNK_SECONDS)
    except Exception as e:
        _mark_failed(job_id, f'Audio chunking failed: {e}')
        return

    if not chunks:
        _mark_failed(job_id, 'Audio chunking produced no segments — is the source audio empty?')
        return

    n = len(chunks)
    print(f"📦 [gemini-vt] {n} chunk(s) of ~{CHUNK_SECONDS}s each")

    transcript_parts: list[str] = []

    for i, chunk_path in enumerate(chunks):
        if _is_cancelled(job_id):
            print(f"🛑 [gemini-vt] {job_id} cancelled at chunk {i + 1}/{n}")
            final_text = '\n'.join(p for p in transcript_parts if p).strip()
            _patch_progress(job_id, final_text, 100, status='awaiting_review')
            return

        # Progress: 8 → 96, leaving the final 4% for cleanup + status flip.
        pct = 8 + int(i * 88 / max(n, 1))
        live_text = '\n'.join(transcript_parts).strip()
        live_text_with_marker = (
            (live_text + '\n\n' if live_text else '')
            + f'[Transcribing chunk {i + 1}/{n} with Gemini…]'
        )
        _patch_progress(job_id, live_text_with_marker, pct)

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                text = _transcribe_chunk(genai, chunk_path)
                if text:
                    transcript_parts.append(text)
                last_err = None
                break
            except Exception as e:
                last_err = e
                wait = 2 * (attempt + 1)
                print(f"⚠️  [gemini-vt] chunk {i + 1}/{n} attempt {attempt + 1} "
                      f"failed: {e} — retrying in {wait}s")
                time.sleep(wait)

        if last_err is not None:
            print(f"❌ [gemini-vt] chunk {i + 1}/{n} permanently failed; "
                  f"appending placeholder so the user can edit by hand")
            transcript_parts.append(
                f'[चंक {i + 1} ट्रांसक्राइब नहीं हो सका — कृपया मैन्युअल रूप से जोड़ें. ({last_err})]'
            )

    final_text = '\n'.join(p for p in transcript_parts if p).strip()
    if not final_text:
        final_text = '[No speech detected — please verify the audio has audible speech.]'

    if not _patch_progress(job_id, final_text, 100, status='awaiting_review'):
        print(f"⚠️  [gemini-vt] {job_id} vanished before final flush")
        return

    print(f"✅ [gemini-vt] Worker finished {job_id} — {len(final_text)} chars")

    # Best-effort cleanup of the temp mp3 chunks; safe to leave on failure.
    try:
        for f in os.listdir(chunk_dir):
            if f.startswith('chunk_'):
                try:
                    os.remove(os.path.join(chunk_dir, f))
                except OSError:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# YouTube path
# ---------------------------------------------------------------------------

def transcribe_youtube_job(job_id: str, video_url: str, language: str = 'hi-IN'):
    """Background-thread entry point. Downloads the YouTube audio for the
    given Voice Typing job, then runs Gemini over it, streaming the
    transcript into jobs.payload as it progresses."""
    print(f"\n🎙️  [gemini-vt] Worker started for job {job_id} (lang={language})")
    print(f"    video: {video_url}")

    try:
        from backend.pipeline.step01_download_audio import download_audio
    except Exception as e:
        _mark_failed(job_id, f'Audio downloader import failed: {e}')
        return

    if not _patch_progress(job_id, '[Downloading video audio…]', 2):
        return
    if _is_cancelled(job_id):
        return

    try:
        dl = download_audio(job_id, video_url)
    except Exception as e:
        _mark_failed(job_id, f'Audio download crashed: {e}')
        return

    if not dl.get('success'):
        err = dl.get('error') or 'Audio download failed'
        _mark_failed(
            job_id,
            f"{err}\n\nTip: you can upload the audio file manually instead — "
            f"use the 'Upload audio file' button below to bypass YouTube download.",
        )
        return

    audio_path = dl.get('prepared_audio')
    if not audio_path or not os.path.exists(audio_path):
        _mark_failed(job_id, 'Prepared 16kHz WAV missing after download')
        return

    if _is_cancelled(job_id):
        return

    _run_gemini_on_audio(job_id, audio_path, language)


# ---------------------------------------------------------------------------
# Manual-upload path
# ---------------------------------------------------------------------------

def transcribe_uploaded_job(job_id: str, source_audio_path: str,
                            language: str = 'hi-IN'):
    """Background-thread entry point for the manual-upload path. Converts
    the user-supplied audio file to 16 kHz mono PCM WAV via ffmpeg, then
    runs the shared Gemini loop."""
    print(f"\n🎙️  [gemini-vt] Upload worker started for job {job_id} (lang={language})")
    print(f"    source: {source_audio_path}")

    if not os.path.exists(source_audio_path):
        _mark_failed(job_id, f'Uploaded audio file missing on disk: {source_audio_path}')
        return

    if not _patch_progress(job_id, '[Converting uploaded audio…]', 2):
        return
    if _is_cancelled(job_id):
        return

    audio_folder = os.path.join('backend', 'job_files', job_id, 'audio')
    os.makedirs(audio_folder, exist_ok=True)
    prepared_audio_path = os.path.join(audio_folder, 'audio_16k_mono.wav')

    try:
        result = subprocess.run(
            [
                'ffmpeg', '-i', source_audio_path,
                '-ar', '16000', '-ac', '1', '-y',
                prepared_audio_path,
            ],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        _mark_failed(job_id, 'Audio conversion timed out after 10 minutes — try a shorter file.')
        return
    except FileNotFoundError:
        _mark_failed(job_id, 'ffmpeg is not installed on the server. Please contact the administrator.')
        return
    except Exception as e:
        _mark_failed(job_id, f'Audio conversion crashed: {e}')
        return

    if result.returncode != 0:
        tail = (result.stderr or '')[-800:].strip()
        _mark_failed(job_id, f'FFmpeg conversion failed: {tail or "unknown ffmpeg error"}')
        return

    if not os.path.exists(prepared_audio_path):
        _mark_failed(job_id, 'FFmpeg reported success but no WAV was produced.')
        return

    if _is_cancelled(job_id):
        return

    _run_gemini_on_audio(job_id, prepared_audio_path, language)


# ---------------------------------------------------------------------------
# Thread launchers
# ---------------------------------------------------------------------------

def spawn(job_id: str, video_url: str, language: str = 'hi-IN'):
    """Fire-and-forget thread launcher for the YouTube path."""
    t = threading.Thread(
        target=transcribe_youtube_job,
        args=(job_id, video_url, language),
        name=f'gemini-vt-{job_id}',
        daemon=True,
    )
    t.start()
    return t


def spawn_uploaded(job_id: str, source_audio_path: str, language: str = 'hi-IN'):
    """Fire-and-forget thread launcher for the manual-upload path."""
    t = threading.Thread(
        target=transcribe_uploaded_job,
        args=(job_id, source_audio_path, language),
        name=f'gemini-vt-upload-{job_id}',
        daemon=True,
    )
    t.start()
    return t
