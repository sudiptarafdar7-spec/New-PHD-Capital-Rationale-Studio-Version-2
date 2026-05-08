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
    TOTAL_STEPS,
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

        # Normalise /live/, /shorts/, etc. → canonical watch?v=<id>
        # before metadata lookup; the upstream extractor 404s on the
        # /live/ form for finished streams.
        from backend.utils.youtube import normalize_youtube_url
        url = normalize_youtube_url(url)

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
            # Convert /live/, /shorts/, /embed/, youtu.be/ → canonical
            # watch?v=<id> so both yt-dlp and the RapidAPI fallback see
            # a URL shape they can actually download.
            from backend.utils.youtube import normalize_youtube_url
            youtube_url = normalize_youtube_url(youtube_url)
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


@ai_transcribe_bp.route("/jobs/<job_id>/restart-step/<int:step_number>", methods=["POST"])
@jwt_required()
def restart_step(job_id, step_number):
    """Re-run any AI Transcribe step from scratch.

    • Steps 1 or 2 → re-download + re-transcribe (the pair always run together).
    • Step 3 → re-translate using payload.transcript_text.
    • Step 4 → re-extract using payload.translated_text.
    • Step 5 → re-spawn Bulk Rationale child using payload.extracted_text.

    Mirrors the Bulk Rationale /restart-step pattern: resets all steps from
    the chosen step onward to 'pending', flips the parent job back to a
    running status, and kicks off the matching background worker thread.
    """
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if step_number < 1 or step_number > TOTAL_STEPS:
        return jsonify({"error": f"step_number must be 1..{TOTAL_STEPS}"}), 400

    payload = _payload_dict(job)
    folder = job.get("folder_path") or f"backend/job_files/{job_id}"

    # Validate prerequisites for steps that consume earlier outputs.
    transcript_text = (payload.get("transcript_text") or "").strip()
    translated_text = (payload.get("translated_text") or "").strip()
    extracted_text  = (payload.get("extracted_text")  or "").strip()

    if step_number == 3 and not transcript_text:
        return jsonify({"error": "Cannot restart Translate — no reviewed transcript yet."}), 400
    if step_number == 4 and not translated_text:
        return jsonify({"error": "Cannot restart Extract — no reviewed translation yet."}), 400
    if step_number == 5 and not extracted_text:
        return jsonify({"error": "Cannot restart Send-to-Bulk — no extracted text yet."}), 400
    if step_number == 5 and (not job.get("channel_id") or not job.get("date")):
        return jsonify({
            "error": "Channel and date are required to spawn a Bulk Rationale job.",
        }), 400

    # Choose the running status the parent should sit in while the chosen
    # step (or its pair) executes.
    new_status = {
        1: "processing",
        2: "processing",
        3: "translating",
        4: "extracting",
        5: "bulk_started",
    }[step_number]

    # Reset every step from `step_number` onward to pending so the dashboard
    # progress UI re-animates them. Bump the parent back to current_step-1
    # so the running step shows as in-flight (matching Bulk's contract).
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """UPDATE job_steps
               SET status='pending', message=NULL, started_at=NULL, ended_at=NULL,
                   output_files='{}'
               WHERE job_id=%s AND step_number >= %s""",
            (job_id, step_number),
        )
        cursor.execute(
            """UPDATE jobs
               SET status=%s, current_step=%s, progress=%s, updated_at=%s
               WHERE id=%s""",
            (new_status, max(step_number - 1, 0),
             int(((step_number - 1) / TOTAL_STEPS) * 100),
             datetime.now(), job_id),
        )

    # Dispatch the right background worker.
    if step_number in (1, 2):
        # Re-build source kwargs from the parent job row.
        source = {}
        if job.get("youtube_url"):
            source["youtube_url"] = job["youtube_url"]
        else:
            existing = os.path.join(folder, "audio", "audio_16k_mono.wav")
            if os.path.exists(existing):
                source["local_audio_path"] = existing
            else:
                return jsonify({
                    "error": "No YouTube URL or local audio found to re-download from.",
                }), 400
        lang = payload.get("language_code") or "hi"
        threading.Thread(
            target=run_ai_transcribe_pipeline,
            args=(job_id, folder, source, lang),
            daemon=True,
        ).start()
    elif step_number == 3:
        threading.Thread(
            target=run_translate_step,
            args=(job_id, transcript_text, folder),
            daemon=True,
        ).start()
    elif step_number == 4:
        threading.Thread(
            target=run_extract_step,
            args=(job_id, translated_text, folder),
            daemon=True,
        ).start()
    elif step_number == 5:
        from backend.services.ai_transcribe_service import spawn_bulk_from_extracted
        channel_id = job["channel_id"]
        call_date  = job["date"]
        call_time  = job.get("time") or "00:00:00"
        title      = job.get("title") or job_id
        youtube_url = job.get("youtube_url") or ""
        def _safe_respawn():
            try:
                spawn_bulk_from_extracted(
                    job_id, user_id, extracted_text,
                    channel_id, call_date, call_time, title,
                    youtube_url=youtube_url,
                )
            except Exception as spawn_err:
                print(f"❌ AI Transcribe {job_id} re-spawn failed: {spawn_err}")
                with get_db_cursor(commit=True) as c:
                    c.execute(
                        """UPDATE jobs SET status='awaiting_extract_review',
                           updated_at=%s WHERE id=%s""",
                        (datetime.now(), job_id),
                    )
        threading.Thread(target=_safe_respawn, daemon=True).start()

    return jsonify({
        "success": True,
        "message": f"Restarting from step {step_number}",
    }), 202


@ai_transcribe_bp.route("/jobs/<job_id>/upload-audio", methods=["POST"])
@jwt_required()
def upload_audio(job_id):
    """Manual audio fallback for AI Transcribe.

    Used when Step 1 (download audio) failed because both yt-dlp and the
    RapidAPI fallback couldn't pull the YouTube file (age-gated video,
    cookies expired, region block, etc.). The user picks an audio file
    from their computer; we save it under the job folder, reset every
    pipeline step back to pending, flip the parent job back to
    'processing', and re-spawn ``run_ai_transcribe_pipeline`` with a
    ``local_audio_path`` source so step 1 skips YouTube entirely and
    just normalises the uploaded file via ffmpeg.

    Mirrors the Voice Typing /upload-audio pattern.
    """
    user_id = get_jwt_identity()
    job, err = _check_job_access(job_id, user_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (multipart field 'file' required)"}), 400

    audio_file = request.files["file"]
    if not audio_file.filename:
        return jsonify({"error": "Empty audio upload"}), 400

    # ---- Server-side validation (parity with Voice Typing fallback) -----
    ALLOWED_EXTS = {
        ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".webm",
        ".mp4", ".aac", ".flac", ".wma",
    }
    MAX_BYTES = 500 * 1024 * 1024  # 500 MB

    ext = os.path.splitext(audio_file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({
            "error": f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTS))}",
        }), 400

    # Best-effort content-length check before saving (Werkzeug streams the
    # body, so the post-save fallback below is the authoritative limit).
    try:
        content_length = int(request.content_length or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length and content_length > MAX_BYTES:
        return jsonify({"error": f"File too large (max {MAX_BYTES // (1024*1024)} MB)"}), 413

    # ---- Gate: only allow when step 1 actually failed -------------------
    # Race-safety: confirm the parent job is in 'failed' state AND step 1
    # is the failed step before we touch anything. This blocks accidental
    # double-uploads, restart-step collisions, and uploads against jobs
    # that failed at later stages (translate/extract) where re-running
    # download wouldn't help.
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT status FROM jobs WHERE id = %s",
            (job_id,),
        )
        cur = cursor.fetchone()
        if not cur or cur.get("status") != "failed":
            return jsonify({
                "error": "Manual audio upload is only available after the job has failed.",
            }), 409
        cursor.execute(
            """SELECT status FROM job_steps
               WHERE job_id = %s AND step_number = 1""",
            (job_id,),
        )
        step1 = cursor.fetchone()
        if not step1 or step1.get("status") != "failed":
            return jsonify({
                "error": "Manual audio upload only applies when Step 1 (Download Audio) failed.",
            }), 409

    folder = job.get("folder_path") or os.path.join("backend", "job_files", job_id)
    upload_dir = _ensure_dir(os.path.join(folder, "upload"))
    safe_name = secure_filename(audio_file.filename) or "upload.wav"
    local_path = os.path.join(upload_dir, safe_name)
    try:
        audio_file.save(local_path)
    except Exception as save_err:
        return jsonify({"error": f"Failed to save upload: {save_err}"}), 500

    # Authoritative size check now that the file is on disk.
    try:
        actual_size = os.path.getsize(local_path)
    except OSError:
        actual_size = 0
    if actual_size > MAX_BYTES:
        try:
            os.remove(local_path)
        except OSError:
            pass
        return jsonify({"error": f"File too large (max {MAX_BYTES // (1024*1024)} MB)"}), 413

    payload = _payload_dict(job)
    lang = payload.get("language_code") or "hi"

    # Atomic state transition: only flip the parent if it's STILL failed.
    # If a competing /restart-step or /upload-audio request beat us to it,
    # bail out without resetting steps or spawning a duplicate worker.
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """UPDATE jobs
               SET status='processing', current_step=0, progress=0,
                   payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                   updated_at=%s
               WHERE id=%s AND status='failed'""",
            (json.dumps({"uploaded_audio_path": local_path,
                         "uploaded_audio_name": safe_name}),
             datetime.now(), job_id),
        )
        if cursor.rowcount == 0:
            return jsonify({
                "error": "Another restart is already in flight. Refresh and try again.",
            }), 409
        # We won the transition — safe to reset step rows now.
        cursor.execute(
            """UPDATE job_steps
               SET status='pending', message=NULL, started_at=NULL, ended_at=NULL,
                   output_files='{}'
               WHERE job_id=%s""",
            (job_id,),
        )

    # Mirror the restart back onto the linked Media Presence row (if any)
    # so its Transcribe pill leaves 'failed' and shows live progress.
    try:
        from backend.services.ai_transcribe_service import _mp_linkback_stage
        _mp_linkback_stage(job_id, "processing")
    except Exception as link_err:
        print(f"⚠️  AI Transcribe {job_id}: MP restart linkback skipped: {link_err}")

    source = {"local_audio_path": local_path}
    threading.Thread(
        target=run_ai_transcribe_pipeline,
        args=(job_id, folder, source, lang),
        daemon=True,
    ).start()

    return jsonify({
        "success": True,
        "message": "Audio uploaded — AI Transcribe pipeline restarting.",
        "uploadedAudioName": safe_name,
    }), 200


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
