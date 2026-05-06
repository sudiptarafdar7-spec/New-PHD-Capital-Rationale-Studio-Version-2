from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import uuid
import os
import json
from backend.api import Blueprint
from backend.utils.database import get_db_cursor
from backend.services.manual_v2.utils import enrich_stocks_with_master_data, get_stock_autocomplete
from backend.services.manual_v2 import ManualRationaleOrchestrator

manual_v2_bp = Blueprint('manual_v2', __name__, url_prefix='/api/v1/manual-v2')

@manual_v2_bp.route('/stocks', methods=['GET'])
@jwt_required()
def autocomplete_stocks():
    try:
        # Accept both 'q' and 'query' parameters for flexibility
        query = request.args.get('q') or request.args.get('query', '')
        query = query.strip() if query else ''
        limit = request.args.get('limit', 10, type=int)
        
        if not query:
            return jsonify({'stocks': []}), 200
        
        stocks = get_stock_autocomplete(query, limit)
        
        return jsonify({'stocks': stocks}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs', methods=['POST'])
@jwt_required()
def create_job():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        channel_id = data.get('channel_id')
        title = data.get('title', '')
        date = data.get('date', '')
        call_time = data.get('call_time', '')
        stocks = data.get('stocks', [])
        
        if not channel_id:
            return jsonify({'error': 'channel_id is required'}), 400
        
        if not title:
            return jsonify({'error': 'title is required'}), 400
        
        if not stocks or len(stocks) == 0:
            return jsonify({'error': 'At least one stock is required'}), 400
        
        enriched_stocks = enrich_stocks_with_master_data(stocks)
        
        job_id = f"manual-{uuid.uuid4().hex[:8]}"
        folder_path = os.path.join('backend', 'job_files', job_id)
        
        # Look up the channel so the unified job title can include both the
        # platform (icon-bearing prefix on the dashboard) and channel name.
        with get_db_cursor() as cursor:
            cursor.execute("SELECT channel_name, platform FROM channels WHERE id = %s", (channel_id,))
            channel = cursor.fetchone()
            channel_name = channel['channel_name'] if channel else 'Unknown'
            platform = channel['platform'] if channel else ''

        # Canonical title: "{Platform} - {Channel} - {DD-MM-YYYY} - {HH:MM}".
        from backend.utils.job_title import build_job_title
        job_title = build_job_title(platform, channel_name, date, call_time)
        
        payload = {
            'stocks': enriched_stocks,
            'call_time': call_time,
            'title': title,
            'date': date
        }
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO jobs (id, channel_id, title, date, time, user_id, tool_used, status, folder_path, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (job_id, channel_id, job_title, date, (call_time or None), user_id, 'Manual Rationale', 'pending', folder_path,
                  json.dumps(payload), datetime.now(), datetime.now()))
            
            steps = [
                (1, 'Fetch CMP', 'pending'),
                (2, 'Generate Charts', 'pending'),
                (3, 'Generate PDF', 'pending')
            ]
            
            for step_number, step_name, status in steps:
                cursor.execute("""
                    INSERT INTO job_steps (job_id, step_number, step_name, status, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (job_id, step_number, step_name, status, datetime.now()))
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Job created successfully'
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs/<job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, channel_id, title, date, user_id, tool_used, status, progress, current_step, folder_path, payload, created_at, updated_at
                FROM jobs WHERE id = %s
            """, (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            cursor.execute("""
                SELECT id, job_id, step_number, step_name, status, message, started_at, ended_at, created_at
                FROM job_steps WHERE job_id = %s ORDER BY step_number
            """, (job_id,))
            job_steps = cursor.fetchall()
        
        return jsonify({
            'job': dict(job),
            'job_steps': [dict(step) for step in job_steps]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs/<job_id>/run', methods=['POST'])
@jwt_required()
def run_job(job_id):
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT status FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            current_status = job['status']
            
            # Allow restart if job is completed, failed, or pending
            if current_status == 'processing':
                return jsonify({'error': 'Job is currently running. Please wait for it to complete.'}), 400
            
            # Reset job status to pending for restart
            if current_status in ['pdf_ready', 'completed', 'signed', 'failed']:
                cursor.execute("""
                    UPDATE jobs 
                    SET status = %s, progress = %s, current_step = %s, updated_at = %s 
                    WHERE id = %s
                """, ('pending', 0, 0, datetime.now(), job_id))
                
                # Reset all job steps to pending
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = %s, message = NULL, started_at = NULL, ended_at = NULL 
                    WHERE job_id = %s
                """, ('pending', job_id))
        
        orchestrator = ManualRationaleOrchestrator(job_id)
        orchestrator.run_async()
        
        return jsonify({
            'success': True,
            'message': 'Job started successfully'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs/<job_id>/steps', methods=['GET'])
@jwt_required()
def get_job_steps(job_id):
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, job_id, step_number, step_name, status, message, started_at, ended_at, created_at
                FROM job_steps WHERE job_id = %s ORDER BY step_number
            """, (job_id,))
            job_steps = cursor.fetchall()
        
        return jsonify({
            'job_steps': [dict(step) for step in job_steps]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs/<job_id>/save', methods=['POST'])
@jwt_required()
def save_job(job_id):
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                SELECT channel_id, title, date, folder_path, status, payload
                FROM jobs WHERE id = %s
            """, (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            if job['status'] != 'pdf_ready':
                return jsonify({'error': 'Job is not ready to be saved'}), 400
            
            pdf_path = None
            
            # Method 1: Get PDF path from Step 3 output_files
            cursor.execute("""
                SELECT output_files 
                FROM job_steps 
                WHERE job_id = %s AND step_number = 3 AND status = 'success'
            """, (job_id,))
            step_result = cursor.fetchone()
            
            if step_result and step_result['output_files']:
                pdf_path = step_result['output_files'][0]
            
            # Method 2: Fallback to payload pdf_filename
            if not pdf_path or not os.path.exists(pdf_path):
                payload = job.get('payload', {})
                if isinstance(payload, str):
                    payload = json.loads(payload)
                pdf_filename = payload.get('pdf_filename')
                if pdf_filename:
                    pdf_path = os.path.join(job['folder_path'], 'pdf', pdf_filename)
            
            # Method 3: Fallback to finding latest PDF in folder
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_folder = os.path.join(job['folder_path'], 'pdf')
                if os.path.exists(pdf_folder):
                    pdf_files = [f for f in os.listdir(pdf_folder) if f.endswith('.pdf')]
                    if pdf_files:
                        # Get most recent PDF
                        pdf_files.sort(key=lambda x: os.path.getmtime(os.path.join(pdf_folder, x)), reverse=True)
                        pdf_path = os.path.join(pdf_folder, pdf_files[0])
            
            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({'error': 'PDF file not found. Please generate PDF first.'}), 404
            
            cursor.execute("""
                SELECT id FROM saved_rationale WHERE job_id = %s
            """, (job_id,))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""
                    UPDATE saved_rationale 
                    SET title = %s, date = %s, unsigned_pdf_path = %s, updated_at = %s
                    WHERE job_id = %s
                """, (job['title'], job['date'], pdf_path, datetime.now(), job_id))
            else:
                cursor.execute("""
                    INSERT INTO saved_rationale (job_id, tool_used, channel_id, title, date, unsigned_pdf_path, sign_status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (job_id, 'Manual Rationale', job['channel_id'], job['title'], job['date'], 
                      pdf_path, 'Unsigned', datetime.now(), datetime.now()))
            
            cursor.execute("""
                UPDATE jobs SET status = %s, updated_at = %s WHERE id = %s
            """, ('completed', datetime.now(), job_id))
        
        return jsonify({
            'success': True,
            'message': 'Job saved successfully'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs/<job_id>/upload-signed', methods=['POST'])
@jwt_required()
def upload_signed_pdf(job_id):
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                SELECT folder_path FROM jobs WHERE id = %s
            """, (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            pdf_folder = os.path.join(job['folder_path'], 'pdf')
            os.makedirs(pdf_folder, exist_ok=True)
            
            signed_filename = f"signed_{uuid.uuid4().hex[:8]}.pdf"
            signed_path = os.path.join(pdf_folder, signed_filename)
            
            file.save(signed_path)
            
            cursor.execute("""
                UPDATE saved_rationale 
                SET signed_pdf_path = %s, sign_status = %s, signed_uploaded_at = %s, updated_at = %s
                WHERE job_id = %s
            """, (signed_path, 'Signed', datetime.now(), datetime.now(), job_id))
            
            cursor.execute("""
                UPDATE jobs SET status = %s, updated_at = %s WHERE id = %s
            """, ('signed', datetime.now(), job_id))
        
        return jsonify({
            'success': True,
            'message': 'Signed PDF uploaded successfully'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@manual_v2_bp.route('/jobs/<job_id>/download', methods=['GET'])
@jwt_required()
def download_pdf(job_id):
    try:
        current_user = get_jwt_identity()
        
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT folder_path, payload, user_id FROM jobs WHERE id = %s
            """, (job_id,))
            job = cursor.fetchone()
            
            # Return 403 for job not found (prevents ID enumeration)
            if not job:
                return jsonify({'error': 'Access denied'}), 403
            
            # Verify job ownership - handle both string and dict formats
            job_user_id = str(job['user_id']) if job['user_id'] else None
            current_user_str = str(current_user) if isinstance(current_user, str) else str(current_user.get('sub', '')) if isinstance(current_user, dict) else None
            
            if job_user_id != current_user_str:
                return jsonify({'error': 'Access denied'}), 403
            
            # Parse payload if it's a string
            import json
            payload = job['payload']
            if isinstance(payload, str):
                payload = json.loads(payload)
            
            # Get PDF filename from payload
            pdf_filename = payload.get('pdf_filename') if payload else None
            
            if not pdf_filename:
                return jsonify({'error': 'Access denied'}), 403
            
            pdf_path = os.path.join(job['folder_path'], 'pdf', pdf_filename)
            
            # Convert to absolute path to ensure correct resolution
            abs_pdf_path = os.path.abspath(pdf_path)
            
            if not os.path.exists(abs_pdf_path):
                return jsonify({'error': 'Access denied'}), 403
            
            from flask import send_file
            return send_file(
                abs_pdf_path,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=pdf_filename
            )
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
