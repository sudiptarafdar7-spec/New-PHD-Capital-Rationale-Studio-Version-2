"""
Live Transcribe API Endpoints

Live Transcribe captures a YouTube *live* stream's audio on the SERVER,
streams the audio into AssemblyAI's Realtime websocket for live partial
captions, and on stream end runs a second AssemblyAI pass with
speaker_labels=true to produce a diarized timestamped transcript.

The user reviews the diarized transcript, then a third (OpenAI) pass
extracts only Pradip Halder's stock analyses in the strict line-pair
format Bulk Rationale needs. Finally a Bulk Rationale child job is
spawned — same hand-off as Voice Typing.

Lifecycle:
  live                       - capture worker is recording the live stream and
                               streaming partials into jobs.payload.live_transcript
  awaiting_review            - stream ended (or user pressed Stop). Diarized
                               transcript is being / has been computed; user
                               reviews & edits.
  extracting                 - Step 3: OpenAI is extracting Pradip Halder's
                               stock analyses.
  awaiting_extract_review    - Step 3 done — extracted text editable.
  bulk_started               - Step 4: Bulk Rationale child spawned.
  failed                     - Capture / extract / spawn failed.

Job id prefix: 'live-'.   tool_used = 'Live Transcribe'.
"""

import os
import json
import uuid
import threading
from datetime import datetime

from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from backend.api import live_transcribe_bp
from backend.utils.database import get_db_cursor
from backend.api.activity_logs import create_activity_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload_dict(row):
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
        (job_id, user_id, 'Live Transcribe'),
    )
    return cursor.fetchone()


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
        'liveUrl': payload.get('live_url') or job.get('youtube_url') or '',
        'liveTranscript': payload.get('live_transcript', ''),
        'diarizedTranscript': payload.get('diarized_transcript', ''),
        'arrangedText': payload.get('arranged_text', ''),
        'bulkJobId': payload.get('bulk_job_id'),
        'arrangeError': payload.get('arrange_error'),
        'transcribeError': payload.get('transcribe_error'),
        'diarizeError': payload.get('diarize_error'),
        'transcribeProgress': payload.get('transcribe_progress', 0),
    }


def _serialize_with_channel(row):
    base = _serialize(row)
    base['channelName'] = row.get('channel_name')
    base['platform'] = row.get('platform')
    if 'bulk_status' in row:
        base['bulkJobStatus'] = row.get('bulk_status')
    if 'bulk_progress' in row:
        base['bulkJobProgress'] = row.get('bulk_progress')
    return base


# ---------------------------------------------------------------------------
# Step 1: fetch metadata (delegate to the existing YouTube Data API helper)
# ---------------------------------------------------------------------------

@live_transcribe_bp.route('/fetch-metadata', methods=['POST'])
@jwt_required()
def fetch_metadata():
    """Look up a YouTube live URL via the YouTube Data API. Returns the same
    shape the Voice Typing / Media Rationale fetch helpers already return,
    so the frontend's existing prefill logic just works."""
    try:
        data = request.get_json(silent=True) or {}
        live_url = (data.get('liveUrl') or data.get('youtubeUrl') or '').strip()
        if not live_url:
            return jsonify({'error': 'liveUrl is required'}), 400

        from backend.pipeline.fetch_video_data import fetch_video_metadata
        meta = fetch_video_metadata(live_url)

        return jsonify({
            'success': True,
            'data': {
                'videoId': meta.get('video_id'),
                'title': meta.get('title'),
                'channelName': meta.get('channel_name'),
                'uploadDate': meta.get('date'),
                'uploadTime': meta.get('time'),
                'duration': meta.get('duration'),
                'thumbnail': meta.get('thumbnail'),
            },
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@live_transcribe_bp.route('/jobs', methods=['GET'])
@jwt_required()
def list_jobs():
    try:
        user_id = get_jwt_identity()
        with get_db_cursor() as cursor:
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
                (user_id, 'Live Transcribe'),
            )
            rows = cursor.fetchall()
        return jsonify({'success': True, 'jobs': [_serialize_with_channel(r) for r in rows]}), 200
    except Exception as e:
        print(f"live_transcribe list_jobs error: {e}")
        return jsonify({'error': str(e)}), 500


@live_transcribe_bp.route('/jobs', methods=['POST'])
@jwt_required()
def create_job():
    """Create a new Live Transcribe job. The YouTube live URL is REQUIRED.
    On success the server immediately spawns the live capture worker —
    closing the browser does not interrupt the transcription."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}

        channel_id = data.get('channelId')
        call_date = data.get('callDate')
        call_time = data.get('callTime') or '10:00:00'
        title = (data.get('title') or '').strip()
        live_url = (data.get('liveUrl') or '').strip()

        if not channel_id or not call_date:
            return jsonify({'error': 'Channel and date are required'}), 400
        if not live_url:
            return jsonify({'error': 'YouTube live URL is required'}), 400

        # Parity with Media Presence start-live-transcribe: validate the URL
        # is actually a live YouTube broadcast before spawning the worker so
        # we reject pre-recorded VODs / non-YouTube URLs up front instead of
        # letting yt-dlp fail mid-capture with an opaque error.
        from backend.api.media_presence import _probe_youtube_is_live
        is_live, live_err = _probe_youtube_is_live(live_url)
        if not is_live:
            return jsonify({
                'error': live_err or (
                    'URL does not appear to be a live YouTube stream. '
                    'Live Transcribe only supports live broadcasts — use '
                    'AI Transcribe or Voice Typing for already-ended videos.'
                ),
            }), 400

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

            job_id = f"live-{uuid.uuid4().hex[:8]}"
            folder = f"backend/job_files/{job_id}"
            os.makedirs(folder, exist_ok=True)
            os.makedirs(os.path.join(folder, 'audio'), exist_ok=True)

            payload = {
                'live_url': live_url,
                'live_transcript': '',
                'diarized_transcript': '',
                'arranged_text': '',
                'transcribe_progress': 0,
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
                    job_id, live_url, title, channel_id, call_date, call_time,
                    user_id, 'Live Transcribe', 'live', 0, 0,
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

        try:
            create_activity_log(
                user_id, 'job_started',
                f'Started Live Transcribe: {title}', job_id, 'Live Transcribe',
            )
        except Exception as log_err:
            print(f"live_transcribe create_job: activity log failed (non-fatal): {log_err}")

        try:
            from backend.pipeline.live_transcribe.realtime_transcribe import spawn as spawn_live
            spawn_live(job_id, live_url)
        except Exception as spawn_err:
            print(f"live_transcribe create_job: live worker spawn failed: {spawn_err}")
            try:
                with get_db_cursor(commit=True) as cursor:
                    err_patch = {'transcribe_error': f'Worker spawn failed: {spawn_err}'}
                    cursor.execute(
                        """
                        UPDATE jobs SET status = 'failed',
                                        payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                                        updated_at = %s
                        WHERE id = %s
                        """,
                        (json.dumps(err_patch), datetime.now(), job_id),
                    )
            except Exception:
                pass

        return jsonify({'success': True, 'job': _serialize_with_channel(row)}), 201
    except Exception as e:
        print(f"live_transcribe create_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@live_transcribe_bp.route('/jobs/<job_id>', methods=['GET'])
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
                (job_id, user_id, 'Live Transcribe'),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Job not found'}), 404
        return jsonify({'success': True, 'job': _serialize_with_channel(row)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@live_transcribe_bp.route('/jobs/<job_id>', methods=['PATCH'])
@jwt_required()
def patch_job(job_id):
    """Update transcripts / status. Allowed transitions:
       * → 'awaiting_review'  : Stop button (live → awaiting_review)
    Edits to diarizedTranscript or arrangedText only allowed in their
    respective review phases."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        new_diarized = data.get('diarizedTranscript')
        new_arranged = data.get('arrangedText')
        new_title = data.get('title')
        new_status = data.get('status')

        # Strict transition gate — only the live → awaiting_review flip is
        # allowed via PATCH (kept for legacy clients; new code should use
        # POST /jobs/<id>/stop). Extract goes via /extract; bulk via /send-to-bulk.
        if new_status is not None and new_status != 'awaiting_review':
            return jsonify({'error': 'Invalid status — only awaiting_review accepted via PATCH'}), 400

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] in ('bulk_started', 'completed'):
                return jsonify({'error': f"Job is {row['status']} — no further edits"}), 409
            if row['status'] == 'extracting':
                return jsonify({'error': 'Extraction is in progress — wait for it to finish'}), 409
            # Mirror Voice Typing's tighter source-state guard: the only
            # legal source for status='awaiting_review' via PATCH is 'live'.
            if new_status == 'awaiting_review' and row['status'] != 'live':
                return jsonify({
                    'error': f"Cannot transition to awaiting_review from {row['status']} — job must be live."
                }), 409

            # Diarized edits only allowed during review phase.
            if new_diarized is not None and row['status'] not in ('awaiting_review',):
                return jsonify({
                    'error': f'Diarized transcript is only editable during review (currently {row["status"]}).'
                }), 409

            if new_arranged is not None and row['status'] != 'awaiting_extract_review':
                return jsonify({
                    'error': f'Arranged text is only editable while awaiting arrange review (currently {row["status"]}).'
                }), 409

            payload_patch: dict = {}
            if new_diarized is not None:
                payload_patch['diarized_transcript'] = new_diarized
            if new_arranged is not None:
                payload_patch['arranged_text'] = new_arranged

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

            cursor.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = %s", params)

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
        print(f"live_transcribe patch_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@live_transcribe_bp.route('/jobs/<job_id>', methods=['DELETE'])
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
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Step 3: extract Pradip Halder's analyses (background)
# ---------------------------------------------------------------------------

def _extract_only(job_id, transcript_text):
    from backend.pipeline.live_transcribe.extract_pradip_analysis import run as extract_run

    print(f"\n📡 Live Transcribe job {job_id}: extracting Pradip's analysis...")
    result = extract_run(transcript_text)

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
        print(f"❌ Live Transcribe {job_id} failed during extract: {err}")
        return

    arranged = result['arranged_text']

    with get_db_cursor(commit=True) as cursor:
        cursor.execute("SELECT payload FROM jobs WHERE id = %s", (job_id,))
        row = cursor.fetchone()
        payload = _payload_dict(row) if row else {}
        payload['arranged_text'] = arranged
        payload.pop('arrange_error', None)
        cursor.execute(
            "UPDATE jobs SET status = 'awaiting_extract_review', payload = %s::jsonb, updated_at = %s WHERE id = %s",
            (json.dumps(payload), datetime.now(), job_id),
        )
    print(f"✅ Live Transcribe {job_id}: extract done — awaiting user review")


@live_transcribe_bp.route('/jobs/<job_id>/stop', methods=['POST'])
@jwt_required()
def stop_job(job_id):
    """Dedicated Stop endpoint — flips a 'live' job to 'awaiting_review'
    so the capture worker tears down on its next poll. Thin wrapper over
    the same guarded transition the PATCH route uses, exposed as a
    distinct verb so the frontend doesn't have to know the internal
    status vocabulary."""
    try:
        user_id = get_jwt_identity()
        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] != 'live':
                return jsonify({
                    'error': f"Stop only allowed while job is live (current: {row['status']}).",
                }), 409
            cursor.execute(
                "UPDATE jobs SET status = 'awaiting_review', updated_at = %s "
                "WHERE id = %s AND status = 'live'",
                (datetime.now(), job_id),
            )
        return jsonify({'success': True, 'status': 'awaiting_review'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@live_transcribe_bp.route('/jobs/<job_id>/extract', methods=['POST'])
@jwt_required()
def extract_job(job_id):
    """Step 3: persist final diarized transcript, then run OpenAI extraction
    in the background. Result parks at awaiting_extract_review."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        final_text = data.get('diarizedTranscript')

        with get_db_cursor(commit=True) as cursor:
            row = _job_owner_check(cursor, job_id, user_id)
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if row['status'] != 'awaiting_review':
                return jsonify({
                    'error': (
                        f"Extract is only allowed once the live capture has finished "
                        f"and the diarized transcript is ready for review "
                        f"(current status: {row['status']})."
                    ),
                }), 409

            payload = _payload_dict(row)
            if final_text is not None:
                payload['diarized_transcript'] = final_text

            transcript_to_use = (
                payload.get('diarized_transcript')
                or payload.get('live_transcript')
                or ''
            )
            if not transcript_to_use.strip():
                return jsonify({'error': 'Transcript is empty'}), 400

            payload.pop('arrange_error', None)
            cursor.execute(
                "UPDATE jobs SET status = 'extracting', payload = %s::jsonb, updated_at = %s WHERE id = %s",
                (json.dumps(payload), datetime.now(), job_id),
            )

        t = threading.Thread(target=_extract_only, args=(job_id, transcript_to_use), daemon=True)
        t.start()

        return jsonify({
            'success': True,
            'message': 'Extracting Pradip\'s analysis — review the result when it appears.',
        }), 202
    except Exception as e:
        print(f"live_transcribe extract_job error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Step 4: send to Bulk Rationale (background spawn)
# ---------------------------------------------------------------------------

def _spawn_bulk_from_arranged(job_id, user_id, arranged_text, channel_id, call_date, call_time, title):
    from backend.api.bulk_rationale import run_bulk_pipeline, BULK_STEPS

    bulk_job_id = f"bulk-{uuid.uuid4().hex[:8]}"
    bulk_folder = f"backend/job_files/{bulk_job_id}"
    os.makedirs(bulk_folder, exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, 'analysis'), exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, 'charts'), exist_ok=True)
    os.makedirs(os.path.join(bulk_folder, 'pdf'), exist_ok=True)

    with open(os.path.join(bulk_folder, 'bulk-input.txt'), 'w', encoding='utf-8') as f:
        f.write(arranged_text)

    # Use the unified job-title format (no hand-appended suffix). The parent
    # Live Transcribe job already encodes platform/channel/date/time via
    # build_job_title(); reuse the same string for the spawned Bulk child so
    # the dashboard's <JobTitle> renderer treats it consistently.
    bulk_title = title

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

        # MP linkback (mirrors Voice Typing).
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
                    (arranged_text, bulk_job_id, datetime.now(), media_presence_id),
                )
            except Exception as mp_err:
                print(f"⚠️  Live Transcribe {job_id}: MP {media_presence_id} link update failed: {mp_err}")

        create_activity_log(
            user_id, 'job_started',
            f'Live Transcribe → Bulk Rationale: {bulk_title}',
            bulk_job_id, 'Bulk Rationale',
        )

    t = threading.Thread(
        target=run_bulk_pipeline,
        args=(bulk_job_id, bulk_folder, call_date, call_time),
    )
    t.daemon = True
    t.start()
    print(f"✅ Live Transcribe {job_id}: spawned Bulk Rationale {bulk_job_id}")


@live_transcribe_bp.route('/jobs/<job_id>/send-to-bulk', methods=['POST'])
@jwt_required()
def send_to_bulk(job_id):
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
            if row['status'] != 'awaiting_extract_review':
                return jsonify({
                    'error': f"Extract must be reviewed first (job status is {row['status']})",
                }), 409

            existing_payload = _payload_dict(row)
            arranged_to_use = (
                edited_arranged
                if edited_arranged is not None
                else existing_payload.get('arranged_text', '')
            )
            if not (arranged_to_use or '').strip():
                return jsonify({'error': 'Arranged text is empty'}), 400

            payload_patch = {'arranged_text': arranged_to_use}
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'bulk_started',
                    payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb,
                    updated_at = %s
                WHERE id = %s AND status = 'awaiting_extract_review'
                RETURNING id
                """,
                (json.dumps(payload_patch), datetime.now(), job_id),
            )
            if cursor.fetchone() is None:
                return jsonify({'error': 'Send already in progress for this job'}), 409

            channel_id = row['channel_id']
            call_date = row['date']
            call_time = row['time']
            title = row.get('title') or job_id

        # Wrap _spawn_bulk_from_arranged so any unhandled exception
        # rolls the parent job back to awaiting_extract_review with an
        # error stamped onto the payload — otherwise the parent would
        # be stuck in 'bulk_started' forever with no child bulk_job_id.
        def _safe_spawn():
            try:
                _spawn_bulk_from_arranged(
                    job_id, user_id, arranged_to_use, channel_id,
                    call_date, call_time, title,
                )
            except Exception as spawn_err:
                print(f"❌ Live Transcribe {job_id} bulk spawn failed: {spawn_err}")
                import traceback as _tb
                _tb.print_exc()
                try:
                    err_msg = str(spawn_err)[:1000]
                    with get_db_cursor(commit=True) as c2:
                        c2.execute(
                            """
                            UPDATE jobs
                            SET status = 'awaiting_extract_review',
                                payload = COALESCE(payload, '{}'::jsonb)
                                          || jsonb_build_object('arrange_error', %s),
                                updated_at = %s
                            WHERE id = %s AND status = 'bulk_started'
                            """,
                            (f"Bulk Rationale spawn failed: {err_msg}", datetime.now(), job_id),
                        )
                except Exception as roll_err:
                    print(f"❌ Live Transcribe {job_id} could not roll back after spawn failure: {roll_err}")

        t = threading.Thread(target=_safe_spawn, daemon=True)
        t.start()

        return jsonify({'success': True, 'message': 'Spawning Bulk Rationale child job…'}), 202
    except Exception as e:
        print(f"live_transcribe send_to_bulk error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
