"""
AI Transcribe Service
=====================

5-step pipeline that pauses for user review between content stages:

  1. Download Audio              (auto)
  2. Transcribe with AssemblyAI  (auto) → status='awaiting_review'
  3. Translate to English        (auto, on user "Save & Next") → status='awaiting_translate_review'
  4. Extract Pradip Halder's Analysis (auto, on user "Save & Next") → status='awaiting_extract_review'
  5. Send to Bulk Rationale      (on user "Send to Bulk Rationale")

Editable text at each review stage is stored in jobs.payload as
`transcript_text`, `translated_text`, `extracted_text`. The .txt file
on disk is kept in sync for download.

Two entry points:
  • transcribe_media_presence(media_id, source, language_code)
        — used by the Media Presence "AI Transcribe" method, persists the
          transcript onto the media_presence row. (Unchanged — still 1-shot.)
  • run_ai_transcribe_pipeline(job_id, job_folder, source, language_code)
        — the standalone pipeline. Drives a real `jobs` row + `job_steps`
          rows so it shows up on the dashboard like every other job.
"""

import os
import json
import time
import uuid
import openai
import threading
from datetime import datetime

from backend.utils.database import get_db_cursor
from backend.pipeline.step01_download_audio import download_audio
from backend.pipeline.step03_assemblyai_transcribe import transcribe_audio


TRANSCRIPT_ROOT = "backend/job_files/media_presence"


# -----------------------------------------------------------------------------
# 5-step definition (used to seed job_steps rows on create).
# -----------------------------------------------------------------------------

AI_TRANSCRIBE_STEPS = [
    {"step_number": 1, "name": "Download Audio",
     "description": "Download audio (RapidAPI / yt-dlp) and convert to 16 kHz mono WAV"},
    {"step_number": 2, "name": "Transcribe with AssemblyAI",
     "description": "Run AssemblyAI nano with speaker labels and the chosen language"},
    {"step_number": 3, "name": "Translate to English",
     "description": "Translate the reviewed transcript to English with GPT-4o"},
    {"step_number": 4, "name": "Extract Pradip Halder's Analysis",
     "description": "Filter & reformat the transcript into Bulk Rationale's stock-name / analysis pairs"},
    {"step_number": 5, "name": "Send to Bulk Rationale",
     "description": "Spawn a Bulk Rationale child job inheriting the channel + date + time"},
]
TOTAL_STEPS = len(AI_TRANSCRIBE_STEPS)


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------

def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _payload_dict(row):
    p = row.get("payload") if isinstance(row, dict) else row["payload"]
    if not p:
        return {}
    if isinstance(p, dict):
        return p
    try:
        return json.loads(p)
    except Exception:
        return {}


def _get_assemblyai_key():
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT key_value FROM api_keys WHERE LOWER(provider) = 'assemblyai'"
        )
        row = cursor.fetchone()
    if not row or not row.get("key_value"):
        raise RuntimeError(
            "AssemblyAI API key not configured. Add it under Administration → API Keys."
        )
    return row["key_value"]


def _get_openai_key():
    with get_db_cursor() as cursor:
        cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'openai'")
        row = cursor.fetchone()
    if row and row.get("key_value"):
        return row["key_value"].strip()
    return None


def _read_transcript_text(txt_path):
    with open(txt_path, "r", encoding="utf-8") as f:
        return f.read()


def _prepare_audio(job_id, source):
    job_folder = os.path.join("backend", "job_files", job_id)
    audio_folder = _ensure_dir(os.path.join(job_folder, "audio"))
    prepared_path = os.path.join(audio_folder, "audio_16k_mono.wav")

    if source.get("local_audio_path"):
        import subprocess
        cmd = [
            "ffmpeg", "-i", source["local_audio_path"],
            "-ar", "16000", "-ac", "1", "-y", prepared_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr.strip()}")
        return prepared_path

    if source.get("youtube_url"):
        result = download_audio(job_id, source["youtube_url"])
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "Audio download failed")
        return result["prepared_audio"]

    raise ValueError("Source must include youtube_url or local_audio_path")


# -----------------------------------------------------------------------------
# Media Presence entry point (unchanged behaviour — still 1-shot)
# -----------------------------------------------------------------------------

def transcribe_media_presence(media_id, source, language_code="hi"):
    job_id = f"mediapresence-{media_id}-{uuid.uuid4().hex[:6]}"
    try:
        api_key = _get_assemblyai_key()
        prepared_audio = _prepare_audio(job_id, source)
        outputs = transcribe_audio(job_id, prepared_audio, api_key, language_code=language_code)
        txt_path = next((p for p in outputs if p.endswith(".txt")), outputs[-1])
        text = _read_transcript_text(txt_path)

        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE media_presence
                SET transcribe_status = 'completed',
                    transcript_text = %s,
                    transcript_file_path = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (text, txt_path, datetime.now(), media_id),
            )
        return {"success": True, "transcript_path": txt_path, "transcript_text": text}

    except Exception as exc:
        err = str(exc)
        print(f"[ai_transcribe media_presence={media_id}] ERROR: {err}")
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE media_presence
                SET transcribe_status = 'failed',
                    notes = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (f"AI transcribe error: {err}", datetime.now(), media_id),
            )
        return {"success": False, "error": err}


# -----------------------------------------------------------------------------
# Standalone Job pipeline — job_steps + status helpers
# -----------------------------------------------------------------------------

def _set_step_running(cursor, job_id, step_num):
    cursor.execute(
        """UPDATE job_steps
           SET status = 'running', started_at = %s, message = NULL
           WHERE job_id = %s AND step_number = %s""",
        (datetime.now(), job_id, step_num),
    )


def _set_step_success(cursor, job_id, step_num, message=None, output_files=None):
    cursor.execute(
        """UPDATE job_steps
           SET status = 'success', ended_at = %s,
               message = %s, output_files = %s
           WHERE job_id = %s AND step_number = %s""",
        (datetime.now(), message, output_files or [], job_id, step_num),
    )


def _set_step_failed(cursor, job_id, step_num, message):
    cursor.execute(
        """UPDATE job_steps
           SET status = 'failed', ended_at = %s, message = %s
           WHERE job_id = %s AND step_number = %s""",
        (datetime.now(), message, job_id, step_num),
    )


def _update_job(cursor, job_id, *, current_step, status, progress=None,
                payload_patch=None, expect_status=None):
    """Update the parent job row.

    Pass ``expect_status`` to add a ``WHERE status = expect_status`` guard so
    duplicate / late background workers cannot move the job sideways. The
    caller is responsible for noticing the no-op (cursor.rowcount == 0).
    """
    if progress is None:
        # Step n complete → progress = n/TOTAL; in-flight step n → (n-1)/TOTAL.
        progress = int((current_step / TOTAL_STEPS) * 100)
    sql = ["UPDATE jobs SET current_step = %s, progress = %s, status = %s, updated_at = %s"]
    params = [current_step, progress, status, datetime.now()]
    if payload_patch:
        sql[0] += ", payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb"
        params.append(json.dumps(payload_patch))
    sql[0] += " WHERE id = %s"
    params.append(job_id)
    if expect_status is not None:
        sql[0] += " AND status = %s"
        params.append(expect_status)
    cursor.execute(sql[0], params)
    return cursor.rowcount


def _fail_job(cursor, job_id, step_num, error):
    _set_step_failed(cursor, job_id, step_num, error)
    cursor.execute(
        "UPDATE jobs SET status='failed', updated_at=%s WHERE id=%s",
        (datetime.now(), job_id),
    )


# -----------------------------------------------------------------------------
# Stage 1+2 — auto download + transcribe, then park at awaiting_review.
# -----------------------------------------------------------------------------

def run_ai_transcribe_pipeline(job_id, job_folder, source, language_code="hi"):
    """Background worker that runs Step 1 (download) + Step 2 (transcribe)
    and parks the job at status='awaiting_review' for the user to edit the
    transcript before Translate/Extract."""
    try:
        # ---- Step 1 -----------------------------------------------------
        with get_db_cursor(commit=True) as cursor:
            _set_step_running(cursor, job_id, 1)
            cursor.execute(
                "UPDATE jobs SET current_step=1, status='processing', progress=10, updated_at=%s WHERE id=%s",
                (datetime.now(), job_id),
            )
        print(f"\n{'='*60}\nAI Transcribe job {job_id} — Step 1: Download Audio\n{'='*60}")

        try:
            api_key = _get_assemblyai_key()
            prepared_audio = _prepare_audio(job_id, source)
        except Exception as exc:
            err = str(exc)
            with get_db_cursor(commit=True) as cursor:
                _fail_job(cursor, job_id, 1, err)
            _mp_linkback_failed(job_id, err)
            print(f"[ai_transcribe job={job_id}] STEP 1 FAILED: {err}")
            return

        with get_db_cursor(commit=True) as cursor:
            _set_step_success(
                cursor, job_id, 1,
                message=f"Audio ready: {os.path.basename(prepared_audio)}",
                output_files=[prepared_audio],
            )

        # ---- Step 2 -----------------------------------------------------
        with get_db_cursor(commit=True) as cursor:
            _set_step_running(cursor, job_id, 2)
            cursor.execute(
                "UPDATE jobs SET current_step=2, progress=25, updated_at=%s WHERE id=%s",
                (datetime.now(), job_id),
            )
        print(f"\n{'='*60}\nAI Transcribe job {job_id} — Step 2: Transcribe (lang={language_code})\n{'='*60}")

        try:
            outputs = transcribe_audio(job_id, prepared_audio, api_key, language_code=language_code)
            txt_path = next((p for p in outputs if p.endswith(".txt")), outputs[-1])
            text = _read_transcript_text(txt_path)
        except Exception as exc:
            err = str(exc)
            with get_db_cursor(commit=True) as cursor:
                _fail_job(cursor, job_id, 2, err)
            _mp_linkback_failed(job_id, err)
            print(f"[ai_transcribe job={job_id}] STEP 2 FAILED: {err}")
            return

        with get_db_cursor(commit=True) as cursor:
            _set_step_success(
                cursor, job_id, 2,
                message=f"AssemblyAI returned transcript ({len(text):,} chars)",
                output_files=outputs,
            )
            # Park at awaiting_review with the raw transcript editable.
            _update_job(
                cursor, job_id,
                current_step=2, progress=40,
                status="awaiting_review",
                payload_patch={"transcript_text": text, "transcript_file": txt_path},
            )

        print(f"⏸  AI Transcribe {job_id} parked at awaiting_review ({len(text):,} chars)")

    except Exception as exc:
        err = str(exc)
        print(f"❌ AI Transcribe pipeline crashed for job {job_id}: {err}")
        import traceback
        traceback.print_exc()
        try:
            with get_db_cursor(commit=True) as cursor:
                cursor.execute(
                    """UPDATE job_steps
                       SET status='failed', ended_at=%s, message=%s
                       WHERE job_id=%s AND status='running'""",
                    (datetime.now(), f"Pipeline crashed: {err}", job_id),
                )
                cursor.execute(
                    "UPDATE jobs SET status='failed', updated_at=%s WHERE id=%s",
                    (datetime.now(), job_id),
                )
        except Exception as inner:
            print(f"❌ Could not mark job {job_id} failed in DB: {inner}")
        # MP linkback on failure: if this job was spawned from a Media Presence
        # row, mirror the failure on that row so its Transcribe pill flips from
        # 'started' to 'failed' instead of getting stuck on the spinner.
        _mp_linkback_failed(job_id, err)


def _mp_linkback_failed(job_id, err_msg):
    """Mirror a job-level failure onto the linked media_presence row."""
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
            row = cursor.fetchone()
            if not row:
                return
            payload = row.get("payload") or {}
            if isinstance(payload, str):
                import json as _json
                try:
                    payload = _json.loads(payload)
                except Exception:
                    payload = {}
            mp_id = payload.get("media_presence_id")
            if mp_id:
                cursor.execute(
                    """UPDATE media_presence
                       SET transcribe_status = 'failed',
                           notes = %s,
                           updated_at = %s
                       WHERE id = %s""",
                    (f"AI Transcribe error: {err_msg[:500]}", datetime.now(), mp_id),
                )
    except Exception as link_err:
        print(f"⚠️  AI Transcribe {job_id}: MP failure linkback skipped: {link_err}")


# -----------------------------------------------------------------------------
# Stage 3 — Translate (background, triggered by /save-transcript-and-translate).
# -----------------------------------------------------------------------------

TRANSLATE_SYSTEM_PROMPT = """You are a professional translator specializing in financial content.
Translate the following text to English while:
1. Preserving all stock names, symbols, numbers, and financial terms accurately
2. Maintaining the original structure and formatting (preserve all sections, line breaks, and stock entries)
3. Keeping any dates, times, and price targets exactly as they appear
4. If the text is already in English, return it as-is with minor cleanup
5. Do not add any explanations or commentary - just translate
6. IMPORTANT: Translate ALL content completely - do not skip or truncate any sections
7. If a stock name appears to be gibberish or random characters, keep it as-is
8. Preserve any "[HH:MM:SS] Speaker X:" prefixes verbatim — DO NOT translate the speaker labels"""


def _translate_text(text):
    """Translate a (possibly multilingual) transcript to English with GPT-4o.
    Mirrors backend/pipeline/bulk/step01_translate.py but operates on text
    rather than files."""
    key = _get_openai_key()
    if not key:
        raise RuntimeError("OpenAI API key not found. Add it under API Keys.")
    if not (text or "").strip():
        raise ValueError("Transcript is empty")

    client = openai.OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
        max_tokens=16384,
    )
    return (resp.choices[0].message.content or "").strip()


def run_translate_step(job_id, transcript_text, job_folder):
    """Background Step 3 worker: translate the user-edited transcript.
    On success → status='awaiting_translate_review'."""
    try:
        with get_db_cursor(commit=True) as cursor:
            _set_step_running(cursor, job_id, 3)
            _update_job(cursor, job_id, current_step=3, status="translating", progress=50)

        print(f"\n{'='*60}\nAI Transcribe job {job_id} — Step 3: Translate\n{'='*60}")
        translated = _translate_text(transcript_text)
        print(f"✅ Translation complete: {len(translated):,} chars")

        # Save .txt alongside the original transcript for download / debugging.
        translated_path = os.path.join(job_folder, "transcripts", "transcript_english.txt")
        _ensure_dir(os.path.dirname(translated_path))
        with open(translated_path, "w", encoding="utf-8") as f:
            f.write(translated)

        with get_db_cursor(commit=True) as cursor:
            # Guarded — only park if we're still the active translating worker.
            rows = _update_job(
                cursor, job_id,
                current_step=3, progress=60,
                status="awaiting_translate_review",
                payload_patch={
                    "translated_text": translated,
                    "translated_file": translated_path,
                    "transcript_text": transcript_text,
                },
                expect_status="translating",
            )
            if rows == 0:
                print(f"⚠  AI Transcribe {job_id} translate finished but status was no longer 'translating' — skipping parking.")
                return
            _set_step_success(
                cursor, job_id, 3,
                message=f"Translated to English ({len(translated):,} chars)",
                output_files=[translated_path],
            )
        print(f"⏸  AI Transcribe {job_id} parked at awaiting_translate_review")
    except Exception as exc:
        err = str(exc)
        print(f"❌ AI Transcribe {job_id} translate failed: {err}")
        import traceback
        traceback.print_exc()
        with get_db_cursor(commit=True) as cursor:
            _fail_job(cursor, job_id, 3, err)
        _mp_linkback_failed(job_id, err)


# -----------------------------------------------------------------------------
# Stage 4 — Extract Pradip Halder analysis (background).
# -----------------------------------------------------------------------------

def run_extract_step(job_id, translated_text, job_folder):
    """Background Step 4 worker: extract Pradip Halder's stock analyses.
    On success → status='awaiting_extract_review'."""
    try:
        from backend.pipeline.live_transcribe.extract_pradip_analysis import run as extract_run

        with get_db_cursor(commit=True) as cursor:
            _set_step_running(cursor, job_id, 4)
            _update_job(cursor, job_id, current_step=4, status="extracting", progress=70)

        print(f"\n{'='*60}\nAI Transcribe job {job_id} — Step 4: Extract Pradip's Analysis\n{'='*60}")
        result = extract_run(translated_text)

        if not result.get("success"):
            err = result.get("error") or "Unknown extract error"
            with get_db_cursor(commit=True) as cursor:
                _fail_job(cursor, job_id, 4, err)
            _mp_linkback_failed(job_id, err)
            print(f"❌ AI Transcribe {job_id} extract failed: {err}")
            return

        extracted = result["arranged_text"]

        extracted_path = os.path.join(job_folder, "transcripts", "extracted_analysis.txt")
        _ensure_dir(os.path.dirname(extracted_path))
        with open(extracted_path, "w", encoding="utf-8") as f:
            f.write(extracted)

        with get_db_cursor(commit=True) as cursor:
            rows = _update_job(
                cursor, job_id,
                current_step=4, progress=85,
                status="awaiting_extract_review",
                payload_patch={
                    "extracted_text": extracted,
                    "extracted_file": extracted_path,
                    "translated_text": translated_text,
                },
                expect_status="extracting",
            )
            if rows == 0:
                print(f"⚠  AI Transcribe {job_id} extract finished but status was no longer 'extracting' — skipping parking.")
                return
            _set_step_success(
                cursor, job_id, 4,
                message=f"Extracted Pradip's analysis ({len(extracted):,} chars)",
                output_files=[extracted_path],
            )
        print(f"⏸  AI Transcribe {job_id} parked at awaiting_extract_review")
    except Exception as exc:
        err = str(exc)
        print(f"❌ AI Transcribe {job_id} extract crashed: {err}")
        import traceback
        traceback.print_exc()
        with get_db_cursor(commit=True) as cursor:
            _fail_job(cursor, job_id, 4, err)
        _mp_linkback_failed(job_id, err)


# -----------------------------------------------------------------------------
# Stage 5 — Spawn Bulk Rationale child job, inheriting channel/date/time.
# -----------------------------------------------------------------------------

def spawn_bulk_from_extracted(job_id, user_id, extracted_text,
                              channel_id, call_date, call_time, title,
                              youtube_url=""):
    """Create + kick off a Bulk Rationale child job. Marks the AI Transcribe
    parent's Step 5 success, status='bulk_started', and stamps bulk_job_id
    onto its payload."""
    from backend.api.bulk_rationale import run_bulk_pipeline, BULK_STEPS
    from backend.api.activity_logs import create_activity_log

    bulk_job_id = f"bulk-{uuid.uuid4().hex[:8]}"
    bulk_folder = f"backend/job_files/{bulk_job_id}"
    os.makedirs(bulk_folder, exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, "analysis"), exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, "charts"), exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, "pdf"), exist_ok=True)

    with open(os.path.join(bulk_folder, "bulk-input.txt"), "w", encoding="utf-8") as f:
        f.write(extracted_text)

    bulk_title = title or bulk_job_id

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO jobs (id, youtube_url, title, channel_id, date, time,
                              user_id, tool_used, status, progress, current_step,
                              folder_path, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                bulk_job_id, youtube_url or "", bulk_title, channel_id, call_date, call_time,
                user_id, "Bulk Rationale", "processing", 0, 0, bulk_folder,
                datetime.now(), datetime.now(),
            ),
        )
        for step in BULK_STEPS:
            cursor.execute(
                "INSERT INTO job_steps (job_id, step_number, step_name, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (bulk_job_id, step["step_number"], step["name"], "pending", datetime.now()),
            )

        # Stamp Step 5 success on the parent and mark it bulk_started.
        _set_step_success(
            cursor, job_id, 5,
            message=f"Spawned Bulk Rationale {bulk_job_id}",
            output_files=[],
        )
        _update_job(
            cursor, job_id,
            current_step=5, progress=100,
            status="bulk_started",
            payload_patch={"bulk_job_id": bulk_job_id, "extracted_text": extracted_text},
        )

        try:
            create_activity_log(
                user_id, "job_started",
                f"AI Transcribe → Bulk Rationale: {bulk_title}",
                bulk_job_id, "Bulk Rationale",
            )
        except Exception:
            pass

    t = threading.Thread(
        target=run_bulk_pipeline,
        args=(bulk_job_id, bulk_folder, call_date, call_time),
        daemon=True,
    )
    t.start()
    print(f"✅ AI Transcribe {job_id}: spawned Bulk Rationale {bulk_job_id}")
    return bulk_job_id


# -----------------------------------------------------------------------------
# Compatibility helper used by api/ai_transcribe.py for the download endpoint.
# -----------------------------------------------------------------------------

def load_job_transcript(job_folder):
    """Return the (text, path) for the AssemblyAI transcript .txt, or
    (None, None) if not present yet."""
    txt_path = os.path.join(job_folder, "transcripts", "transcript.txt")
    if os.path.exists(txt_path):
        try:
            return _read_transcript_text(txt_path), txt_path
        except Exception:
            return None, txt_path
    return None, None
