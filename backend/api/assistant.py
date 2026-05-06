"""
Ayushi - the in-app AI assistant.

Three endpoints, all JWT-protected:

- POST /api/v1/assistant/chat
    Body: { messages: [{role,content}, ...], currentPage?, jobContextId? }
    Returns: { message, actions[], suggestions[] }

- GET  /api/v1/assistant/active-jobs
    Returns recent jobs (in-flight / awaiting_review / failed) for the
    current user, used to populate the "which job?" picker and to drive
    the red-dot failure indicator on the floating widget.

- GET  /api/v1/assistant/job/<job_id>/diagnose
    Returns a structured plain-English diagnosis blob the frontend can
    show in the chat OR re-send into the next chat turn.

The chat endpoint always pulls a small "active jobs" summary from the
database so the assistant has fresh context even when the user hasn't
explicitly picked a job.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from backend.api import auth_bp  # noqa: F401  (touch package init)
from backend.api import assistant_bp  # registered in __init__.py
from backend.utils.database import get_db_cursor
from backend.services.ai_transcribe_service import _get_openai_key
from backend.services.assistant_doc import build_system_prompt, PAGE_KEYS


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _user_role(user_id: str) -> str:
    with get_db_cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
    return (row or {}).get('role') or 'employee'


def _fetch_active_jobs(user_id: str, limit: int = 10):
    """Recent jobs that are either in-flight, awaiting user input, or
    failed in the last 7 days. Used both for the picker and to give the
    LLM fresh context."""
    cutoff = datetime.now() - timedelta(days=7)
    with get_db_cursor() as cursor:
        cursor.execute(
            """SELECT id, tool_used, status, payload, created_at, updated_at
               FROM jobs
               WHERE user_id = %s
                 AND (
                    status IN (
                        'recording','transcribing','translating','arranging',
                        'awaiting_review','awaiting_translate_review',
                        'awaiting_arrange_review','live','awaiting_review',
                        'extracting','processing','queued','running',
                        'pending','generating'
                    )
                    OR (status = 'failed' AND updated_at >= %s)
                 )
               ORDER BY updated_at DESC
               LIMIT %s""",
            (user_id, cutoff, limit),
        )
        rows = cursor.fetchall() or []

    out = []
    for r in rows:
        payload = r.get('payload') or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        # Title format: "Channel · DD-MM-YYYY" (matches the dashboard's
        # row format). Falls back to whatever we have so titles never
        # collapse to "(untitled)" when there's a channel or date.
        channel = (payload.get('channel_name')
                   or payload.get('platform')
                   or payload.get('platform_name'))
        date = payload.get('date') or payload.get('call_date')
        time_str = payload.get('time') or payload.get('call_time')
        if channel and date:
            title = f"{channel} · {date}" + (f" · {time_str}" if time_str else "")
        elif channel:
            title = channel
        elif payload.get('video_title'):
            title = payload['video_title']
        elif payload.get('title'):
            title = payload['title']
        else:
            # Last resort: a friendly fallback using tool + short id.
            title = f"{r['tool_used']} job {r['id'][:8]}"
        err = (payload.get('error')
               or payload.get('arrange_error')
               or payload.get('translate_error')
               or payload.get('transcribe_error'))
        progress = payload.get('progress') or payload.get('current_step') or None
        out.append({
            'jobId': r['id'],
            'tool': r['tool_used'],
            'status': r['status'],
            'title': str(title)[:120],
            'progress': progress,
            'hasError': bool(err),
            'updatedAt': (r['updated_at'].isoformat()
                          if r.get('updated_at') else None),
        })
    return out


def _summarise_jobs(jobs) -> str:
    if not jobs:
        return ""
    lines = []
    for j in jobs[:8]:
        flag = " [FAILED]" if j['hasError'] or j['status'] == 'failed' else ""
        lines.append(
            f"  - {j['tool']} job {j['jobId']}: {j['status']} - "
            f"\"{j['title']}\"{flag}"
        )
    return "\n".join(lines)


def _diagnose_job(user_id: str, job_id: str):
    """Pull the full record and turn it into a compact, LLM-friendly
    JSON blob. Returns (blob_dict, http_error_or_none)."""
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT id, tool_used, status, payload, user_id, created_at, updated_at "
            "FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None, ("Job not found", 404)
    if str(row['user_id']) != str(user_id) and _user_role(user_id) != 'admin':
        return None, ("You don't own this job", 403)

    payload = row.get('payload') or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    # Extract the most useful fields without dumping the full payload
    # (it can be huge — transcripts, etc.).
    keep_keys = (
        'title', 'video_title', 'channel_name', 'platform',
        'progress', 'current_step', 'step', 'steps_done',
        'error', 'arrange_error', 'translate_error', 'transcribe_error',
        'failed_charts', 'missing_fields',
        'video_url', 'youtube_url', 'language',
    )
    summary_payload = {k: payload.get(k) for k in keep_keys if k in payload}

    blob = {
        'jobId': row['id'],
        'tool': row['tool_used'],
        'status': row['status'],
        'createdAt': row['created_at'].isoformat() if row.get('created_at') else None,
        'updatedAt': row['updated_at'].isoformat() if row.get('updated_at') else None,
        'details': summary_payload,
    }
    return blob, None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@assistant_bp.route('/active-jobs', methods=['GET'])
@jwt_required()
def active_jobs():
    user_id = get_jwt_identity()
    jobs = _fetch_active_jobs(user_id)
    failed_count = sum(1 for j in jobs if j['hasError'] or j['status'] == 'failed')
    return jsonify({'jobs': jobs, 'failedCount': failed_count}), 200


@assistant_bp.route('/job/<job_id>/diagnose', methods=['GET'])
@jwt_required()
def diagnose(job_id):
    user_id = get_jwt_identity()
    blob, err = _diagnose_job(user_id, job_id)
    if err:
        return jsonify({'error': err[0]}), err[1]
    return jsonify(blob), 200


@assistant_bp.route('/chat', methods=['POST'])
@jwt_required()
def chat():
    user_id = get_jwt_identity()
    role = _user_role(user_id)
    data = request.get_json(silent=True) or {}

    messages_in = data.get('messages') or []
    if not isinstance(messages_in, list):
        return jsonify({'error': 'messages must be a list'}), 400

    current_page = data.get('currentPage') or None
    job_context_id = data.get('jobContextId')

    # Pull fresh job context every turn so the LLM never operates on
    # stale info. Wrap in try/except so a transient DB hiccup never
    # takes the whole chat down — Ayushi can still answer "how do I…"
    # questions without job awareness.
    try:
        active = _fetch_active_jobs(user_id)
        summary = _summarise_jobs(active)
    except Exception as e:  # noqa: BLE001
        print(f'[assistant] _fetch_active_jobs failed: {e}')
        summary = ""

    diagnose_block = None
    if job_context_id:
        try:
            blob, _ = _diagnose_job(user_id, job_context_id)
            if blob:
                diagnose_block = json.dumps(blob, indent=2)
        except Exception as e:  # noqa: BLE001
            print(f'[assistant] _diagnose_job failed: {e}')

    system_prompt = build_system_prompt(role, current_page, summary, diagnose_block)

    # Keep only the last 12 user/assistant turns to control token cost.
    trimmed = []
    for m in messages_in[-24:]:
        role_ = m.get('role')
        content = (m.get('content') or '').strip()
        if role_ in ('user', 'assistant') and content:
            trimmed.append({'role': role_, 'content': content[:4000]})

    if not trimmed:
        return jsonify({'error': 'no user message provided'}), 400

    api_key = _get_openai_key() or os.environ.get('OPENAI_API_KEY')
    if not api_key:
        # Graceful degradation - still helpful even without GPT.
        return jsonify({
            'message': ("I can't reach OpenAI right now because no API key"
                        " is configured. Please ask your admin to add the"
                        " OpenAI key under Administration → API Keys."),
            'actions': ([{'type': 'navigate', 'page': 'api-keys'},
                         {'type': 'wait', 'ms': 400},
                         {'type': 'highlight',
                          'selector': "[data-tour='nav-api-keys']",
                          'text': 'Add the OpenAI key here'}]
                        if role == 'admin' else []),
            'suggestions': ['How do I make a rationale?',
                            'What can you help with?'],
        }), 200

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model='gpt-4o',
            # NB: max_tokens raised so Ayushi can fit a full multi-step
            # tour plan + a short markdown explanation in one shot.
            messages=[{'role': 'system', 'content': system_prompt}, *trimmed],
            temperature=0.25,
            max_tokens=1500,
            response_format={'type': 'json_object'},
        )
        raw = (completion.choices[0].message.content or '').strip()
    except Exception as e:  # noqa: BLE001
        print(f'[assistant] OpenAI error: {e}')
        return jsonify({
            'message': ("I'm having trouble reaching the AI right now. "
                        "Please try again in a moment."),
            'actions': [],
            'suggestions': ['Try again'],
        }), 200

    # Parse + sanitise the model's JSON.
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {'message': raw, 'actions': [], 'suggestions': []}

    message = str(parsed.get('message') or '').strip() or "I'm here to help!"
    suggestions = parsed.get('suggestions') or []
    if not isinstance(suggestions, list):
        suggestions = []
    suggestions = [str(s)[:60] for s in suggestions[:4]]

    actions_in = parsed.get('actions') or []
    actions_out = []
    if isinstance(actions_in, list):
        for a in actions_in[:12]:
            if not isinstance(a, dict):
                continue
            t = a.get('type')
            if t == 'navigate':
                page = a.get('page')
                if page in PAGE_KEYS:
                    actions_out.append({'type': 'navigate', 'page': page})
            elif t == 'highlight':
                sel = a.get('selector') or ''
                if sel.startswith("[data-tour='") and sel.endswith("']"):
                    actions_out.append({
                        'type': 'highlight',
                        'selector': sel,
                        'text': str(a.get('text') or '')[:200],
                    })
            elif t == 'wait':
                try:
                    ms = max(0, min(5000, int(a.get('ms', 0))))
                    actions_out.append({'type': 'wait', 'ms': ms})
                except Exception:
                    pass

    return jsonify({
        'message': message,
        'actions': actions_out,
        'suggestions': suggestions,
    }), 200
