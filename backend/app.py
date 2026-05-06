import os
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from backend.config import Config
from backend.api import auth_bp, users_bp, api_keys_bp, pdf_template_bp, uploaded_files_bp, channels_bp, media_rationale_bp, premium_rationale_bp, bulk_rationale_bp, saved_rationale_bp, activity_logs_bp, dashboard_bp, manual_v2_bp, generate_chart_bp, media_presence_bp, ai_transcribe_bp, voice_typing_bp, live_transcribe_bp, assistant_bp
from backend.utils.database import init_database

def create_app():
    # Serve static files from build directory in production
    static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'build')
    app = Flask(__name__, static_folder=static_folder, static_url_path='')
    app.config.from_object(Config)
    
    # Initialize database tables
    with app.app_context():
        init_database()
    
    # CORS configuration with environment-based security
    allowed_origins = os.environ.get('ALLOWED_ORIGINS', '*')
    if allowed_origins != '*':
        allowed_origins = allowed_origins.split(',')
    
    CORS(app, resources={
        r"/api/*": {
            "origins": allowed_origins,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True
        }
    })
    
    jwt = JWTManager(app)
    
    @jwt.unauthorized_loader
    def unauthorized_callback(callback):
        return jsonify({'error': 'Missing or invalid token'}), 401
    
    @jwt.invalid_token_loader
    def invalid_token_callback(callback):
        return jsonify({'error': 'Invalid token'}), 401
    
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'error': 'Token has expired'}), 401
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(api_keys_bp)
    app.register_blueprint(pdf_template_bp)
    app.register_blueprint(uploaded_files_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(media_rationale_bp)
    app.register_blueprint(premium_rationale_bp)
    app.register_blueprint(bulk_rationale_bp)
    app.register_blueprint(manual_v2_bp)
    app.register_blueprint(generate_chart_bp)
    app.register_blueprint(saved_rationale_bp)
    app.register_blueprint(activity_logs_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(media_presence_bp)
    app.register_blueprint(ai_transcribe_bp)
    app.register_blueprint(voice_typing_bp)
    app.register_blueprint(live_transcribe_bp)
    app.register_blueprint(assistant_bp)

    # ---- Orphan recovery on startup ------------------------------------
    # Voice Typing (Vosk) and Live Transcribe (AssemblyAI Realtime) both
    # use daemon threads that DO NOT survive a process restart. On boot,
    # re-spawn workers for any jobs left mid-flight.
    #
    # IMPORTANT: gate this carefully so it runs EXACTLY ONCE per serving
    # process. Two failure modes to avoid:
    #   1. Werkzeug reloader parent imports this module before forking the
    #      child worker — we must NOT spawn threads in the parent (they'd
    #      die on the next reload AND duplicate the child's work).
    #   2. `app.debug` is `False` at create_app() time (debug is set later
    #      by `app.run(debug=True)`), so we cannot rely on it here.
    #
    # The robust gate: only schedule recovery when WERKZEUG_RUN_MAIN is
    # 'true' (reloader child) OR when the reloader is not in use at all
    # (production WSGI / gunicorn / `flask run --no-reload`). We detect
    # "reloader is active" via `WERKZEUG_SERVER_FD`, which Werkzeug only
    # sets when the reloader has spawned a worker. A `_recovery_started`
    # flag guarantees idempotency even if create_app is called twice.
    in_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    reloader_active = 'WERKZEUG_SERVER_FD' in os.environ or os.environ.get('WERKZEUG_RUN_MAIN') is not None
    should_recover = in_reloader_child or not reloader_active

    if should_recover and not getattr(app, '_orphan_recovery_started', False):
        app._orphan_recovery_started = True

        # Acquire a Postgres SESSION advisory lock that we HOLD for the
        # entire orphan-recovery section. In multi-worker WSGI deployments
        # (gunicorn -w N) only one worker wins the lock; the others skip
        # recovery and avoid double-spawning daemon threads for the same
        # jobs. The lock is bound to the underlying connection — we keep
        # the connection alive in `_recovery_lock_conn` (intentionally
        # leaked into module scope so it survives until process exit; the
        # OS reclaims it on shutdown).
        # The constant 0x4C495645 is ASCII "LIVE" — arbitrary but stable.
        _recovery_lock_conn = None
        _have_lock = False
        try:
            import psycopg2
            from backend.config import Config as _LockCfg
            _recovery_lock_conn = psycopg2.connect(_LockCfg.DATABASE_URL)
            _recovery_lock_conn.autocommit = True
            with _recovery_lock_conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (0x4C495645,))
                row = cur.fetchone()
                _have_lock = bool(row and row[0])
            app._recovery_lock_conn = _recovery_lock_conn  # keep alive
        except Exception as lock_err:
            print(f"[startup] advisory-lock probe failed, proceeding: {lock_err}")
            _have_lock = True  # single-process fallback

        if _have_lock:
            try:
                from backend.pipeline.voice_typing.transcribe_vosk import recover_orphans as recover_voice
                recover_voice()
            except Exception as recover_err:
                print(f"[startup] voice typing orphan recovery failed (non-fatal): {recover_err}")
            try:
                from backend.pipeline.live_transcribe.realtime_transcribe import recover_orphans as recover_live
                recover_live()
            except Exception as recover_err:
                print(f"[startup] live transcribe orphan recovery failed (non-fatal): {recover_err}")
        else:
            print("[startup] another worker holds the orphan-recovery lock — skipping.")

    # Cap upload size at 500 MB. Mirrors the client-side limit in
    # VoiceTypingPage.tsx's UploadAudioFallback and prevents a malicious
    # client from filling the VPS disk via the manual audio-upload fallback.
    # Flask rejects oversize requests at WSGI level with HTTP 413 before any
    # handler bytes are read, so this can't be bypassed by the frontend.
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
    
    @app.route('/api/health', methods=['GET'])
    def health():
        return jsonify({'status': 'ok', 'message': 'PHD Capital Rationale Studio API'}), 200
    
    # Serve React frontend (catch-all route for SPA)
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_frontend(path):
        static_dir = app.static_folder or static_folder
        if path != "" and os.path.exists(os.path.join(static_dir, path)):
            return send_from_directory(static_dir, path)
        else:
            return send_from_directory(static_dir, 'index.html')
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=8000, debug=True)
