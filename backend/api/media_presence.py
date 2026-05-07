"""
Media Presence API
Endpoints for the daily TV/YouTube media-event tracker that orchestrates
voice typing, AI transcribe and auto (Media Rationale) workflows.
"""

import os
import threading
import uuid
from datetime import datetime

from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from backend.api import media_presence_bp
from backend.utils.database import get_db_cursor
from backend.api.activity_logs import create_activity_log
from backend.models.media_presence import MediaPresence
from backend.services.ai_transcribe_service import (
    transcribe_media_presence,
    TRANSCRIPT_ROOT,
)


# ---------- Authorization ----------------------------------------------------

def _is_admin(user_id):
    """Return True if the user has the admin role."""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            return bool(row and row.get("role") == "admin")
    except Exception:
        return False


def _authorize_entry(media_id, user_id):
    """Fetch an entry and confirm the requester may act on it.
    Returns (entry, error_response_tuple_or_None)."""
    entry = MediaPresence.get(media_id)
    if not entry:
        return None, (jsonify({"error": "Not found"}), 404)
    if not _is_admin(user_id) and str(entry.get("created_by")) != str(user_id):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return entry, None


# ---------- Helpers ----------------------------------------------------------

def _channel_for(channel_id):
    if not channel_id:
        return None
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT id, channel_name, platform FROM channels WHERE id = %s",
            (channel_id,),
        )
        return cursor.fetchone()


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


# ---------- Auto-trigger of downstream rationale jobs ------------------------

# Status values that mean the underlying job has produced a final PDF
_DONE_STATUSES = {"pdf_ready", "completed", "signed"}
_FAILED_STATUSES = {"failed"}


def _create_bulk_rationale_job(media_row, transcript_text, user_id):
    """Insert a Bulk Rationale job and start its pipeline thread."""
    from backend.api.bulk_rationale import BULK_STEPS, run_bulk_pipeline

    job_id = f"bulk-{uuid.uuid4().hex[:8]}"
    channel = _channel_for(media_row.get("channel_id"))
    channel_name = channel["channel_name"] if channel else (media_row.get("platform") or "media")
    platform = channel["platform"] if channel else (media_row.get("platform") or "")
    from backend.utils.job_title import build_job_title
    title = build_job_title(platform, channel_name, media_row['event_date'], media_row.get('event_time'))

    job_folder = f"backend/job_files/{job_id}"
    _ensure_dir(job_folder)
    _ensure_dir(os.path.join(job_folder, "analysis"))
    _ensure_dir(os.path.join(job_folder, "charts"))
    _ensure_dir(os.path.join(job_folder, "pdf"))

    with open(os.path.join(job_folder, "bulk-input.txt"), "w", encoding="utf-8") as f:
        f.write(transcript_text or "")

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO jobs (id, youtube_url, title, channel_id, date, time,
                              user_id, tool_used, status, progress, current_step, folder_path,
                              created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id, media_row.get("video_url") or "", title, media_row.get("channel_id"),
                media_row["event_date"], media_row["event_time"],
                user_id, "Bulk Rationale", "processing", 0, 0, job_folder,
                datetime.now(), datetime.now(),
            ),
        )
        for step in BULK_STEPS:
            cursor.execute(
                """
                INSERT INTO job_steps (job_id, step_number, step_name, status, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (job_id, step["step_number"], step["name"], "pending", datetime.now()),
            )

    create_activity_log(
        user_id, "job_started",
        f"Started Bulk Rationale (from Media Presence): {title}", job_id, "Bulk Rationale",
    )

    threading.Thread(
        target=run_bulk_pipeline,
        args=(job_id, job_folder, media_row["event_date"], media_row["event_time"]),
        daemon=True,
    ).start()
    return job_id


def _create_media_rationale_job(media_row, user_id):
    """Insert a Media Rationale (auto end-to-end) job and start its pipeline."""
    from backend.pipeline.pipeline_manager import (
        create_job_directory, PIPELINE_STEPS, run_pipeline_step,
    )

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    channel = _channel_for(media_row.get("channel_id"))
    channel_name = channel["channel_name"] if channel else ""
    title = media_row.get("video_title") or f"Media Presence {media_row['id']}"

    create_job_directory(job_id)

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO jobs (
                id, user_id, channel_id, tool_used, title, video_id,
                date, time, youtube_url, duration, status,
                current_step, progress, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id, user_id, media_row.get("channel_id"), "Media Rationale", title, "",
                media_row["event_date"], media_row["event_time"],
                media_row.get("video_url") or "", "", "pending",
                0, 0, datetime.now(), datetime.now(),
            ),
        )
        for step in PIPELINE_STEPS:
            cursor.execute(
                """
                INSERT INTO job_steps (job_id, step_number, step_name, status, message, output_files)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (job_id, step["number"], step["name"], "pending", None, []),
            )

    create_activity_log(
        user_id, "job_started",
        f"Started Media Rationale (auto from Media Presence): {title}", job_id, "Media Rationale",
    )

    def _run_auto():
        try:
            with get_db_cursor(commit=True) as cursor:
                cursor.execute(
                    "UPDATE jobs SET status = 'processing', updated_at = %s WHERE id = %s",
                    (datetime.now(), job_id),
                )
            # Run steps 1..8 (the same point at which the manual flow also pauses)
            for step_num in range(1, 9):
                ok = run_pipeline_step(job_id, step_num)
                if not ok:
                    break
        except Exception as exc:
            print(f"[media_presence auto] Pipeline error for {job_id}: {exc}")

    threading.Thread(target=_run_auto, daemon=True).start()
    return job_id


def _trigger_downstream_job(media_row, transcript_text, user_id):
    """Dispatch to the rationale tool selected on the entry."""
    tool = media_row.get("rationale_tool")
    if tool == "bulk_rationale":
        return _create_bulk_rationale_job(media_row, transcript_text, user_id)
    if tool == "media_rationale":
        return _create_media_rationale_job(media_row, user_id)
    raise ValueError(f"Unknown rationale_tool: {tool}")


def unlink_deleted_job(job_id):
    """Reset MP rows that referenced a now-deleted job so the user can
    restart the corresponding step.

    - If the deleted job was the linked transcribe job (Voice Typing /
      AI Transcribe / Live Transcribe), clear linked_transcribe_job_id,
      transcribe_method, transcribe_status (back to 'pending'), and any
      transcript text/path.  The Voice/AI buttons reappear in MP.
    - If the deleted job was the rationale job (Bulk / Media / Premium /
      Manual), clear rationale_job_id, rationale_status (back to
      'pending') and output_pdf_path.  The "Start" rationale button
      reappears.
    Safe to call for any job_id — does nothing when no MP row references
    it.  Caller is responsible for already having committed the DELETE
    on the jobs row before invoking this (so the LEFT JOIN in
    _sync_from_job doesn't re-stamp stale data)."""
    if not job_id:
        return
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE media_presence
                SET linked_transcribe_job_id = NULL,
                    transcribe_method = NULL,
                    transcribe_status = 'pending',
                    transcript_text = NULL,
                    transcript_file_path = NULL,
                    updated_at = %s
                WHERE linked_transcribe_job_id = %s
                """,
                (datetime.now(), job_id),
            )
            cursor.execute(
                """
                UPDATE media_presence
                SET rationale_job_id = NULL,
                    rationale_status = 'pending',
                    output_pdf_path = NULL,
                    updated_at = %s
                WHERE rationale_job_id = %s
                """,
                (datetime.now(), job_id),
            )
    except Exception as exc:
        # Never let MP cleanup failures break the underlying job DELETE.
        print(f"[media_presence] unlink_deleted_job({job_id}) failed: {exc}")


def _sync_from_job(media_id):
    """Refresh rationale_status & output_pdf_path on a media_presence row
    by inspecting its linked job + saved_rationale row."""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            SELECT mp.id, mp.rationale_job_id, mp.rationale_status,
                   j.status AS job_status,
                   sr.unsigned_pdf_path, sr.signed_pdf_path
            FROM media_presence mp
            LEFT JOIN jobs j ON mp.rationale_job_id = j.id
            LEFT JOIN saved_rationale sr ON sr.job_id = mp.rationale_job_id
            WHERE mp.id = %s
            """,
            (media_id,),
        )
        row = cursor.fetchone()
        if not row or not row.get("rationale_job_id"):
            return

        job_status = row.get("job_status")
        new_status = row.get("rationale_status")
        new_pdf = row.get("signed_pdf_path") or row.get("unsigned_pdf_path")

        if job_status == "signed" or row.get("signed_pdf_path"):
            new_status = "signed"
        elif job_status in _DONE_STATUSES:
            new_status = "done"
        elif job_status in _FAILED_STATUSES:
            new_status = "failed"
        elif job_status:
            new_status = "started"

        cursor.execute(
            """
            UPDATE media_presence
            SET rationale_status = %s,
                output_pdf_path = COALESCE(%s, output_pdf_path),
                updated_at = %s
            WHERE id = %s
            """,
            (new_status, new_pdf, datetime.now(), media_id),
        )


# ---------- CRUD endpoints ---------------------------------------------------

@media_presence_bp.route("", methods=["GET"])
@jwt_required()
def list_entries():
    user_id = get_jwt_identity()
    transcribe_status = request.args.get("transcribe_status") or None
    rationale_status = request.args.get("rationale_status") or None
    limit = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))
    # Non-admins only see their own entries
    owner_filter = None if _is_admin(user_id) else user_id
    rows = MediaPresence.list_all(
        limit=limit, offset=offset,
        transcribe_status=transcribe_status,
        rationale_status=rationale_status,
        created_by=owner_filter,
    )
    # Opportunistic status sync for any entry with a linked rationale job.
    # We deliberately re-sync rows in 'done' state too, because a later signed
    # PDF upload flips job.status='signed' and we want MP to reflect it.
    # Only terminal 'failed' / 'signed' rows are skipped.
    for r in rows:
        if r.get("rationale_job_id") and r.get("rationale_status") not in ("failed", "signed"):
            try:
                _sync_from_job(r["id"])
            except Exception as exc:
                print(f"[media_presence] sync error for {r['id']}: {exc}")
    # Re-fetch after sync so the response reflects latest values
    rows = MediaPresence.list_all(
        limit=limit, offset=offset,
        transcribe_status=transcribe_status,
        rationale_status=rationale_status,
        created_by=owner_filter,
    )
    return jsonify({"success": True, "items": rows}), 200


@media_presence_bp.route("", methods=["POST"])
@jwt_required()
def create_entry():
    user_id = get_jwt_identity()
    data = request.get_json() or {}

    # Required-field validation
    for key in ("platform", "event_date", "event_time", "rationale_tool"):
        if not data.get(key):
            return jsonify({"error": f"'{key}' is required"}), 400

    if data["rationale_tool"] not in ("bulk_rationale", "media_rationale"):
        return jsonify({"error": "Invalid rationale_tool"}), 400

    if data["rationale_tool"] == "media_rationale" and not data.get("video_url"):
        return jsonify({"error": "video_url is required when rationale_tool is media_rationale"}), 400

    entry = MediaPresence.create(data, created_by=user_id)
    return jsonify({"success": True, "item": entry}), 201


@media_presence_bp.route("/<int:media_id>", methods=["GET"])
@jwt_required()
def get_entry(media_id):
    user_id = get_jwt_identity()
    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err
    return jsonify({"success": True, "item": entry}), 200


@media_presence_bp.route("/<int:media_id>", methods=["PUT"])
@jwt_required()
def update_entry(media_id):
    user_id = get_jwt_identity()
    _, err = _authorize_entry(media_id, user_id)
    if err:
        return err
    data = request.get_json() or {}
    entry = MediaPresence.update(media_id, data)
    return jsonify({"success": True, "item": entry}), 200


@media_presence_bp.route("/<int:media_id>", methods=["DELETE"])
@jwt_required()
def delete_entry(media_id):
    user_id = get_jwt_identity()
    _, err = _authorize_entry(media_id, user_id)
    if err:
        return err
    ok = MediaPresence.delete(media_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True}), 200


# ---------- Method-specific actions -----------------------------------------

@media_presence_bp.route("/<int:media_id>/save-transcript", methods=["POST"])
@jwt_required()
def save_transcript(media_id):
    """Called by Voice Typing & AI Transcribe pages once the user is happy
    with the transcript. Saves the text and triggers the downstream rationale job."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    transcript_text = (data.get("transcript_text") or "").strip()
    method = data.get("transcribe_method")  # 'voice_typing' or 'ai_transcribe'

    if not transcript_text:
        return jsonify({"error": "transcript_text is required"}), 400
    if method not in ("voice_typing", "ai_transcribe"):
        return jsonify({"error": "transcribe_method must be voice_typing or ai_transcribe"}), 400

    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err

    if entry["rationale_tool"] != "bulk_rationale":
        return jsonify({
            "error": "Voice Typing / AI Transcribe only support the Bulk Rationale tool."
        }), 400

    # Idempotency guard — don't create a second job if one is already running/done
    if entry.get("rationale_job_id") and entry.get("rationale_status") in ("started", "done"):
        return jsonify({
            "success": False,
            "error": (
                "A rationale job is already linked to this entry "
                f"({entry['rationale_job_id']}, status={entry['rationale_status']})."
            ),
            "item": entry,
        }), 409

    # Persist transcript text + file
    work_dir = _ensure_dir(os.path.join(TRANSCRIPT_ROOT, f"entry_{media_id}_manual"))
    txt_path = os.path.join(work_dir, "transcript.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE media_presence
            SET transcribe_method = %s,
                transcribe_status = 'completed',
                transcript_text = %s,
                transcript_file_path = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (method, transcript_text, txt_path, datetime.now(), media_id),
        )

    # Re-read so we have the latest row
    entry = MediaPresence.get(media_id)

    # Trigger downstream rationale job
    try:
        job_id = _trigger_downstream_job(entry, transcript_text, user_id)
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE media_presence
                SET rationale_job_id = %s,
                    rationale_status = 'started',
                    updated_at = %s
                WHERE id = %s
                """,
                (job_id, datetime.now(), media_id),
            )
        return jsonify({
            "success": True,
            "message": "Transcript saved & rationale job started.",
            "rationale_job_id": job_id,
            "item": MediaPresence.get(media_id),
        }), 200
    except Exception as exc:
        return jsonify({
            "success": False,
            "error": f"Transcript saved but failed to start rationale: {exc}",
            "item": MediaPresence.get(media_id),
        }), 500


@media_presence_bp.route("/<int:media_id>/start-voice-typing", methods=["POST"])
@jwt_required()
def start_voice_typing(media_id):
    """Kick off the *real* server-side Voice Typing flow (Vosk → review →
    ChatGPT arrange → Bulk Rationale child) for a Media Presence entry.

    This replaces the old browser-mic legacy flow that the Voice button used
    to open. The new flow:
      1. Validates the entry has a YouTube URL + channel and uses
         rationale_tool='bulk_rationale' (Voice Typing's only downstream).
      2. Inserts a Voice Typing job in `jobs` and tags it with
         `payload.media_presence_id` so we can link the eventual Bulk
         Rationale child back to this MP row.
      3. Marks the MP row transcribe_method='voice_typing',
         transcribe_status='started'.
      4. Spawns the Vosk worker (same as POST /voice-typing/jobs).
      5. Returns the new voice_job_id so the UI can navigate straight to
         the live transcription editor.
    """
    user_id = get_jwt_identity()
    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err

    if entry.get("rationale_tool") != "bulk_rationale":
        return jsonify({
            "error": (
                "Voice Typing produces a Bulk Rationale child job. "
                "This entry's rationale tool is "
                f"'{entry.get('rationale_tool')}' — please use AI Transcribe."
            ),
        }), 400

    video_url = (entry.get("video_url") or "").strip()
    if not video_url:
        return jsonify({"error": "Entry has no video_url for Vosk to download."}), 400
    if not entry.get("channel_id"):
        return jsonify({"error": "Entry has no channel_id."}), 400
    if entry.get("transcribe_status") in ("started", "completed"):
        return jsonify({
            "error": f"Transcription already {entry['transcribe_status']} for this entry.",
        }), 409

    # ----- Create the Voice Typing job (mirrors backend/api/voice_typing.py
    # ::create_job, but tagged with media_presence_id in the payload). -----
    import json as _json

    voice_job_id = f"voice-{uuid.uuid4().hex[:8]}"
    folder = f"backend/job_files/{voice_job_id}"
    _ensure_dir(folder)

    channel = _channel_for(entry["channel_id"])
    channel_name = channel["channel_name"] if channel else (entry.get("platform") or "media")
    platform = channel["platform"] if channel else (entry.get("platform") or "")
    # Canonical job title — never use entry['video_title'] here, it would
    # break the unified "{Platform} - {Channel} - {Date} - {Time}" format
    # that every other tool follows.
    from backend.utils.job_title import build_job_title
    title = build_job_title(platform, channel_name, entry["event_date"], entry.get("event_time"))

    language = "hi-IN"
    payload = {
        "transcript_text": "",
        "arranged_text": "",
        "language": language,
        "video_url": video_url,
        # Linkage: voice_typing's _spawn_bulk_from_arranged reads this and
        # stamps the resulting bulk_job_id back onto the MP row.
        "media_presence_id": media_id,
    }

    with get_db_cursor(commit=True) as cursor:
        # RACE-SAFE GUARD: atomically claim the MP row for voice typing.
        # If two concurrent requests arrive (double-click / quick retry),
        # only one will see rowcount=1; the other gets 409 and we never
        # spawn a duplicate Vosk worker. The pre-check above is just for
        # nicer error messages — this is the real lock.
        cursor.execute(
            """
            UPDATE media_presence
            SET transcribe_method = 'voice_typing',
                transcribe_status = 'started',
                updated_at = %s
            WHERE id = %s
              AND transcribe_status NOT IN ('started', 'completed')
            RETURNING id
            """,
            (datetime.now(), media_id),
        )
        if cursor.fetchone() is None:
            return jsonify({
                "error": "Transcription already in progress or completed for this entry.",
            }), 409

        cursor.execute(
            """
            INSERT INTO jobs (
                id, youtube_url, title, channel_id, date, time,
                user_id, tool_used, status, progress, current_step,
                folder_path, payload, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                voice_job_id, video_url, title, entry["channel_id"],
                entry["event_date"], entry["event_time"],
                user_id, "Voice Typing", "recording", 0, 0,
                folder, _json.dumps(payload), datetime.now(), datetime.now(),
            ),
        )

        # Now that the jobs row exists, the FK on linked_transcribe_job_id
        # is satisfied — stamp it on the MP row so the table pill becomes a
        # clickable shortcut into the Voice Typing job.
        cursor.execute(
            "UPDATE media_presence SET linked_transcribe_job_id = %s, updated_at = %s WHERE id = %s",
            (voice_job_id, datetime.now(), media_id),
        )

    try:
        create_activity_log(
            user_id, "job_started",
            f"Started Voice Typing (from Media Presence): {title}",
            voice_job_id, "Voice Typing",
        )
    except Exception as log_err:
        print(f"[media_presence start_voice_typing] activity log failed: {log_err}")

    # Spawn the Vosk worker. Failure here is non-fatal at the API level —
    # the job row exists, status will be flipped to 'failed' by the worker
    # if the download or transcription blows up.
    try:
        from backend.pipeline.voice_typing.transcribe_vosk import spawn as spawn_vosk
        spawn_vosk(voice_job_id, video_url, language)
    except Exception as spawn_err:
        print(f"[media_presence start_voice_typing] Vosk spawn failed: {spawn_err}")
        with get_db_cursor(commit=True) as cursor:
            payload["transcribe_error"] = f"Worker spawn failed: {spawn_err}"
            cursor.execute(
                "UPDATE jobs SET status = 'failed', payload = %s::jsonb, updated_at = %s WHERE id = %s",
                (_json.dumps(payload), datetime.now(), voice_job_id),
            )
            cursor.execute(
                "UPDATE media_presence SET transcribe_status = 'failed', updated_at = %s WHERE id = %s",
                (datetime.now(), media_id),
            )
        return jsonify({
            "error": f"Failed to start Vosk worker: {spawn_err}",
            "voice_job_id": voice_job_id,
        }), 500

    return jsonify({
        "success": True,
        "message": "Voice Typing job started.",
        "voice_job_id": voice_job_id,
        "item": MediaPresence.get(media_id),
    }), 201


def _probe_youtube_is_live(url: str):
    """Return (is_live, error_message). Best-effort: a quick URL-shape check
    short-circuits, then yt-dlp's metadata extractor checks `is_live`.

    If yt-dlp itself fails (network blip, missing cookies, blocked region),
    we fall back to the URL heuristic so a temporary probe failure doesn't
    block the user — the capture worker will surface a clearer error if the
    stream really isn't live."""
    if not url:
        return False, "URL is empty."
    low = url.lower()
    looks_live = ('/live/' in low) or ('youtube.com/watch' in low) or ('youtu.be/' in low)
    if not looks_live:
        return False, "URL is not a recognised YouTube link."
    try:
        from yt_dlp import YoutubeDL  # type: ignore
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        # Same cookies file used by the live capture worker — without it
        # YouTube's bot-check rejects the metadata probe even for valid
        # live URLs ("Sign in to confirm you're not a bot").
        for cookies_path in (
            os.path.join('backend', 'youtube_cookies.txt'),
            os.path.join('backend', 'uploaded_files', 'youtube_cookies.txt'),
        ):
            if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
                ydl_opts['cookiefile'] = cookies_path
                break
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        if info.get('is_live'):
            return True, None
        if info.get('was_live') or info.get('live_status') in ('was_live', 'post_live'):
            return False, "This stream has already ended — use AI Transcribe or Auto for ended broadcasts."
        if info.get('live_status') in ('is_live', 'is_upcoming'):
            return True, None
        # Pre-recorded VOD
        return False, "URL is a regular YouTube video, not a live stream."
    except Exception as e:
        # yt-dlp probe failed (network blip, missing cookies, region block).
        # Fall back to the broader YouTube URL shape so a transient probe
        # failure doesn't reject otherwise-valid /live/, /watch?, or
        # youtu.be/ links — the capture worker will surface a clearer
        # error if the stream really isn't live.
        print(f"[live-transcribe] yt-dlp probe failed, falling back to URL heuristic: {e}")
        return looks_live, (
            None if looks_live
            else "Could not verify this is a live stream and the URL is not a recognised YouTube link."
        )


@media_presence_bp.route("/<int:media_id>/start-live-transcribe", methods=["POST"])
@jwt_required()
def start_live_transcribe(media_id):
    """Kick off the server-side Live Transcribe flow (AssemblyAI Realtime →
    review → OpenAI extract → Bulk Rationale child) for a Media Presence
    entry. Mirrors start_voice_typing but for the Live Transcribe tool."""
    user_id = get_jwt_identity()
    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err

    if entry.get("rationale_tool") != "bulk_rationale":
        return jsonify({
            "error": (
                "Live Transcribe produces a Bulk Rationale child job. "
                "This entry's rationale tool is "
                f"'{entry.get('rationale_tool')}' — please use a different tool."
            ),
        }), 400

    video_url = (entry.get("video_url") or "").strip()
    if not video_url:
        return jsonify({"error": "Entry has no video_url for Live Transcribe."}), 400
    if not entry.get("channel_id"):
        return jsonify({"error": "Entry has no channel_id."}), 400
    if entry.get("transcribe_status") in ("started", "completed"):
        return jsonify({
            "error": f"Transcription already {entry['transcribe_status']} for this entry.",
        }), 409

    # Validate this is actually a YouTube live stream (or a /live/ short link).
    # Cheap heuristic first (URL shape), then a yt-dlp metadata probe for
    # is_live / was_live so we reject pre-recorded videos with a clear error
    # instead of letting the capture worker fail mid-stream.
    is_live, live_err = _probe_youtube_is_live(video_url)
    if not is_live:
        return jsonify({
            "error": live_err or (
                "URL does not appear to be a live YouTube stream. "
                "Live Transcribe only supports live broadcasts — use AI Transcribe "
                "or Auto for already-ended videos."
            ),
        }), 400

    import json as _json

    live_job_id = f"live-{uuid.uuid4().hex[:8]}"
    folder = f"backend/job_files/{live_job_id}"
    _ensure_dir(folder)
    _ensure_dir(os.path.join(folder, "audio"))

    channel = _channel_for(entry["channel_id"])
    channel_name = channel["channel_name"] if channel else (entry.get("platform") or "media")
    platform = channel["platform"] if channel else (entry.get("platform") or "")
    from backend.utils.job_title import build_job_title
    title = build_job_title(platform, channel_name, entry["event_date"], entry.get("event_time"))

    payload = {
        "live_url": video_url,
        "live_transcript": "",
        "diarized_transcript": "",
        "arranged_text": "",
        "transcribe_progress": 0,
        "media_presence_id": media_id,
    }

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE media_presence
            SET transcribe_method = 'live_transcribe',
                transcribe_status = 'started',
                updated_at = %s
            WHERE id = %s
              AND transcribe_status NOT IN ('started', 'completed')
            RETURNING id
            """,
            (datetime.now(), media_id),
        )
        if cursor.fetchone() is None:
            return jsonify({
                "error": "Transcription already in progress or completed for this entry.",
            }), 409

        cursor.execute(
            """
            INSERT INTO jobs (
                id, youtube_url, title, channel_id, date, time,
                user_id, tool_used, status, progress, current_step,
                folder_path, payload, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                live_job_id, video_url, title, entry["channel_id"],
                entry["event_date"], entry["event_time"],
                user_id, "Live Transcribe", "live", 0, 0,
                folder, _json.dumps(payload), datetime.now(), datetime.now(),
            ),
        )

        cursor.execute(
            "UPDATE media_presence SET linked_transcribe_job_id = %s, updated_at = %s WHERE id = %s",
            (live_job_id, datetime.now(), media_id),
        )

    try:
        create_activity_log(
            user_id, "job_started",
            f"Started Live Transcribe (from Media Presence): {title}",
            live_job_id, "Live Transcribe",
        )
    except Exception as log_err:
        print(f"[media_presence start_live_transcribe] activity log failed: {log_err}")

    try:
        from backend.pipeline.live_transcribe.realtime_transcribe import spawn as spawn_live
        spawn_live(live_job_id, video_url)
    except Exception as spawn_err:
        print(f"[media_presence start_live_transcribe] live worker spawn failed: {spawn_err}")
        with get_db_cursor(commit=True) as cursor:
            payload["transcribe_error"] = f"Worker spawn failed: {spawn_err}"
            cursor.execute(
                "UPDATE jobs SET status = 'failed', payload = %s::jsonb, updated_at = %s WHERE id = %s",
                (_json.dumps(payload), datetime.now(), live_job_id),
            )
            cursor.execute(
                "UPDATE media_presence SET transcribe_status = 'failed', updated_at = %s WHERE id = %s",
                (datetime.now(), media_id),
            )
        return jsonify({
            "error": f"Failed to start live worker: {spawn_err}",
            "live_job_id": live_job_id,
        }), 500

    return jsonify({
        "success": True,
        "message": "Live Transcribe job started.",
        "live_job_id": live_job_id,
        "item": MediaPresence.get(media_id),
    }), 201


@media_presence_bp.route("/<int:media_id>/start-ai-transcribe", methods=["POST"])
@jwt_required()
def start_ai_transcribe(media_id):
    """Kick off backend AI transcription (yt-dlp + AssemblyAI) for an entry.
    Optional body: { language_code: 'hi' | 'en' | ... }
    Optional multipart upload: 'audio' file (skips YouTube download).

    NOTE: This endpoint only produces the transcript text. The downstream
    rationale job is NOT triggered here — the user reviews/edits the transcript
    on the AI Transcribe page and the rationale job is started by save-transcript."""
    user_id = get_jwt_identity()
    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err

    if entry["rationale_tool"] != "bulk_rationale":
        return jsonify({
            "error": "AI Transcribe only supports Bulk or Transcript rationale tools."
        }), 400

    # Accept either JSON or multipart
    language_code = "hi"
    local_audio_path = None

    if "audio" in request.files:
        audio_file = request.files["audio"]
        work_dir = _ensure_dir(os.path.join(TRANSCRIPT_ROOT, f"entry_{media_id}_upload"))
        safe_name = secure_filename(audio_file.filename or "upload.wav")
        local_audio_path = os.path.join(work_dir, safe_name)
        audio_file.save(local_audio_path)
        language_code = request.form.get("language_code") or language_code
    else:
        body = request.get_json(silent=True) or {}
        language_code = body.get("language_code") or language_code

    youtube_url = entry.get("video_url")
    if not local_audio_path and not youtube_url:
        return jsonify({
            "error": "Entry has no video_url and no audio file was uploaded."
        }), 400

    # Mark started immediately and run transcription in background thread
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE media_presence
            SET transcribe_method = 'ai_transcribe',
                transcribe_status = 'started',
                updated_at = %s
            WHERE id = %s
            """,
            (datetime.now(), media_id),
        )

    source = (
        {"local_audio_path": local_audio_path}
        if local_audio_path
        else {"youtube_url": youtube_url}
    )

    def _run_transcribe_only():
        # The service itself updates transcribe_status to completed/failed and
        # writes transcript_text. We don't auto-create the downstream job here;
        # the user reviews the text and presses Save on the AI Transcribe page.
        try:
            transcribe_media_presence(media_id, source, language_code=language_code)
        except Exception as exc:
            print(f"[media_presence ai_transcribe] transcription error: {exc}")

    threading.Thread(target=_run_transcribe_only, daemon=True).start()

    return jsonify({
        "success": True,
        "message": "AI transcription started; poll the entry for status.",
        "item": MediaPresence.get(media_id),
    }), 202


@media_presence_bp.route("/<int:media_id>/start-auto", methods=["POST"])
@jwt_required()
def start_auto(media_id):
    """Kick off the full Media Rationale 14-step pipeline for an entry."""
    user_id = get_jwt_identity()
    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err
    if entry["rationale_tool"] != "media_rationale":
        return jsonify({"error": "Auto method requires rationale_tool = media_rationale"}), 400
    if not entry.get("video_url"):
        return jsonify({"error": "video_url is required for the auto method"}), 400
    if entry.get("rationale_job_id") and entry.get("rationale_status") in ("started", "done"):
        return jsonify({
            "error": (
                "Auto pipeline already linked to this entry "
                f"({entry['rationale_job_id']}, status={entry['rationale_status']})."
            )
        }), 409

    try:
        job_id = _create_media_rationale_job(entry, user_id)
    except Exception as exc:
        return jsonify({"error": f"Failed to start auto pipeline: {exc}"}), 500

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE media_presence
            SET transcribe_method = 'auto',
                transcribe_status = 'started',
                rationale_job_id = %s,
                rationale_status = 'started',
                updated_at = %s
            WHERE id = %s
            """,
            (job_id, datetime.now(), media_id),
        )

    return jsonify({
        "success": True,
        "message": "Auto pipeline started.",
        "rationale_job_id": job_id,
        "item": MediaPresence.get(media_id),
    }), 202


@media_presence_bp.route("/<int:media_id>/sync-status", methods=["GET"])
@jwt_required()
def sync_status(media_id):
    """Force a refresh of an entry's rationale_status from its linked job."""
    user_id = get_jwt_identity()
    _, err = _authorize_entry(media_id, user_id)
    if err:
        return err
    _sync_from_job(media_id)
    return jsonify({"success": True, "item": MediaPresence.get(media_id)}), 200


@media_presence_bp.route("/<int:media_id>/transcript", methods=["GET"])
@jwt_required()
def get_transcript(media_id):
    """Return just the transcript text for the Voice Typing / AI Transcribe pages."""
    user_id = get_jwt_identity()
    entry, err = _authorize_entry(media_id, user_id)
    if err:
        return err
    return jsonify({
        "success": True,
        "transcript_text": entry.get("transcript_text") or "",
        "transcribe_status": entry.get("transcribe_status"),
        "transcribe_method": entry.get("transcribe_method"),
    }), 200


# ---------------------------------------------------------------------------
# Search history (per-user, last 5 distinct queries) — mirrors dashboard.
# Used by the Media Presence filter bar's free-text search input.
# ---------------------------------------------------------------------------

def _ensure_mp_search_history_table():
    """Create the per-user MP search-history table on demand (safe on existing installs)."""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS media_presence_search_history (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                query TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mpsh_user_time "
            "ON media_presence_search_history(user_id, created_at DESC);"
        )


@media_presence_bp.route("/search-history", methods=["GET"])
@jwt_required()
def mp_get_search_history():
    try:
        user_id = get_jwt_identity()
        _ensure_mp_search_history_table()
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT query, MAX(created_at) AS last_used
                FROM media_presence_search_history
                WHERE user_id = %s
                GROUP BY query
                ORDER BY last_used DESC
                LIMIT 5
                """,
                (user_id,),
            )
            rows = cursor.fetchall() or []
        return jsonify({
            "history": [
                {
                    "query": r["query"],
                    "last_used": r["last_used"].isoformat() if r.get("last_used") else None,
                }
                for r in rows
            ]
        }), 200
    except Exception as e:
        print(f"Error getting MP search history: {e}")
        return jsonify({"error": str(e)}), 500


@media_presence_bp.route("/search-history", methods=["POST"])
@jwt_required()
def mp_add_search_history():
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        raw_query = data.get("query")
        if not isinstance(raw_query, str):
            return jsonify({"error": "query must be a string"}), 400
        query = raw_query.strip()
        if not query:
            return jsonify({"error": "query is required"}), 400
        if len(query) > 500:
            query = query[:500]
        _ensure_mp_search_history_table()
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"mpsh:{user_id}",),
            )
            cursor.execute(
                "DELETE FROM media_presence_search_history "
                "WHERE user_id = %s AND LOWER(query) = LOWER(%s)",
                (user_id, query),
            )
            cursor.execute(
                "INSERT INTO media_presence_search_history (user_id, query) VALUES (%s, %s)",
                (user_id, query),
            )
            cursor.execute(
                """
                DELETE FROM media_presence_search_history
                WHERE user_id = %s
                  AND id NOT IN (
                    SELECT id FROM media_presence_search_history
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT 5
                  )
                """,
                (user_id, user_id),
            )
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"Error adding MP search history: {e}")
        return jsonify({"error": str(e)}), 500


@media_presence_bp.route("/search-history", methods=["DELETE"])
@jwt_required()
def mp_clear_search_history():
    try:
        user_id = get_jwt_identity()
        query = (request.args.get("query") or "").strip()
        _ensure_mp_search_history_table()
        with get_db_cursor(commit=True) as cursor:
            if query:
                cursor.execute(
                    "DELETE FROM media_presence_search_history "
                    "WHERE user_id = %s AND LOWER(query) = LOWER(%s)",
                    (user_id, query),
                )
            else:
                cursor.execute(
                    "DELETE FROM media_presence_search_history WHERE user_id = %s",
                    (user_id,),
                )
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"Error clearing MP search history: {e}")
        return jsonify({"error": str(e)}), 500
