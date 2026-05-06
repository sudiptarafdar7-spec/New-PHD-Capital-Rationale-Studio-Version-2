from flask import Blueprint

auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')
users_bp = Blueprint('users', __name__, url_prefix='/api/v1/users')
api_keys_bp = Blueprint('api_keys', __name__, url_prefix='/api/v1/api-keys')
pdf_template_bp = Blueprint('pdf_template', __name__, url_prefix='/api/v1/pdf-template')
uploaded_files_bp = Blueprint('uploaded_files', __name__, url_prefix='/api/v1/uploaded-files')
channels_bp = Blueprint('channels', __name__, url_prefix='/api/v1/channels')
media_rationale_bp = Blueprint('media_rationale', __name__, url_prefix='/api/v1/media-rationale')
premium_rationale_bp = Blueprint('premium_rationale', __name__, url_prefix='/api/v1/premium-rationale')
bulk_rationale_bp = Blueprint('bulk_rationale', __name__, url_prefix='/api/v1/bulk-rationale')
saved_rationale_bp = Blueprint('saved_rationale', __name__, url_prefix='/api/v1/saved-rationale')
activity_logs_bp = Blueprint('activity_logs', __name__, url_prefix='/api/v1/activity-logs')
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/v1/dashboard')
media_presence_bp = Blueprint('media_presence', __name__, url_prefix='/api/v1/media-presence')
ai_transcribe_bp = Blueprint('ai_transcribe', __name__, url_prefix='/api/v1/ai-transcribe')
voice_typing_bp = Blueprint('voice_typing', __name__, url_prefix='/api/v1/voice-typing')
live_transcribe_bp = Blueprint('live_transcribe', __name__, url_prefix='/api/v1/live-transcribe')
assistant_bp = Blueprint('assistant', __name__, url_prefix='/api/v1/assistant')

from backend.api import auth, users, api_keys, pdf_template, uploaded_files, channels, media_rationale, premium_rationale, bulk_rationale, saved_rationale, activity_logs, dashboard, manual_v2, generate_chart, media_presence, ai_transcribe, voice_typing, live_transcribe, assistant

manual_v2_bp = manual_v2.manual_v2_bp
generate_chart_bp = generate_chart.generate_chart_bp
