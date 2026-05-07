"""
AI Transcribe API — 5-stage review pipeline.

Endpoints:
  • POST   /api/v1/ai-transcribe/fetch-metadata           — prefill from YT URL
  • POST   /api/v1/ai-transcribe/create-job               — create + kick off pipeline
  • GET    /api/v1/ai-transcribe/jobs/<job_id>            — full job + step status
  • POST   /api/v1/ai-transcribe/jobs/<id>/save-transcript-and-translate
  • POST   /api/v1/ai-transcribe/jobs/<id>/save-translation-and-extract
  • POST   /api/v1/ai-transcribe/jobs/<id>/save-extracted   — save edits only
  • POST   /api/v1/ai-transcribe/jobs/<id>/send-to-bulk    — spawn Bulk Rationale child
  • GET    /api/v1/ai-transcribe/jobs/<id>/transcript      — download .txt
  • DELETE /api/v1/ai-transcribe/jobs/<id>                 — delete a job
"""

import os
import json
import uuid
import threading
from datetime import datetime, date as _date_cls

from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from backend.api import ai_transcribe_bp
from backend.utils.database import get_db_cursor
from backend.api.activity_logs import create_activity_log
from backend.utils.job_title import build_job_title
from backend.services.ai_transcribe_service import (
    AI_TRANSCRIBE_STEPS,
    run_ai_transcribe_pipeline,
    run_translate_step,
    run_extract_step,
    spawn_bulk_from_extracted,
    load_job_transcript,
)


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


def _check_job_access(job_id, user_id):
    """Look up an AI Transcribe job and enforce scope + ownership."""
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT id, user_id, folder_path, status, title, youtube_url, tool_used, "
            "current_step, progress, channel_id, date, time, payload, "
            "created_at, updated_at "
            "FROM jobs WHERE id = %s",
            (job_id,),
        )
        job = cursor.fetchone()
        if not job:
            return None, ("Job not found", 404)

        if (job.get("tool_used") or "").lower() != "ai transcribe" \
                and not str(job["id"]).startswith("aitr-"):
            return None, ("Job not found", 404)

        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        urow = cursor.fetchone()
        is_admin = bool(urow and urow.get("role") == "admin")
        if str(job["user_id"]) != str(user_id) and not is_admin:
            return None, ("Forbidden", 403)
        return dict(job), None


# ---------------------------------------------------------------------------
# Step 0 — fetch YouTube metadata (mirror of Live Transcribe's helper).
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/fetch-metadata", methods=["POST"])
@jwt_required()
def fetch_metadata():
    try:
        data = request.get_json(silent=True) or {}
        url = (data.get("youtubeUrl") or data.get("youtube_url") or "").strip()
        if not url:
            return jsonify({"error": "youtubeUrl is required"}), 400

        from backend.pipeline.fetch_video_data import fetch_video_metadata
        meta = fetch_video_metadata(url)

        return jsonify({
            "success": True,
            "data": {
                "videoId": meta.get("video_id"),
                "title": meta.get("title"),
                "channelName": meta.get("channel_name"),
                "uploadDate": meta.get("date"),
                "uploadTime": meta.get("time"),
                "duration": meta.get("duration"),
                "thumbnail": meta.get("thumbnail"),
            },
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Create job (Step 1+2 fire automatically).
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/create-job", methods=["POST"])
@jwt_required()
def create_job():
    """Create a new AI Transcribe job.

    Accepts JSON { youtube_url, language_code?, title?, channel_id?, date?, time? }
    or multipart with 'audio' file + the same fields as form data.
    """
    user_id = get_jwt_identity()
    language_code = "hi"
    title = None
    youtube_url = ""
    channel_id = None
    call_date = None
    call_time = None
    media_presence_id = None
    source = {}

    try:
        job_id = f"aitr-{uuid.uuid4().hex[:8]}"
        job_folder = os.path.join("backend", "job_files", job_id)
        _ensure_dir(job_folder)

        # ---- parse common fields (work for both multipart and JSON) ------
        if "audio" in request.files:
            audio_file = request.files["audio"]
            if not audio_file.filename:
                return jsonify({"error": "Empty audio upload"}), 400
            upload_dir = _ensure_dir(os.path.join(job_folder, "upload"))
            safe_name = secure_filename(audio_file.filename) or "upload.wav"
            local_path = os.path.join(upload_dir, safe_name)
            audio_file.save(local_path)
            source = {"local_audio_path": local_path}
            language_code = (request.form.get("language_code") or language_code).strip()
            title = (request.form.get("title") or "").strip() or None
            channel_id = request.form.get("channel_id") or None
            call_date = request.form.get("date") or None
            call_time = request.form.get("time") or None
            media_presence_id = request.form.get("media_presence_id") or None
        else:
            body = request.get_json(silent=True) or {}
            youtube_url = (body.get("youtube_url") or "").strip()
            if not youtube_url:
                return jsonify({"error": "youtube_url or audio file is required"}), 400
            source = {"youtube_url": youtube_url}
            language_code = (body.get("language_code") or language_code).strip()
            title = (body.get("title") or "").strip() or None
            channel_id = body.get("channel_id") or None
            call_date = body.get("date") or None
            call_time = body.get("time") or None
            media_presence_id = body.get("media_presence_id") or None

        if channel_id in ("", "null", "None"):
            channel_id = None
        try:
            media_presence_id = int(media_presence_id) if media_presence_id not in (None, "", "null", "None") else None
        except (TypeError, ValueError):
            media_presence_id = None
        try:
            channel_id = int(channel_id) if channel_id is not None else None
        except (TypeError, ValueError):
            channel_id = None

        # ---- build the unified job title if we have channel/date/time ----
        platform_str, channel_name = "", ""
        if channel_id:
            with get_db_cursor() as cursor:
                cursor.execute(
                    "SELECT platform, channel_name FROM channels WHERE id = %s",
                    (channel_id,),
                )
                ch = cursor.fetchone()
                if ch:
                    platform_str = ch.get("platform") or ""
                    channel_name = ch.get("channel_name") or ""

        if not title:
            if channel_id and call_date:
                title = build_job_title(
                    platform_str, channel_name, call_date, call_time or "00:00",
                )
            elif youtube_url:
                title = f"YouTube · {youtube_url[:80]}"
            else:
                title = f"AI Transcribe · {job_id}"

        # ---- insert parent job + step rows ------------------------------
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO jobs (id, youtube_url, title, user_id, tool_used,
                                  status, progress, current_step, folder_path,
                                  channel_id, date, time, payload,
                                  created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    job_id, youtube_url, title, user_id, "AI Transcribe",
                    "processing", 0, 0, job_folder,
                    channel_id, call_date, call_time,
                    json.dumps({
                        "language_code": language_code,
                        **({"media_presence_id": media_presence_id} if media_presence_id else {}),
                    }),
                    datetime.now(), datetime.now(),
                ),
            )

            # If this AI Transcribe job was spawned from a Media Presence row,
            # link both directions: stamp transcribe_status='started' on the MP
            # row and store the new aitr- id in linked_transcribe_job_id so the
            # MP table's Transcribe pill becomes a clickable shortcut into the
            # job's review page (mirrors voice/live behaviour).
            if media_presence_id:
                cursor.execute(
                    """
                    UPDATE media_presence
                    SET transcribe_method = 'ai_transcribe',
                        transcribe_status = 'started',
                        linked_transcribe_job_id = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (job_id, datetime.now(), media_presence_id),
                )

            for step in AI_TRANSCRIBE_STEPS:
                cursor.execute(
                    """INSERT INTO job_steps (job_id, step_number, step_name, status, created_at)
                       VALUES (%s, %s, %s, 'pending', %s)""",
                    (job_id, step["step_number"], step["name"], datetime.now()),
                )

            try:
                create_activity_log(
                    user_id, "job_started",
                    f"Started AI Transcribe: {title}", job_id, "AI Transcribe",
                )
            except Exception:
                pass

        thread = threading.Thread(
            target=run_ai_transcribe_pipeline,
            args=(job_id, job_folder, source, language_code),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "jobId": job_id,
            "title": title,
            "message": "AI Transcribe job started",
        }), 200

    except Exception as exc:
        print(f"Error creating AI Transcribe job: {exc}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Get job (poll target).
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/list", methods=["GET"])
@jwt_required()
def list_jobs():
    """Return every AI Transcribe job belonging to the calling user (admins
    see all). Joins the spawned Bulk Rationale child so the list view can
    surface its status inline.
    """
    user_id = get_jwt_identity()
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            urow = cursor.fetchone()
            is_admin = bool(urow and urow.get("role") == "admin")

            scope_sql = "" if is_admin else "AND j.user_id = %s"
            params = [user_id] if not is_admin else []
            # ``user_id`` is also passed for the admin branch so the SQL
            # placeholder count matches; we always pass at least one param.
            cursor.execute(
                f"""
                SELECT j.id, j.title, j.status, j.progress, j.current_step,
                       j.youtube_url, j.channel_id, j.date, j.time,
                       j.created_at, j.updated_at, j.payload,
                       c.channel_name, c.platform,
                       bj.status   AS bulk_status,
                       bj.progress AS bulk_progress
                FROM jobs j
                LEFT JOIN channels c ON c.id = j.channel_id
                LEFT JOIN jobs bj
                       ON bj.id = (j.payload->>'bulk_job_id')
                      AND bj.tool_used = 'Bulk Rationale'
                WHERE (j.tool_used = 'AI Transcribe' OR j.id LIKE 'aitr-%%')
                  {scope_sql}
                ORDER BY j.created_at DESC
                LIMIT 200
                """,
                tuple(params),
            )
            rows = cursor.fetchall()

        out = []
        for r in rows:
            payload = _payload_dict(r)
            out.append({
                "jobId": r["id"],
                "title": r["title"],
                "status": r["status"],
                "progress": r["progress"],
                "currentStep": r["current_step"],
                "youtubeUrl": r["youtube_url"],
                "channelId": r.get("channel_id"),
                "channelName": r.get("channel_name"),
                "platform": r.get("platform"),
                "date": r["date"].isoformat() if isinstance(r.get("date"), _date_cls) else (str(r["date"]) if r.get("date") else None),
                "time": str(r["time"]) if r.get("time") else None,
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
                "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
                "bulkJobId": payload.get("bulk_job_id"),
                "bulkJobStatus": r.get("bulk_status"),
                "bulkJobProgress": r.get("bulk_progress"),
            })
        return jsonify({"success": True, "jobs": out}), 200
    except Exception as exc:
        print(f"ai_transcribe list_jobs error: {exc}")
        return jsonify({"error": str(exc)}), 500


@ai_transcribe_bp.route("/jobs/<job_id>", methods=["GET"])
@jwt_required()
def get_job(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    with get_db_cursor() as cursor:
        cursor.execute(
            """SELECT step_number, step_name, status, message, output_files,
                      started_at, ended_at
               FROM job_steps WHERE job_id = %s ORDER BY step_number""",
            (job_id,),
        )
        steps = cursor.fetchall()

        channel_name = None
        if job.get("channel_id"):
            cursor.execute(
                "SELECT channel_name, platform FROM channels WHERE id = %s",
                (job["channel_id"],),
            )
            ch = cursor.fetchone()
            if ch:
                channel_name = ch.get("channel_name")

    payload = _payload_dict(job)

    # Backwards compat: legacy 3-step jobs may have only stored the file.
    transcript_text = payload.get("transcript_text")
    if not transcript_text and job["status"] == "completed":
        transcript_text, _ = load_job_transcript(job["folder_path"])

    total_steps = len(steps) if steps else len(AI_TRANSCRIBE_STEPS)

    def _fmt_d(v):
        if v is None:
            return None
        if isinstance(v, _date_cls):
            return v.isoformat()
        return str(v)

    return jsonify({
        "jobId": job["id"],
        "title": job["title"],
        "status": job["status"],
        "progress": job["progress"],
        "currentStep": job["current_step"],
        "totalSteps": total_steps,
        "youtubeUrl": job["youtube_url"],
        "channelId": job.get("channel_id"),
        "channelName": channel_name,
        "date": _fmt_d(job.get("date")),
        "time": _fmt_d(job.get("time")),
        "createdAt": job["created_at"].isoformat() if job["created_at"] else None,
        "updatedAt": job["updated_at"].isoformat() if job["updated_at"] else None,
        "transcriptText": transcript_text,
        "translatedText": payload.get("translated_text"),
        "extractedText": payload.get("extracted_text"),
        "bulkJobId": payload.get("bulk_job_id"),
        "languageCode": payload.get("language_code"),
        "transcriptFile": payload.get("transcript_file"),
        "steps": [
            {
                "step_number": s["step_number"],
                "step_name": s["step_name"],
                "status": s["status"],
                "message": s.get("message"),
                "output_files": s.get("output_files") or [],
                "started_at": s["started_at"].isoformat() if s.get("started_at") else None,
                "ended_at": s["ended_at"].isoformat() if s.get("ended_at") else None,
            }
            for s in steps
        ],
        "stepDefinitions": AI_TRANSCRIBE_STEPS,
    }), 200


# ---------------------------------------------------------------------------
# Step 3 trigger — save edited transcript, kick off background translate.
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/jobs/<job_id>/save-transcript-and-translate", methods=["POST"])
@jwt_required()
def save_transcript_and_translate(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if job["status"] != "awaiting_review":
        return jsonify({
            "error": f"Translate is only allowed after transcription review (current status: {job['status']})."
        }), 409

    data = request.get_json(silent=True) or {}
    text = (data.get("transcriptText") or "").strip()
    if not text:
        return jsonify({"error": "Transcript text is empty"}), 400

    with get_db_cursor(commit=True) as cursor:
        # Atomic transition guards against double-click.
        cursor.execute(
            """UPDATE jobs
               SET status='translating',
                   payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                   updated_at=%s
               WHERE id=%s AND status='awaiting_review'
               RETURNING id""",
            (json.dumps({"transcript_text": text}), datetime.now(), job_id),
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Job is no longer in awaiting_review state"}), 409

    threading.Thread(
        target=run_translate_step,
        args=(job_id, text, job["folder_path"]),
        daemon=True,
    ).start()

    return jsonify({"success": True, "message": "Translating…"}), 202


# ---------------------------------------------------------------------------
# Step 4 trigger — save edited translation, kick off background extract.
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/jobs/<job_id>/save-translation-and-extract", methods=["POST"])
@jwt_required()
def save_translation_and_extract(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if job["status"] != "awaiting_translate_review":
        return jsonify({
            "error": f"Extract is only allowed after translation review (current status: {job['status']})."
        }), 409

    data = request.get_json(silent=True) or {}
    text = (data.get("translatedText") or "").strip()
    if not text:
        return jsonify({"error": "Translated text is empty"}), 400

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """UPDATE jobs
               SET status='extracting',
                   payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                   updated_at=%s
               WHERE id=%s AND status='awaiting_translate_review'
               RETURNING id""",
            (json.dumps({"translated_text": text}), datetime.now(), job_id),
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Job is no longer in awaiting_translate_review state"}), 409

    threading.Thread(
        target=run_extract_step,
        args=(job_id, text, job["folder_path"]),
        daemon=True,
    ).start()

    return jsonify({"success": True, "message": "Extracting Pradip's analysis…"}), 202


# ---------------------------------------------------------------------------
# Save extracted edits only (without sending to Bulk yet).
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/jobs/<job_id>/save-extracted", methods=["POST"])
@jwt_required()
def save_extracted(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]
    if job["status"] != "awaiting_extract_review":
        return jsonify({
            "error": f"Edits only allowed during extract review (current status: {job['status']})."
        }), 409

    data = request.get_json(silent=True) or {}
    text = (data.get("extractedText") or "").strip()
    if not text:
        return jsonify({"error": "Extracted text is empty"}), 400

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """UPDATE jobs
               SET payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                   updated_at=%s
               WHERE id=%s""",
            (json.dumps({"extracted_text": text}), datetime.now(), job_id),
        )
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Step 5 — spawn Bulk Rationale child.
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/jobs/<job_id>/send-to-bulk", methods=["POST"])
@jwt_required()
def send_to_bulk(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if job["status"] in ("bulk_started", "completed"):
        return jsonify({"error": f"Already {job['status']}"}), 409
    if job["status"] != "awaiting_extract_review":
        return jsonify({
            "error": f"Send to Bulk is only allowed after extract review (current status: {job['status']})."
        }), 409
    if not job.get("channel_id") or not job.get("date"):
        return jsonify({
            "error": "Channel and date are required to spawn a Bulk Rationale job. "
                     "Please re-create the job with those fields filled in."
        }), 400

    data = request.get_json(silent=True) or {}
    payload = _payload_dict(job)
    edited = (data.get("extractedText") if data.get("extractedText") is not None
              else payload.get("extracted_text", ""))
    edited = (edited or "").strip()
    if not edited:
        return jsonify({"error": "Extracted text is empty"}), 400

    # Atomic transition.
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """UPDATE jobs
               SET status='bulk_started',
                   payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                   updated_at=%s
               WHERE id=%s AND status='awaiting_extract_review'
               RETURNING id""",
            (json.dumps({"extracted_text": edited}), datetime.now(), job_id),
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Send already in progress for this job"}), 409

        channel_id = job["channel_id"]
        call_date = job["date"]
        call_time = job["time"] or "00:00:00"
        title = job.get("title") or job_id
        youtube_url = job.get("youtube_url") or ""

    def _safe_spawn():
        try:
            spawn_bulk_from_extracted(
                job_id, user_id, edited, channel_id, call_date, call_time, title,
                youtube_url=youtube_url,
            )
            # MP linkback: mark the source Media Presence row's transcribe
            # phase as completed (transcript review + send finished) so the
            # MP table can advance to its rationale-pending state. Mirrors
            # voice_typing/live_transcribe behaviour.
            try:
                mp_id = (payload or {}).get("media_presence_id")
                if mp_id:
                    with get_db_cursor(commit=True) as c3:
                        c3.execute(
                            """UPDATE media_presence
                               SET transcribe_status = 'completed',
                                   transcript_text = %s,
                                   updated_at = %s
                               WHERE id = %s""",
                            (edited, datetime.now(), mp_id),
                        )
            except Exception as mp_err:
                print(f"⚠️  AI Transcribe {job_id}: MP linkback skipped: {mp_err}")
        except Exception as spawn_err:
            print(f"❌ AI Transcribe {job_id} bulk spawn failed: {spawn_err}")
            import traceback; traceback.print_exc()
            try:
                err_msg = str(spawn_err)[:1000]
                with get_db_cursor(commit=True) as c2:
                    c2.execute(
                        """UPDATE jobs
                           SET status='awaiting_extract_review',
                               payload = COALESCE(payload, '{}'::jsonb)
                                         || jsonb_build_object('spawn_error', %s),
                               updated_at=%s
                           WHERE id=%s AND status='bulk_started'""",
                        (f"Bulk Rationale spawn failed: {err_msg}", datetime.now(), job_id),
                    )
            except Exception as roll_err:
                print(f"❌ AI Transcribe {job_id} could not roll back: {roll_err}")

    threading.Thread(target=_safe_spawn, daemon=True).start()
    return jsonify({"success": True, "message": "Spawning Bulk Rationale child job…"}), 202


# ---------------------------------------------------------------------------
# Download / delete (unchanged).
# ---------------------------------------------------------------------------

@ai_transcribe_bp.route("/jobs/<job_id>/transcript", methods=["GET"])
@jwt_required()
def download_transcript(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    _, txt_path = load_job_transcript(job["folder_path"])
    if not txt_path or not os.path.exists(txt_path):
        return jsonify({"error": "Transcript not available yet"}), 404
    return send_file(
        txt_path, as_attachment=True,
        download_name=f"transcript-{job_id}.txt",
        mimetype="text/plain; charset=utf-8",
    )


@ai_transcribe_bp.route("/jobs/<job_id>", methods=["DELETE"])
@jwt_required()
def delete_job(job_id):
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if job.get("status") in ("processing", "translating", "extracting"):
        return jsonify({
            "error": "Job is still running. Wait for it to finish or fail before deleting.",
        }), 409

    folder = job.get("folder_path")
    with get_db_cursor(commit=True) as cursor:
        cursor.execute("DELETE FROM jobs WHERE id = %s", (job_id,))

    if folder and os.path.isdir(folder):
        try:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        except Exception as exc:
            print(f"[ai_transcribe] failed to remove folder {folder}: {exc}")

    # Detach any Media Presence row that linked to this transcribe job so its
    # Voice/AI buttons reappear.
    try:
        from backend.api.media_presence import unlink_deleted_job
        unlink_deleted_job(job_id)
    except Exception as _mp_err:
        print(f"[ai_transcribe.delete_job] MP unlink failed: {_mp_err}")

    return jsonify({"success": True, "message": "Job deleted"}), 200
