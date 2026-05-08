"""
Voice Typing API Endpoints

Voice Typing transcribes a YouTube video on the SERVER using Vosk (offline,
free, runs on the VPS). Once the job is created the user's browser is no
longer required — the user can close the tab, come back hours later, and the
transcript will be ready for review.

We deliberately keep this separate from AI Transcribe (which uses AssemblyAI,
paid, very high accuracy). Voice Typing is the free / lower-accuracy variant
designed for the edit → ChatGPT-arrange → Bulk Rationale flow.

Lifecycle (5-step pipeline mirroring AI Transcribe):
  recording        - Step 1: Vosk worker thread is downloading the audio
                     and transcribing it on the server. The frontend polls
                     the job's transcript_text + progress for live updates.
  awaiting_review  - Step 2: Vosk finished (or user pressed Stop).
                     Transcript is editable, ready for review.
  translating      - Step 3 in flight: user pressed "Translate to English"
                     — the server is calling OpenAI to translate the
                     reviewed transcript to English.
  awaiting_translate_review
                   - Step 3 done: translation is editable. User reviews
                     the English text before extracting Pradip's analysis.
  arranging        - Step 4 in flight: user pressed "Extract Pradip
                     Halder's Analysis" — the server is calling OpenAI to
                     reformat the translated transcript stock-wise.
  awaiting_arrange_review
                   - Step 4 done: arranged (stock\nanalysis) text is
                     editable so the user can fix mistakes before pushing
                     it into Bulk Rationale.
  bulk_started     - Step 5: user pressed "Send to Bulk Rationale" — a
                     child Bulk Rationale job has been spawned.
  failed           - Audio download / transcription / translate / extract
                     failed.

The transcript text, spawned bulk job id, transcribe progress, and any
errors all live in `jobs.payload`.
"""

import os
import json
import uuid
import threading
from datetime import datetime

from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from backend.api import voice_typing_bp
from backend.utils.database import get_db_cursor
from backend.api.activity_logs import create_activity_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload_dict(row):
    """Return jobs.payload as a python dict (handle JSONB / str / None)."""
    p = row.get('payload') if isinstance(row, dict) else row['payload']
    if not p:
        return {}
    if isinstance(p, dict):
        return p
    try:
        return json.loads(p)
    except Exception:
        return {}


def _job_owner_check(cursor, job_id, user_id):
    cursor.execute(
        "SELECT * FROM jobs WHERE id = %s AND user_id = %s AND tool_used = %s",
        (job_id, user_id, 'Voice Typing'),
    )
    return cursor.fetchone()


# ---------------------------------------------------------------------------
# Media-Presence link-back helpers (mirror AI Transcribe behaviour)
#
# When a Voice Typing job was spawned from a Media Presence row (the user
# clicked "via voice typing →" on the MP table), we mirror the VT job's
# stage transitions onto media_presence.transcribe_status so the MP table
# reflects the live state instead of being stuck on 'started' forever.
# ---------------------------------------------------------------------------

# Maps Voice Typing's internal status → the status string Media Presence
# (and StatusPill) understands. The MP UI's StatusPill already renders
# 'transcribing', 'review_transcript', 'translating', 'review_translation',
# 'extracting', 'review_extract' as labelled, coloured pills (see
# src/pages/MediaPresencePage.tsx :: StatusPill).
_VT_STATUS_TO_MP = {
    'recording': 'transcribing',
    'awaiting_review': 'review_transcript',
    'translating': 'translating',
    'awaiting_translate_review': 'review_translation',
    'arranging': 'extracting',
    'awaiting_arrange_review': 'review_extract',
    'bulk_started': 'completed',
    'completed': 'completed',
}


def _mp_id_for_job(cursor, job_id):
    """Return the linked media_presence_id for a Voice Typing job, or
    None if the job wasn't started from an MP row."""
    cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
    row = cursor.fetchone()
    if not row:
        return None
    payload = _payload_dict(row)
    return payload.get('media_presence_id')


def _mp_linkback_status(job_id, vt_status):
    """Mirror a Voice Typing stage transition onto its linked
    media_presence row's transcribe_status. No-op if the job wasn't
    started from a Media Presence entry, OR if the MP row has since been
    re-linked to a newer transcribe job (prevents a stale worker from
    overwriting fresher state — same race-safety guard AI Transcribe
    needs but doesn't yet have)."""
    mp_status = _VT_STATUS_TO_MP.get(vt_status)
    if not mp_status:
        return
    try:
        with get_db_cursor(commit=True) as cursor:
            mp_id = _mp_id_for_job(cursor, job_id)
            if not mp_id:
                return
            cursor.execute(
                """UPDATE media_presence
                   SET transcribe_status = %s,
                       updated_at = %s
                   WHERE id = %s
                     AND linked_transcribe_job_id = %s""",
                (mp_status, datetime.now(), mp_id, job_id),
            )
            if cursor.rowcount == 0:
                print(f"ℹ️  Voice Typing {job_id}: MP {mp_id} no longer "
                      f"linked to this job — skipping stale {vt_status} update")
    except Exception as link_err:
        print(f"⚠️  Voice Typing {job_id}: MP stage linkback skipped: {link_err}")


def _mp_linkback_failed(job_id, err_msg):
    """Mirror a Voice Typing job-level failure onto the linked
    media_presence row so its Transcribe pill flips from 'started' to
    'failed' instead of getting stuck on the spinner.

    Race-safety: only touches the MP row if it's STILL linked to this
    specific Voice Typing job. If the user has since re-linked the row
    to a newer job, the old worker's failure callback is dropped."""
    try:
        with get_db_cursor(commit=True) as cursor:
            mp_id = _mp_id_for_job(cursor, job_id)
            if not mp_id:
                return
            cursor.execute(
                """UPDATE media_presence
                   SET transcribe_status = 'failed',
                       notes = %s,
                       updated_at = %s
                   WHERE id = %s
                     AND linked_transcribe_job_id = %s""",
                (f"Voice Typing error: {(err_msg or '')[:500]}",
                 datetime.now(), mp_id, job_id),
            )
            if cursor.rowcount == 0:
                print(f"ℹ️  Voice Typing {job_id}: MP {mp_id} no longer "
                      f"linked to this job — skipping stale failure update")
    except Exception as link_err:
        print(f"⚠️  Voice Typing {job_id}: MP failure linkback skipped: {link_err}")


def _serialize(job):
    payload = _payload_dict(job)
    return {
        'jobId': job['id'],
        'title': job.get('title'),
        'status': job['status'],
        'progress': job.get('progress', 0),
        'channelId': job.get('channel_id'),
        'date': str(job['date']) if job.get('date') else None,
        'time': str(job['time']) if job.get('time') else None,
        'createdAt': job['created_at'].isoformat() if job.get('created_at') else None,
        'updatedAt': job['updated_at'].isoformat() if job.get('updated_at') else None,
        'transcriptText': payload.get('transcript_text', ''),
        'translatedText': payload.get('translated_text', ''),
        'arrangedText': payload.get('arranged_text', ''),
        'language': payload.get('language', 'hi-IN'),
        'videoUrl': payload.get('video_url') or job.get('youtube_url') or '',
        'bulkJobId': payload.get('bulk_job_id'),
        'arrangeError': payload.get('arrange_error'),
        'translateError': payload.get('translate_error'),
        'transcribeError': payload.get('transcribe_error'),
        'transcribeProgress': payload.get('transcribe_progress', 0),
    }


def _serialize_with_channel(row):
    base = _serialize(row)
    base['channelName'] = row.get('channel_name')
    base['platform'] = row.get('platform')
    # When the SQL query also LEFT JOINs the spawned Bulk Rationale job,
    # surface its status + progress so the jobs list can render a live
    # badge (Bulk Rationale is async — its status moves through 'started'
    # → 'completed'/'failed' independently of the Voice Typing job).
    if 'bulk_status' in row:
        base['bulkJobStatus'] = row.get('bulk_status')
    if 'bulk_progress' in row:
        base['bulkJobProgress'] = row.get('bulk_progress')
    return base


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@voice_typing_bp.route('/jobs', methods=['GET'])
@jwt_required()
def list_jobs():
    """List the current user's Voice Typing jobs (most recent first)."""
    try:
        user_id = get_jwt_identity()
        with get_db_cursor() as cursor:
            # LEFT JOIN the spawned Bulk Rationale child by reading the
            # bulk job id out of the Voice Typing job's JSONB payload —
            # we need its current status + progress to render a live
            # badge in the jobs list (the bulk pipeline runs async after
            # 'send to bulk' and we want the user to see when it
            # completes without having to click into another tool).
            cursor.execute(
                """
                SELECT j.*, c.channel_name, c.platform,
                       bj.status   AS bulk_status,
                       bj.progress AS bulk_progress
                FROM jobs j
                LEFT JOIN channels c ON c.id = j.channel_id
                LEFT JOIN jobs bj
                       ON bj.id = (j.payload->>'bulk_job_id')
                      AND bj.tool_used = 'Bulk Rationale'
                WHERE j.user_id = %s AND j.tool_used = %s
                ORDER BY j.created_at DESC
                LIMIT 200
                """,
                (user_id, 'Voice Typing'),
            )
            rows = cursor.fetchall()
        return jsonify({'success': True, 'jobs': [_serialize_with_channel(r) for r in rows]}), 200
    except Exception as e:
        print(f"voice_typing list_jobs error: {e}")
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs', methods=['POST'])
@jwt_required()
def create_job():
    """Create a new Voice Typing job. The YouTube URL is REQUIRED — the
    server will download its audio and transcribe it with Vosk in a
    background thread. The user's browser is just a viewer afterwards.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}

        channel_id = data.get('channelId')
        call_date = data.get('callDate')
        call_time = data.get('callTime') or '10:00:00'
        title = (data.get('title') or '').strip()
        language = (data.get('language') or 'hi-IN').strip()
        video_url = (data.get('videoUrl') or '').strip()

        if not channel_id or not call_date:
            return jsonify({'error': 'Channel and date are required'}), 400
        if not video_url:
            return jsonify({'error': 'YouTube video URL is required'}), 400

        # Convert /live/, /shorts/, /embed/, youtu.be/ → canonical
        # watch?v=<id> so the stored DB row, the embedded player iframe,
        # and the downstream Vosk audio download all use the same shape
        # that yt-dlp + RapidAPI know how to handle.
        from backend.utils.youtube import normalize_youtube_url
        video_url = normalize_youtube_url(video_url)

        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT channel_name, platform FROM channels WHERE id = %s",
                (channel_id,),
            )
            ch = cursor.fetchone()
            if not ch:
                return jsonify({'error': 'Channel not found'}), 404

            if not title:
                from backend.utils.job_title import build_job_title
                title = build_job_title(ch['platform'], ch['channel_name'], call_date, call_time)

            job_id = f"voice-{uuid.uuid4().hex[:8]}"
            folder = f"backend/job_files/{job_id}"
            os.makedirs(folder, exist_ok=True)

            payload = {
                'transcript_text': '',
                'arranged_text': '',
                'language': language,
                'video_url': video_url,
            }

            cursor.execute(
                """
                INSERT INTO jobs (
                    id, youtube_url, title, channel_id, date, time,
                    user_id, tool_used, status, progress, current_step,
                    folder_path, payload, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    job_id, video_url, title, channel_id, call_date, call_time,
                    user_id, 'Voice Typing', 'recording', 0, 0,
                    folder, json.dumps(payload), datetime.now(), datetime.now(),
                ),
            )

            cursor.execute(
                """
                SELECT j.*, c.channel_name, c.platform
                FROM jobs j LEFT JOIN channels c ON c.id = j.channel_id
                WHERE j.id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

        # Activity log uses its own connection — must be AFTER the parent
        # transaction commits, otherwise the FK to jobs.id fails.
        try:
            create_activity_log(
                user_id, 'job_started',
                f'Started Voice Typing: {title}', job_id, 'Voice Typing',
            )
        except Exception as log_err:
            print(f"voice_typing create_job: activity log failed (non-fatal): {log_err}")

        # Spawn the server-side Vosk worker. From this point on the user's
        # browser is optional — the transcript will appear in jobs.payload
        # as the worker progresses and the user can poll for it any time.
        try:
            from backend.pipeline.voice_typing.transcribe_vosk import spawn as spawn_vt
            spawn_vt(job_id, video_url, language)
        except Exception as spawn_err:
            # Worker spawn failure is non-fatal at the API level — we still
            # return the created job so the user can retry. But mark the job
            # as failed so the UI can show an error.
            print(f"voice_typing create_job: Vosk spawn failed: {spawn_err}")
            try:
                with get_db_cursor(commit=True) as cursor:
                    payload['transcribe_error'] = f'Worker spawn failed: {spawn_err}'
                    cursor.execute(
                        "UPDATE jobs SET status = 'failed', payload = %s::jsonb, updated_at = %s WHERE id = %s",
                        (json.dumps(payload), datetime.now(), job_id),
                    )
            except Exception:
                pass
            _mp_linkback_failed(job_id, f'Worker spawn failed: {spawn_err}')

        return jsonify({'success': True, 'job': _serialize_with_channel(row)}), 201
    except Exception as e:
        print(f"voice_typing create_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs/<job_id>/upload-audio', methods=['POST'])
@jwt_required()
def upload_audio(job_id):
    """Manual audio-upload fallback for when the YouTube downloader fails
    (geo-block, private video, RapidAPI quota, stale cookies, etc.).

    The user attaches a local audio file (mp3 / m4a / wav / ogg / opus /
    webm — anything ffmpeg can decode). We:

      1. Save the raw upload under the job's audio folder.
      2. Reset payload error state and flip status back to 'recording'.
      3. Spawn the upload-aware Vosk worker, which ffmpeg-converts the
         file to 16 kHz mono WAV and then runs Vosk on it.

    Allowed only when the job is currently in 'failed' or 'awaiting_review'
    status (i.e. the user has had a chance to see the previous error).
    """
    try:
        user_id = get_jwt_identity()

        if 'file' not in request.files:
            return jsonify({'error': 'No audio file in request (expected multipart field "file")'}), 400
        f = request.files['file']
        if not f or not f.filename:
            return jsonify({'error': 'Empty file upload'}), 400

        # Reasonable accept-list. ffmpeg can handle far more, but block obvious
        # mistakes like .txt or .pdf early.
        ALLOWED_EXT = {'.mp3', '.m4a', '.wav', '.ogg', '.opus', '.webm', '.mp4', '.aac', '.flac', '.wma'}
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(f.filename) or 'upload.bin'
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in ALLOWED_EXT:
            return jsonify({
                'error': f'Unsupported audio file type "{ext}". Allowed: {", ".join(sorted(ALLOWED_EXT))}'
            }), 400

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            current_status = row['status']
            if current_status not in ('failed', 'awaiting_review'):
                return jsonify({
                    'error': f'Cannot upload audio while job is "{current_status}". '
                             f'Stop the current run first or wait for it to finish.',
                }), 409

            payload = _payload_dict(row)
            language = payload.get('language', 'hi-IN')

            audio_folder = os.path.join('backend', 'job_files', job_id, 'audio')
            os.makedirs(audio_folder, exist_ok=True)
            source_path = os.path.join(audio_folder, f'uploaded{ext}')
            f.save(source_path)
            print(f"voice_typing upload_audio: saved {source_path} "
                  f"({os.path.getsize(source_path)} bytes)")

            # Reset status + clear stale errors. We use the JSONB merge
            # operator so this can't clobber the worker's writes.
            patch = {
                'transcribe_error': None,
                'transcribe_progress': 1,
                'transcript_text': '',
                'uploaded_audio_path': source_path,
                'uploaded_audio_name': safe_name,
            }
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'recording',
                    progress = 0,
                    payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                    updated_at = %s
                WHERE id = %s
                """,
                (json.dumps(patch), datetime.now(), job_id),
            )

            cursor.execute(
                """
                SELECT j.*, c.channel_name, c.platform
                FROM jobs j LEFT JOIN channels c ON c.id = j.channel_id
                WHERE j.id = %s
                """,
                (job_id,),
            )
            updated = cursor.fetchone()

        # Mirror the re-started transcribe state on the linked MP row
        # (overrides any prior 'failed' pill from the previous attempt).
        _mp_linkback_status(job_id, 'recording')

        # Spawn the upload-aware worker. Same fail-soft pattern as create_job.
        try:
            from backend.pipeline.voice_typing.transcribe_vosk import spawn_uploaded
            spawn_uploaded(job_id, source_path, language)
        except Exception as spawn_err:
            print(f"voice_typing upload_audio: spawn_uploaded failed: {spawn_err}")
            try:
                with get_db_cursor(commit=True) as cursor:
                    err_patch = {'transcribe_error': f'Worker spawn failed: {spawn_err}'}
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET status = 'failed',
                            payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (json.dumps(err_patch), datetime.now(), job_id),
                    )
            except Exception:
                pass
            _mp_linkback_failed(job_id, f'Worker spawn failed: {spawn_err}')
            return jsonify({'error': f'Worker spawn failed: {spawn_err}'}), 500

        return jsonify({'success': True, 'job': _serialize_with_channel(updated)}), 200
    except Exception as e:
        print(f"voice_typing upload_audio error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs/<job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    try:
        user_id = get_jwt_identity()
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT j.*, c.channel_name, c.platform
                FROM jobs j LEFT JOIN channels c ON c.id = j.channel_id
                WHERE j.id = %s AND j.user_id = %s AND j.tool_used = %s
                """,
                (job_id, user_id, 'Voice Typing'),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Job not found'}), 404
        return jsonify({'success': True, 'job': _serialize_with_channel(row)}), 200
    except Exception as e:
        print(f"voice_typing get_job error: {e}")
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs/<job_id>', methods=['PATCH'])
@jwt_required()
def patch_job(job_id):
    """Update transcript / title / language / status. While Vosk is still
    running (status='recording') the worker IS the source of truth for
    transcript text, so a transcriptText payload during that phase is
    rejected — the user must Stop first (status='awaiting_review') and only
    then can they edit. Setting status='awaiting_review' from the client
    short-circuits the Vosk worker (it polls the status between chunks).
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        new_transcript = data.get('transcriptText')
        new_translated = data.get('translatedText')
        new_arranged = data.get('arrangedText')
        new_title = data.get('title')
        new_language = data.get('language')
        new_status = data.get('status')

        # Allowed status transitions via PATCH:
        #   * → 'awaiting_review'  =  Stop button (recording → awaiting_review)
        #                             OR revert from awaiting_translate_review
        #                             OR revert from awaiting_arrange_review
        #                             back to awaiting_review.
        #   * → 'recording'        =  not currently used by the UI but kept for
        #                             completeness.
        if new_status and new_status not in ('recording', 'awaiting_review'):
            return jsonify({'error': 'Invalid status — only recording / awaiting_review are accepted via PATCH'}), 400

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] in ('bulk_started', 'completed'):
                return jsonify({'error': f"Job is {row['status']} — no further edits"}), 409
            if row['status'] == 'arranging':
                return jsonify({'error': 'Extract is in progress — wait for it to finish'}), 409
            if row['status'] == 'translating':
                return jsonify({'error': 'Translation is in progress — wait for it to finish'}), 409

            # Revert path: awaiting_translate_review / awaiting_arrange_review
            # → awaiting_review. While in those review phases, only their own
            # editable buffer (translatedText / arrangedText) and the revert
            # flip are accepted — block stray transcript / title / language
            # edits so the user doesn't accidentally rewrite earlier-stage
            # data they can no longer see.
            if (row['status'] in ('awaiting_translate_review', 'awaiting_arrange_review')
                    and new_status != 'awaiting_review'):
                if (new_transcript is not None
                        or new_title is not None
                        or new_language is not None):
                    return jsonify({
                        'error': f'Only the current stage text is editable while awaiting review ({row["status"]}).'
                    }), 409

            # Refuse transcript edits while the Vosk worker is running — it
            # would just be overwritten on the next 3-second flush. The user
            # must stop (status='awaiting_review') first.
            if (row['status'] == 'recording'
                    and new_transcript is not None
                    and new_status != 'awaiting_review'):
                return jsonify({
                    'error': 'Transcript is locked while server transcription is running. Press Stop first.'
                }), 409

            # Translated-text edits only make sense in the translate-review phase.
            if new_translated is not None and row['status'] != 'awaiting_translate_review':
                return jsonify({
                    'error': f'Translated text is only editable while awaiting translate review (currently {row["status"]}).'
                }), 409

            # Arranged-text edits only make sense in the arrange-review phase.
            if new_arranged is not None and row['status'] != 'awaiting_arrange_review':
                return jsonify({
                    'error': f'Arranged text is only editable while awaiting arrange review (currently {row["status"]}).'
                }), 409

            # Build a JSONB merge patch instead of a full read-modify-write so
            # this PATCH is race-safe with the server-side Vosk worker (which
            # is also writing transcript_text + transcribe_progress into
            # payload via `payload || …` — see backend/pipeline/voice_typing/
            # transcribe_vosk.py).
            payload_patch: dict = {}
            if new_transcript is not None:
                payload_patch['transcript_text'] = new_transcript
            if new_translated is not None:
                payload_patch['translated_text'] = new_translated
            if new_arranged is not None:
                payload_patch['arranged_text'] = new_arranged
            if new_language is not None:
                payload_patch['language'] = new_language

            updates = [
                "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb",
                "updated_at = %s",
            ]
            params = [json.dumps(payload_patch), datetime.now()]
            if new_title is not None and new_title.strip():
                updates.append("title = %s")
                params.append(new_title.strip())
            if new_status:
                updates.append("status = %s")
                params.append(new_status)
            params.append(job_id)

            cursor.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = %s",
                params,
            )

            cursor.execute(
                """
                SELECT j.*, c.channel_name, c.platform
                FROM jobs j LEFT JOIN channels c ON c.id = j.channel_id
                WHERE j.id = %s
                """,
                (job_id,),
            )
            updated = cursor.fetchone()

        return jsonify({'success': True, 'job': _serialize_with_channel(updated)}), 200
    except Exception as e:
        print(f"voice_typing patch_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs/<job_id>', methods=['DELETE'])
@jwt_required()
def delete_job(job_id):
    try:
        user_id = get_jwt_identity()
        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            folder = row.get('folder_path')
            cursor.execute("DELETE FROM job_steps WHERE job_id = %s", (job_id,))
            cursor.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
            if folder and os.path.exists(folder):
                import shutil
                shutil.rmtree(folder, ignore_errors=True)
        # Detach any Media Presence row that linked to this transcribe job
        # so its Voice/AI buttons reappear.
        try:
            from backend.api.media_presence import unlink_deleted_job
            unlink_deleted_job(job_id)
        except Exception as _mp_err:
            print(f"[voice_typing.delete_job] MP unlink failed: {_mp_err}")
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"voice_typing delete_job error: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# 5-step pipeline (mirrors AI Transcribe — see ai_transcribe_service.py):
#   Step 3: /jobs/<id>/translate      — OpenAI translate-to-English; parks at
#                                       awaiting_translate_review
#   Step 4: /jobs/<id>/arrange        — OpenAI extract Pradip's analysis; parks
#                                       at awaiting_arrange_review
#   Step 5: /jobs/<id>/send-to-bulk   — spawns Bulk Rationale child from the
#                                       (possibly user-edited) arrangement
# ---------------------------------------------------------------------------

def _translate_only(job_id, transcript_text):
    """Background Step 3 worker: translate the user-edited transcript to
    English with GPT-4o. On success parks at status='awaiting_translate_review'
    so the user can review and edit the English text before extracting
    Pradip's analysis. Reuses the AI Transcribe translator (same prompt and
    model) so both tools translate identically.
    """
    from backend.services.ai_transcribe_service import _translate_text

    print(f"\n🌐  Voice Typing job {job_id}: translating transcript to English...")
    try:
        translated = _translate_text(transcript_text)
    except Exception as exc:
        err = str(exc)
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
            row = cursor.fetchone()
            payload = _payload_dict(row) if row else {}
            payload['translate_error'] = err
            cursor.execute(
                "UPDATE jobs SET status = 'failed', payload = %s::jsonb, updated_at = %s WHERE id = %s",
                (json.dumps(payload), datetime.now(), job_id),
            )
        _mp_linkback_failed(job_id, f'Translate failed: {err}')
        print(f"❌ Voice Typing job {job_id} failed during translate: {err}")
        return

    parked = False
    with get_db_cursor(commit=True) as cursor:
        cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
        row = cursor.fetchone()
        payload = _payload_dict(row) if row else {}
        payload['translated_text'] = translated
        payload.pop('translate_error', None)
        # Guarded — only park if we're still the active translating worker.
        cursor.execute(
            """UPDATE jobs
               SET status = 'awaiting_translate_review',
                   payload = %s::jsonb,
                   updated_at = %s
               WHERE id = %s AND status = 'translating'""",
            (json.dumps(payload), datetime.now(), job_id),
        )
        parked = cursor.rowcount > 0
    if parked:
        _mp_linkback_status(job_id, 'awaiting_translate_review')
    print(f"✅ Voice Typing {job_id}: translation done — awaiting user review")


def _arrange_only(job_id, transcript_text):
    """Background Step 4 worker. Runs the existing arrange_transcript pipeline
    (Pradip-analysis extraction) on the user-edited *English* text and parks
    the job at status='awaiting_arrange_review' so the user can review and
    edit the stock-wise arrangement before pushing into Bulk Rationale."""
    from backend.pipeline.voice_typing.arrange_transcript import run as arrange_run

    print(f"\n🎙️  Voice Typing job {job_id}: extracting Pradip's analysis via OpenAI...")
    result = arrange_run(transcript_text)

    if not result.get('success'):
        err = result.get('error') or 'Unknown error'
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
            row = cursor.fetchone()
            payload = _payload_dict(row) if row else {}
            payload['arrange_error'] = err
            cursor.execute(
                "UPDATE jobs SET status = 'failed', payload = %s::jsonb, updated_at = %s WHERE id = %s",
                (json.dumps(payload), datetime.now(), job_id),
            )
        _mp_linkback_failed(job_id, f'Extract failed: {err}')
        print(f"❌ Voice Typing job {job_id} failed during arrange: {err}")
        return

    arranged = result['arranged_text']

    parked = False
    with get_db_cursor(commit=True) as cursor:
        cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
        row = cursor.fetchone()
        payload = _payload_dict(row) if row else {}
        payload['arranged_text'] = arranged
        payload.pop('arrange_error', None)
        # Guarded — only park if we're still the active extracting worker.
        # Prevents a stale thread (from a quickly-superseded re-extract) from
        # overwriting a newer arranged_text after another worker already
        # parked the job at awaiting_arrange_review.
        cursor.execute(
            """UPDATE jobs
               SET status = 'awaiting_arrange_review',
                   payload = %s::jsonb,
                   updated_at = %s
               WHERE id = %s AND status = 'arranging'""",
            (json.dumps(payload), datetime.now(), job_id),
        )
        arrange_parked = cursor.rowcount > 0
    if arrange_parked:
        _mp_linkback_status(job_id, 'awaiting_arrange_review')
    print(f"✅ Voice Typing {job_id}: arrange done — awaiting user review")


def _spawn_bulk_from_arranged(job_id, user_id, arranged_text, channel_id, call_date, call_time, title):
    """Background worker for stage 2. Creates + runs a child Bulk Rationale job
    from the (possibly user-edited) arrangement text."""
    from backend.api.bulk_rationale import run_bulk_pipeline, BULK_STEPS

    bulk_job_id = f"bulk-{uuid.uuid4().hex[:8]}"
    bulk_folder = f"backend/job_files/{bulk_job_id}"
    os.makedirs(bulk_folder, exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, 'analysis'), exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, 'charts'), exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, 'pdf'), exist_ok=True)

    with open(os.path.join(bulk_folder, 'bulk-input.txt'), 'w', encoding='utf-8') as f:
        f.write(arranged_text)

    bulk_title = f"{title} (from Voice Typing)"

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO jobs (id, youtube_url, title, channel_id, date, time,
                              user_id, tool_used, status, progress, current_step,
                              folder_path, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                bulk_job_id, '', bulk_title, channel_id, call_date, call_time,
                user_id, 'Bulk Rationale', 'processing', 0, 0, bulk_folder,
                datetime.now(), datetime.now(),
            ),
        )
        for step in BULK_STEPS:
            cursor.execute(
                "INSERT INTO job_steps (job_id, step_number, step_name, status, created_at) VALUES (%s, %s, %s, %s, %s)",
                (bulk_job_id, step['step_number'], step['name'], 'pending', datetime.now()),
            )

        # Update parent voice-typing job. Status was atomically flipped to
        # 'bulk_started' by send_to_bulk() before this thread was spawned, so
        # we ONLY patch the bulk_job_id + progress here (and use a JSONB merge
        # so we don't clobber concurrent updates).
        payload_patch = {
            'arranged_text': arranged_text,
            'bulk_job_id': bulk_job_id,
        }
        cursor.execute(
            """
            UPDATE jobs
            SET progress = 100,
                payload = (COALESCE(payload, '{}'::jsonb) - 'arrange_error') || %s::jsonb,
                updated_at = %s
            WHERE id = %s
            """,
            (json.dumps(payload_patch), datetime.now(), job_id),
        )

        # If this Voice Typing job was started from a Media Presence entry,
        # link the new Bulk child back to that row so the MP table reflects
        # transcribe done + rationale started without the user having to
        # press anything else.
        cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
        parent_row = cursor.fetchone()
        parent_payload = _payload_dict(parent_row) if parent_row else {}
        media_presence_id = parent_payload.get('media_presence_id')
        if media_presence_id:
            try:
                cursor.execute(
                    """
                    UPDATE media_presence
                    SET transcribe_status = 'completed',
                        transcript_text = %s,
                        rationale_job_id = %s,
                        rationale_status = 'started',
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        arranged_text, bulk_job_id, datetime.now(),
                        media_presence_id,
                    ),
                )
            except Exception as mp_err:
                print(f"⚠️  Voice Typing {job_id}: MP {media_presence_id} link update failed: {mp_err}")

        create_activity_log(
            user_id, 'job_started',
            f'Voice Typing → Bulk Rationale: {bulk_title}',
            bulk_job_id, 'Bulk Rationale',
        )

    # Spawn bulk pipeline thread
    t = threading.Thread(
        target=run_bulk_pipeline,
        args=(bulk_job_id, bulk_folder, call_date, call_time),
    )
    t.daemon = True
    t.start()
    print(f"✅ Voice Typing {job_id}: spawned Bulk Rationale {bulk_job_id}")


@voice_typing_bp.route('/jobs/<job_id>/translate', methods=['POST'])
@jwt_required()
def translate_job(job_id):
    """Step 3: Persist final raw transcript edits, then run OpenAI translate
    in the background. Result parks at awaiting_translate_review for user
    review. Allowed only from awaiting_review (the post-Vosk edit phase) so
    the translation always runs against text the user has had a chance to
    fix.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        final_text = data.get('transcriptText')

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] in ('translating', 'arranging', 'bulk_started', 'completed'):
                return jsonify({'error': f"Already {row['status']}"}), 409
            if row['status'] not in ('awaiting_review', 'awaiting_translate_review',
                                     'awaiting_arrange_review', 'failed'):
                return jsonify({
                    'error': f"Translate is only allowed after the transcript is reviewed (current status: {row['status']})."
                }), 409

            payload = _payload_dict(row)
            if final_text is not None:
                payload['transcript_text'] = final_text

            transcript_to_use = payload.get('transcript_text', '')
            if not transcript_to_use.strip():
                return jsonify({'error': 'Transcript is empty'}), 400

            payload.pop('translate_error', None)
            # Atomic compare-and-swap so two concurrent /translate requests
            # can't both spawn a _translate_only worker.
            cursor.execute(
                """UPDATE jobs
                   SET status = 'translating', payload = %s::jsonb, updated_at = %s
                   WHERE id = %s
                     AND status IN ('awaiting_review',
                                    'awaiting_translate_review',
                                    'awaiting_arrange_review',
                                    'failed')""",
                (json.dumps(payload), datetime.now(), job_id),
            )
            if cursor.rowcount == 0:
                return jsonify({
                    'error': 'Another translate request is already in flight or the job has moved on. Refresh and try again.',
                }), 409

        _mp_linkback_status(job_id, 'translating')

        t = threading.Thread(
            target=_translate_only,
            args=(job_id, transcript_to_use),
        )
        t.daemon = True
        t.start()

        return jsonify({
            'success': True,
            'message': 'Translating transcript — review the result when it appears.',
        }), 202
    except Exception as e:
        print(f"voice_typing translate_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs/<job_id>/arrange', methods=['POST'])
@jwt_required()
def arrange_job(job_id):
    """Step 4 (Extract Pradip Halder's Analysis): Persist final translated
    text edits, then run the OpenAI extract pipeline in the background.
    Result parks at awaiting_arrange_review for user review.

    Allowed from awaiting_translate_review (normal path) or
    awaiting_arrange_review (re-extract). Legacy jobs that pre-date the
    translate step land in awaiting_review — they need to translate first.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        translated_in = data.get('translatedText')
        # Backwards-compat: older clients sent transcriptText to /arrange.
        legacy_transcript_in = data.get('transcriptText')

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] in ('arranging', 'bulk_started', 'completed'):
                return jsonify({'error': f"Already {row['status']}"}), 409
            if row['status'] not in ('awaiting_translate_review',
                                     'awaiting_arrange_review', 'failed'):
                return jsonify({
                    'error': f"Extract is only allowed after the translation is reviewed (current status: {row['status']}). Please translate first.",
                }), 409

            payload = _payload_dict(row)
            if translated_in is not None:
                payload['translated_text'] = translated_in
            elif legacy_transcript_in is not None and not payload.get('translated_text'):
                # Older client; treat its transcriptText as already-English.
                payload['translated_text'] = legacy_transcript_in

            translated_to_use = payload.get('translated_text', '')
            if not translated_to_use.strip():
                return jsonify({'error': 'Translated text is empty'}), 400

            payload.pop('arrange_error', None)
            # Atomic compare-and-swap so two concurrent /arrange requests can't
            # both spawn an _arrange_only worker. Only the request that finds
            # the job in awaiting_translate_review / awaiting_arrange_review /
            # failed wins and flips it to 'arranging'.
            cursor.execute(
                """UPDATE jobs
                   SET status = 'arranging', payload = %s::jsonb, updated_at = %s
                   WHERE id = %s
                     AND status IN ('awaiting_translate_review',
                                    'awaiting_arrange_review',
                                    'failed')""",
                (json.dumps(payload), datetime.now(), job_id),
            )
            if cursor.rowcount == 0:
                return jsonify({
                    'error': 'Another extract request is already in flight or the job has moved on. Refresh and try again.',
                }), 409

        _mp_linkback_status(job_id, 'arranging')

        t = threading.Thread(
            target=_arrange_only,
            args=(job_id, translated_to_use),
        )
        t.daemon = True
        t.start()

        return jsonify({
            'success': True,
            'message': "Extracting Pradip's analysis — review the result when it appears.",
        }), 202
    except Exception as e:
        print(f"voice_typing arrange_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@voice_typing_bp.route('/jobs/<job_id>/send-to-bulk', methods=['POST'])
@jwt_required()
def send_to_bulk(job_id):
    """Stage 2: User reviewed/edited the arrangement. Spawn a Bulk Rationale
    child job from the final arrangement text.

    RACE-SAFETY: We do a single atomic UPDATE that both validates the status
    transition (awaiting_arrange_review → bulk_started) AND persists the
    user's final arranged text in one shot, with a RETURNING clause. If two
    concurrent requests arrive, only one will see rowcount=1; the other gets
    409 and no duplicate child job is spawned. The background worker
    `_spawn_bulk_from_arranged` therefore does NOT touch status itself — it
    only patches in `bulk_job_id` once it has one.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        edited_arranged = data.get('arrangedText')

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] in ('bulk_started', 'completed'):
                return jsonify({'error': f"Already {row['status']}"}), 409
            if row['status'] != 'awaiting_arrange_review':
                return jsonify({
                    'error': f"Arrange must be reviewed first (job status is {row['status']})",
                }), 409

            existing_payload = _payload_dict(row)
            arranged_to_use = (
                edited_arranged
                if edited_arranged is not None
                else existing_payload.get('arranged_text', '')
            )
            if not (arranged_to_use or '').strip():
                return jsonify({'error': 'Arranged text is empty'}), 400

            # Build a JSONB merge patch — keeps us race-safe with the
            # arranged-text autosave PATCH that may still be in flight.
            payload_patch = {'arranged_text': arranged_to_use}

            # Atomic guard: only flip if we're STILL at awaiting_arrange_review.
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'bulk_started',
                    payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                    updated_at = %s
                WHERE id = %s AND status = 'awaiting_arrange_review'
                RETURNING id
                """,
                (json.dumps(payload_patch), datetime.now(), job_id),
            )
            if cursor.fetchone() is None:
                # Lost the race to a concurrent send-to-bulk request.
                return jsonify({
                    'error': 'Send already in progress for this job',
                }), 409

            channel_id = row['channel_id']
            call_date = row['date']
            call_time = row['time']
            title = row.get('title') or job_id

        t = threading.Thread(
            target=_spawn_bulk_from_arranged,
            args=(job_id, user_id, arranged_to_use, channel_id, call_date, call_time, title),
        )
        t.daemon = True
        t.start()

        return jsonify({
            'success': True,
            'message': 'Spawning Bulk Rationale child job…',
        }), 202
    except Exception as e:
        print(f"voice_typing send_to_bulk error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Create-from-upload — bypass YouTube entirely, take an mp3/wav directly
# ---------------------------------------------------------------------------

@voice_typing_bp.route('/jobs/upload', methods=['POST'])
@jwt_required()
def create_from_upload():
    """Create a Voice Typing job directly from an uploaded audio file. No
    YouTube download is involved — Vosk runs on the upload directly."""
    try:
        user_id = get_jwt_identity()
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded (field name must be "file")'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        ALLOWED = {'.mp3', '.m4a', '.wav', '.ogg', '.opus', '.webm',
                   '.mp4', '.aac', '.flac', '.wma'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED:
            return jsonify({'error': f'Unsupported file type: {ext}'}), 400

        title = (request.form.get('title') or '').strip() or 'Voice Typing (uploaded audio)'
        channel_id = request.form.get('channelId')
        call_date = request.form.get('callDate')
        call_time = request.form.get('callTime') or None
        language = request.form.get('language', 'hi-IN')

        if not channel_id:
            return jsonify({'error': 'channelId is required'}), 400
        if not call_date:
            return jsonify({'error': 'callDate is required'}), 400
        try:
            channel_id_int = int(channel_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'channelId must be an integer'}), 400

        # Save the upload into a fresh job folder.
        job_id = f"voice-{uuid.uuid4().hex[:8]}"
        folder = f"backend/job_files/{job_id}"
        os.makedirs(folder, exist_ok=True)
        upload_path = os.path.join(folder, f"input{ext}")
        file.save(upload_path)

        payload = {
            'transcript_text': '',
            'transcribe_progress': 0,
            'language': language,
            'uploaded_audio_path': upload_path,
        }

        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO jobs (id, youtube_url, title, channel_id, date, time,
                                  user_id, tool_used, status, progress, current_step,
                                  folder_path, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    job_id, '', title, channel_id_int, call_date, call_time,
                    user_id, 'Voice Typing', 'recording', 0, 0, folder,
                    json.dumps(payload), datetime.now(), datetime.now(),
                ),
            )
            cursor.execute(
                """
                SELECT j.*, c.channel_name, c.platform
                FROM jobs j LEFT JOIN channels c ON c.id = j.channel_id
                WHERE j.id = %s
                """,
                (job_id,),
            )
            created = cursor.fetchone()

        # Spawn the upload-mode Vosk worker.
        from backend.pipeline.voice_typing.transcribe_vosk import spawn_uploaded
        spawn_uploaded(job_id, upload_path, language)

        return jsonify({'success': True, 'job': _serialize_with_channel(created)}), 200
    except Exception as e:
        print(f"voice_typing create_from_upload error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
