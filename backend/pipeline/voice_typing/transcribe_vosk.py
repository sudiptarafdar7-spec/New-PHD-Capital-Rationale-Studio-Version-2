"""
Voice Typing — Server-side Vosk transcription worker.

This module replaces the browser Web Speech API with a server-side speech-to-
text pipeline so transcription continues even if the user closes their browser.

Pipeline:
  1. Download the YouTube audio (via the existing step01_download_audio path
     that produces a 16 kHz mono WAV — the exact format Vosk expects).
  2. Load the appropriate Vosk model (auto-downloaded once and cached on disk
     under backend/models/vosk/).
  3. Stream the WAV through KaldiRecognizer in small chunks. Every ~3 seconds
     of wall-clock time we flush the partial transcript + a progress percentage
     into jobs.payload so the frontend's poller can show live updates.
  4. On completion, flip the job status from `recording` to `awaiting_review`
     so the user can edit the transcript and click "Save & send to Bulk".

Cancellation: between chunks we re-read jobs.status — if the user moved it
away from `recording` (Stop button, delete, anything) we abort cleanly.

Concurrency safety:
  * jobs.payload updates use Postgres' jsonb merge operator (`payload || …`)
    so concurrent worker + user PATCH writes never clobber each other.
  * Model downloads use a cross-process file lock (fcntl) plus a `.complete`
    marker file so multiple Gunicorn workers can boot in parallel without
    racing on the same zip.
  * `recover_orphans()` (called from backend/app.py at startup) re-spawns
    workers for any voice-typing jobs left in `recording` state after a
    server restart.
"""

import os
import json
import time
import wave
import fcntl
import shutil
import zipfile
import threading
import urllib.request
from datetime import datetime

from backend.utils.database import get_db_cursor


# Model registry. Keep these to the SMALL variants — they're 40-50 MB each
# and download in a few seconds. The larger Vosk models (1.5 GB+) need a
# fatter VPS than what we want to assume.
VOSK_MODELS = {
    'hi': (
        'vosk-model-small-hi-0.22',
        'https://alphacephei.com/vosk/models/vosk-model-small-hi-0.22.zip',
    ),
    'en-IN': (
        'vosk-model-small-en-in-0.4',
        'https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip',
    ),
    'en': (
        'vosk-model-small-en-us-0.15',
        'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip',
    ),
}

MODELS_DIR = os.path.join('backend', 'models', 'vosk')


def _resolve_language(language: str) -> str:
    """Map a job's BCP-47 language tag (e.g. 'hi-IN', 'en-US') to one of our
    Vosk model keys. Defaults to Hindi small since this app is built for
    Indian financial content."""
    if not language:
        return 'hi'
    low = language.lower().strip()
    if low.startswith('hi'):
        return 'hi'
    if low in ('en-in', 'en_in') or low.startswith('en-in'):
        return 'en-IN'
    if low.startswith('en'):
        return 'en'
    return 'hi'


def ensure_model(language: str) -> str:
    """Return the local filesystem path to a Vosk model for `language`.
    Downloads and unzips it on first use. Safe across multiple processes
    (Gunicorn workers): uses an fcntl exclusive lock on a side file plus a
    `.complete` marker inside the model directory so we never serve a
    half-extracted model."""
    key = _resolve_language(language)
    model_name, url = VOSK_MODELS[key]
    target = os.path.join(MODELS_DIR, model_name)
    marker = os.path.join(target, '.complete')

    # Fast path — fully extracted and verified.
    if os.path.isfile(marker):
        return target

    os.makedirs(MODELS_DIR, exist_ok=True)
    lock_path = os.path.join(MODELS_DIR, f'.{model_name}.lock')

    # Cross-process exclusive lock: blocks until any concurrent downloader
    # finishes. fcntl.flock is per-FD so we re-open here even if called from
    # the same process.
    with open(lock_path, 'w') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            # Re-check after acquiring the lock — the holder may have
            # finished the work for us.
            if os.path.isfile(marker):
                return target

            # Wipe any half-extracted leftovers from a previous crash.
            if os.path.isdir(target):
                print(f"⚠️  [vosk] Removing partial extract at {target}")
                shutil.rmtree(target, ignore_errors=True)

            zip_path = os.path.join(MODELS_DIR, f'{model_name}.zip')
            print(f"⬇️  [vosk] Downloading model {model_name} from {url}")
            urllib.request.urlretrieve(url, zip_path)
            size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 1)
            print(f"📦 [vosk] Downloaded {size_mb} MB. Extracting…")

            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(MODELS_DIR)

            try:
                os.remove(zip_path)
            except OSError:
                pass

            if not os.path.isdir(target):
                raise RuntimeError(
                    f"Vosk model {model_name} extracted but expected directory not found at {target}"
                )

            # Marker file is the source of truth — only written after a
            # successful extraction so partial state never looks complete.
            with open(marker, 'w') as f:
                f.write('ok')

            print(f"✅ [vosk] Model ready at {target}")
            return target
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Database helpers — all updates use a fresh connection so the worker thread
# is decoupled from any request-scoped DB context. Writes use Postgres' JSONB
# merge operator so a worker flush + a user PATCH never overwrite each
# other's keys.
# ---------------------------------------------------------------------------

def _read_job(job_id: str):
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT id, status, payload, youtube_url FROM jobs WHERE id = %s",
            (job_id,),
        )
        return cursor.fetchone()


def _payload_dict(row) -> dict:
    if not row:
        return {}
    p = row.get('payload') if isinstance(row, dict) else row['payload']
    if not p:
        return {}
    if isinstance(p, dict):
        return p
    try:
        return json.loads(p)
    except Exception:
        return {}


def _patch_payload(job_id: str, **payload_updates) -> bool:
    """Atomically merge `payload_updates` into jobs.payload using Postgres'
    `||` operator. Returns False if the row no longer exists."""
    if not payload_updates:
        return True
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE jobs "
            "SET payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
            "    updated_at = %s "
            "WHERE id = %s",
            (json.dumps(payload_updates), datetime.now(), job_id),
        )
        return cursor.rowcount > 0


def _patch_progress(job_id: str, transcript_text: str, progress: int,
                    status: str | None = None) -> bool:
    """Push a transcript snapshot + progress percentage in one atomic
    statement. Returns False if the job was deleted (worker should bail)."""
    payload_patch = {
        'transcript_text': transcript_text,
        'transcribe_progress': progress,
    }
    sql = (
        "UPDATE jobs "
        "SET payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
        "    progress = %s, updated_at = %s"
    )
    params: list = [json.dumps(payload_patch), progress, datetime.now()]
    if status:
        sql += ", status = %s"
        params.append(status)
    sql += " WHERE id = %s"
    params.append(job_id)
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount > 0


def _mark_failed(job_id: str, error: str):
    """Move the job into 'failed' state with a payload error string. Uses
    JSONB merge so any concurrent transcript flush isn't clobbered."""
    payload_patch = {'transcribe_error': error[:500]}
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE jobs "
            "SET status = 'failed', "
            "    payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
            "    updated_at = %s "
            "WHERE id = %s",
            (json.dumps(payload_patch), datetime.now(), job_id),
        )


def _is_cancelled(job_id: str) -> bool:
    """The user can stop the worker by PATCHing status away from 'recording'
    (e.g. the editor's Stop button flips it to 'awaiting_review'). Job
    deletion also counts as cancellation."""
    row = _read_job(job_id)
    if not row:
        return True
    return row['status'] != 'recording'


# ---------------------------------------------------------------------------
# The actual worker
# ---------------------------------------------------------------------------

def transcribe_youtube_job(job_id: str, video_url: str, language: str = 'hi-IN'):
    """Background-thread entry point. Downloads the YouTube audio for the
    given Voice Typing job, then runs Vosk over it, streaming the transcript
    into jobs.payload as it progresses.

    This function is intentionally self-contained — no Flask / request context.
    Safe to call from threading.Thread(target=transcribe_youtube_job, ...).
    """
    print(f"\n🎙️  [vosk] Worker started for job {job_id} (lang={language})")
    print(f"    video: {video_url}")

    # Local imports so the heavy Vosk module only loads when actually needed.
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
    except Exception as e:
        _mark_failed(job_id, f"Vosk import failed: {e}")
        return

    try:
        from backend.pipeline.step01_download_audio import download_audio
    except Exception as e:
        _mark_failed(job_id, f"Audio downloader import failed: {e}")
        return

    # ---- Step 1: download + convert audio -------------------------------
    if not _patch_progress(job_id, '[Downloading video audio…]', 2):
        print(f"🛑 [vosk] {job_id} disappeared before download")
        return
    if _is_cancelled(job_id):
        print(f"🛑 [vosk] {job_id} cancelled before download")
        return

    try:
        dl = download_audio(job_id, video_url)
    except Exception as e:
        _mark_failed(job_id, f"Audio download crashed: {e}")
        return

    if not dl.get('success'):
        # Surface the underlying error AND give the user the path to
        # recover via manual upload — the API exposes POST .../upload-audio
        # which lets them attach a local audio file and resume from here.
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

    print(f"📥 [vosk] Audio ready: {audio_path}")

    if _is_cancelled(job_id):
        print(f"🛑 [vosk] {job_id} cancelled after download")
        return

    # Hand off to the shared model + streaming loop. Same loop runs for the
    # manual-upload path (transcribe_uploaded_job below).
    _run_vosk_on_wav(job_id, audio_path, language, Model, KaldiRecognizer)


def _run_vosk_on_wav(job_id: str, audio_path: str, language: str,
                     Model, KaldiRecognizer):
    """Shared Vosk transcription loop. Caller must have already produced a
    16 kHz / mono / 16-bit PCM WAV at `audio_path` and updated the job to
    status='recording'. This function owns the rest of the pipeline:

      • load the speech model
      • stream audio chunks through Vosk
      • flush partial transcripts to jobs.payload every ~3s
      • flip status='awaiting_review' on completion

    Used by both the YouTube path (`transcribe_youtube_job`) and the
    manual-upload path (`transcribe_uploaded_job`).
    """
    # ---- Step 2: ensure the speech model is on disk ---------------------
    if not _patch_progress(job_id, '[Loading Hindi/English speech model…]', 4):
        print(f"🛑 [vosk] {job_id} disappeared before model load")
        return
    try:
        model_path = ensure_model(language)
        model = Model(model_path)
    except Exception as e:
        _mark_failed(job_id, f"Speech model load failed: {e}")
        return

    if _is_cancelled(job_id):
        print(f"🛑 [vosk] {job_id} cancelled after model load")
        return

    # ---- Step 3: stream the WAV through Vosk ----------------------------
    try:
        wf = wave.open(audio_path, 'rb')
    except Exception as e:
        _mark_failed(job_id, f"Could not open WAV: {e}")
        return

    if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
        wf.close()
        _mark_failed(
            job_id,
            f"Audio must be 16-bit mono PCM (got channels={wf.getnchannels()}, "
            f"width={wf.getsampwidth()})",
        )
        return

    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(False)

    total_frames = wf.getnframes() or 1
    processed_frames = 0
    chunks: list[str] = []
    last_db_flush = 0.0
    chunk_size = 4000  # frames per read ≈ 0.25 s at 16 kHz

    print(f"🎧 [vosk] Streaming {total_frames} frames "
          f"(~{total_frames / wf.getframerate():.0f}s of audio)…")

    try:
        while True:
            if _is_cancelled(job_id):
                print(f"🛑 [vosk] {job_id} cancelled mid-transcription")
                # Persist whatever we have so far before exiting.
                final_text = ' '.join(c for c in chunks if c).strip()
                _patch_progress(job_id, final_text, 100, status='awaiting_review')
                wf.close()
                return

            data = wf.readframes(chunk_size)
            if len(data) == 0:
                break
            processed_frames += chunk_size

            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                text = (res.get('text') or '').strip()
                if text:
                    chunks.append(text)

            now = time.time()
            if now - last_db_flush > 3.0:
                last_db_flush = now
                try:
                    partial = json.loads(rec.PartialResult()).get('partial', '').strip()
                except Exception:
                    partial = ''
                live_text = ' '.join(chunks).strip()
                if partial:
                    live_text = (live_text + ' ' + partial).strip()
                pct = 5 + int(processed_frames * 90 / total_frames)
                pct = max(5, min(95, pct))
                if not _patch_progress(job_id, live_text, pct):
                    print(f"🛑 [vosk] {job_id} disappeared mid-transcribe")
                    wf.close()
                    return
    finally:
        try:
            wf.close()
        except Exception:
            pass

    # ---- Step 4: final flush + lifecycle bump ---------------------------
    try:
        final = json.loads(rec.FinalResult())
        if final.get('text'):
            chunks.append(final['text'].strip())
    except Exception as e:
        print(f"⚠️  [vosk] FinalResult decode warning: {e}")

    final_text = ' '.join(c for c in chunks if c).strip()
    if not final_text:
        # Don't fail — just leave the user with an empty transcript so they
        # can retry or type their own.
        final_text = '[No speech detected — please verify the video has audible speech.]'

    if not _patch_progress(job_id, final_text, 100, status='awaiting_review'):
        print(f"⚠️  [vosk] {job_id} vanished before final flush — nothing to do")
        return
    print(f"✅ [vosk] Worker finished {job_id} — {len(final_text)} chars")


def spawn(job_id: str, video_url: str, language: str = 'hi-IN'):
    """Fire-and-forget thread launcher. Always use this from request handlers."""
    t = threading.Thread(
        target=transcribe_youtube_job,
        args=(job_id, video_url, language),
        name=f"vosk-{job_id}",
        daemon=True,
    )
    t.start()
    return t


# ---------------------------------------------------------------------------
# Manual upload path
#
# When YouTube download fails (geo-blocked video, private upload, expired
# cookies, RapidAPI quota, etc.) the user can attach a local audio file
# directly. The API endpoint stores the raw upload, then calls spawn_uploaded
# which converts it to the canonical 16 kHz mono WAV via ffmpeg and runs the
# same shared Vosk loop the YouTube path uses.
# ---------------------------------------------------------------------------

def transcribe_uploaded_job(job_id: str, source_audio_path: str,
                            language: str = 'hi-IN'):
    """Background-thread entry point for the manual-upload path. Converts the
    user-supplied audio file to 16 kHz mono PCM WAV via ffmpeg, then runs the
    shared Vosk loop. The original upload is preserved so the user can
    retry with a different language without re-uploading."""
    print(f"\n🎙️  [vosk] Upload worker started for job {job_id} (lang={language})")
    print(f"    source: {source_audio_path}")

    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
    except Exception as e:
        _mark_failed(job_id, f"Vosk import failed: {e}")
        return

    if not os.path.exists(source_audio_path):
        _mark_failed(job_id, f"Uploaded audio file missing on disk: {source_audio_path}")
        return

    # ---- Step 1: ffmpeg-convert the upload to 16 kHz mono WAV -----------
    if not _patch_progress(job_id, '[Converting uploaded audio…]', 2):
        print(f"🛑 [vosk] {job_id} disappeared before conversion")
        return
    if _is_cancelled(job_id):
        print(f"🛑 [vosk] {job_id} cancelled before conversion")
        return

    audio_folder = os.path.join("backend", "job_files", job_id, "audio")
    os.makedirs(audio_folder, exist_ok=True)
    prepared_audio_path = os.path.join(audio_folder, "audio_16k_mono.wav")

    import subprocess
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", source_audio_path,
                "-ar", "16000", "-ac", "1", "-y",
                prepared_audio_path,
            ],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        _mark_failed(job_id, "Audio conversion timed out after 10 minutes — try a shorter file.")
        return
    except FileNotFoundError:
        _mark_failed(job_id, "ffmpeg is not installed on the server. Please contact the administrator.")
        return
    except Exception as e:
        _mark_failed(job_id, f"Audio conversion crashed: {e}")
        return

    if result.returncode != 0:
        # ffmpeg's stderr is the useful diagnostic — trim to last 800 chars.
        tail = (result.stderr or '')[-800:].strip()
        _mark_failed(job_id, f"FFmpeg conversion failed: {tail or 'unknown ffmpeg error'}")
        return

    if not os.path.exists(prepared_audio_path):
        _mark_failed(job_id, "FFmpeg reported success but no WAV was produced.")
        return

    print(f"📥 [vosk] Converted upload ready: {prepared_audio_path}")

    if _is_cancelled(job_id):
        print(f"🛑 [vosk] {job_id} cancelled after conversion")
        return

    # Hand off to the shared model + streaming loop.
    _run_vosk_on_wav(job_id, prepared_audio_path, language, Model, KaldiRecognizer)


def spawn_uploaded(job_id: str, source_audio_path: str, language: str = 'hi-IN'):
    """Fire-and-forget thread launcher for the manual-upload path."""
    t = threading.Thread(
        target=transcribe_uploaded_job,
        args=(job_id, source_audio_path, language),
        name=f"vosk-upload-{job_id}",
        daemon=True,
    )
    t.start()
    return t


# ---------------------------------------------------------------------------
# Orphan recovery — called once at server startup.
#
# Daemon transcription threads do NOT survive a process restart (Gunicorn
# reload, Flask debug-mode reload, server crash, etc.). When we boot up we
# scan for any voice-typing jobs that are still marked `recording`, mark
# their transcript field with a "[Resumed after restart…]" placeholder, and
# kick the Vosk worker again. Audio download is idempotent (yt-dlp will
# reuse the cached WAV) so this just resumes work cheaply.
# ---------------------------------------------------------------------------

def recover_orphans():
    """Re-spawn Vosk workers for any voice typing jobs left in `recording`
    status after a server restart. Safe to call multiple times — duplicate
    spawns will both eventually flush the same final transcript, with the
    last writer winning (a benign race for our use case)."""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id, payload, youtube_url
                FROM jobs
                WHERE tool_used = 'Voice Typing' AND status = 'recording'
                """
            )
            rows = cursor.fetchall() or []
    except Exception as e:
        print(f"[vosk] orphan scan failed: {e}")
        return 0

    recovered = 0
    for row in rows:
        try:
            payload = _payload_dict(row)
            language = payload.get('language', 'hi-IN')
            uploaded_audio_path = payload.get('uploaded_audio_path')
            video_url = payload.get('video_url') or row.get('youtube_url')

            # Prefer the uploaded-audio path if the job was kicked off via the
            # manual-upload endpoint (the user explicitly opted out of YouTube
            # download). Otherwise fall back to re-running the YouTube path.
            # Voice Typing now uses Gemini as the primary engine (better
            # Hindi multi-speaker accuracy). Recovery hands off to those
            # spawn functions; Vosk is retained only as a legacy fallback.
            from backend.pipeline.voice_typing.transcribe_gemini import (
                spawn as gemini_spawn,
                spawn_uploaded as gemini_spawn_uploaded,
            )
            if uploaded_audio_path and os.path.exists(uploaded_audio_path):
                print(f"♻️  [voice-typing] Recovering orphan UPLOAD job {row['id']} via Gemini")
                _patch_progress(row['id'], '[Resumed after server restart…]', 1)
                gemini_spawn_uploaded(row['id'], uploaded_audio_path, language)
                recovered += 1
            elif video_url:
                print(f"♻️  [voice-typing] Recovering orphan YOUTUBE job {row['id']} via Gemini")
                _patch_progress(row['id'], '[Resumed after server restart…]', 1)
                gemini_spawn(row['id'], video_url, language)
                recovered += 1
            else:
                print(f"[vosk] orphan {row['id']} has neither uploaded_audio_path "
                      f"nor video_url — marking failed")
                _mark_failed(
                    row['id'],
                    'Server restarted but no audio source could be recovered. '
                    'Please delete this job and start over.',
                )
        except Exception as e:
            print(f"[vosk] orphan recover failed for {row.get('id')}: {e}")
    if recovered:
        print(f"♻️  [vosk] Recovered {recovered} orphaned job(s)")
    return recovered
