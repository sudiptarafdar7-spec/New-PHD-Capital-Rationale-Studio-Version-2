from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.utils.database import get_db_cursor
from backend.api import saved_rationale_bp
from backend.models.user import User
from backend.api.activity_logs import create_activity_log
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import uuid

def is_admin(user_id):
    user = User.find_by_id(user_id)
    return user and user.get('role') == 'admin'

@saved_rationale_bp.route('', methods=['GET'])
@jwt_required()
def get_saved_rationale():
    try:
        current_user_id = get_jwt_identity()
        user_is_admin = is_admin(current_user_id)
        
        # Get query parameters for filtering
        tool_filter = request.args.get('tool', 'all')
        channel_filter = request.args.get('channel', 'all')
        date_from = request.args.get('dateFrom')
        date_to = request.args.get('dateTo')
        
        with get_db_cursor() as cursor:
            # Admin sees all rationale, employee sees only their own
            query = """
                SELECT 
                    sr.id,
                    sr.job_id,
                    sr.tool_used,
                    sr.title,
                    sr.date,
                    sr.youtube_url,
                    sr.unsigned_pdf_path,
                    sr.signed_pdf_path,
                    sr.signed_uploaded_at,
                    sr.created_at,
                    c.channel_name,
                    c.channel_logo_path,
                    c.platform,
                    c.channel_url,
                    j.user_id,
                    CONCAT(u.first_name, ' ', u.last_name) as creator_name
                FROM saved_rationale sr
                LEFT JOIN channels c ON sr.channel_id = c.id
                LEFT JOIN jobs j ON sr.job_id = j.id
                LEFT JOIN users u ON j.user_id = u.id
                WHERE 1=1
            """
            params = []
            
            # Non-admin users can only see their own rationale
            if not user_is_admin:
                query += " AND j.user_id = %s"
                params.append(current_user_id)
            
            if tool_filter != 'all':
                query += " AND sr.tool_used = %s"
                params.append(tool_filter)
            
            if channel_filter != 'all':
                query += " AND c.channel_name = %s"
                params.append(channel_filter)
            
            if date_from:
                query += " AND sr.date >= %s"
                params.append(date_from)
            
            if date_to:
                query += " AND sr.date <= %s"
                params.append(date_to)
            
            query += " ORDER BY sr.created_at DESC"
            
            cursor.execute(query, tuple(params))
            rationales = cursor.fetchall()
            
            return jsonify({
                'success': True,
                'rationales': rationales
            }), 200
            
    except Exception as e:
        print(f"Error fetching saved rationale: {str(e)}")
        return jsonify({'error': 'Failed to fetch saved rationale'}), 500

@saved_rationale_bp.route('/<int:rationale_id>', methods=['GET'])
@jwt_required()
def get_rationale_by_id(rationale_id):
    try:
        current_user_id = get_jwt_identity()
        user_is_admin = is_admin(current_user_id)
        
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    sr.id,
                    sr.job_id,
                    sr.tool_used,
                    sr.title,
                    sr.date,
                    sr.youtube_url,
                    sr.unsigned_pdf_path,
                    sr.signed_pdf_path,
                    sr.signed_uploaded_at,
                    sr.created_at,
                    c.channel_name,
                    c.channel_logo_path,
                    c.platform,
                    c.channel_url,
                    j.user_id,
                    CONCAT(u.first_name, ' ', u.last_name) as creator_name
                FROM saved_rationale sr
                LEFT JOIN channels c ON sr.channel_id = c.id
                LEFT JOIN jobs j ON sr.job_id = j.id
                LEFT JOIN users u ON j.user_id = u.id
                WHERE sr.id = %s
            """, (rationale_id,))
            
            rationale = cursor.fetchone()
            
            if not rationale:
                return jsonify({'error': 'Rationale not found'}), 404
            
            # Non-admin users can only see their own rationale
            if not user_is_admin and rationale.get('user_id') != current_user_id:
                return jsonify({'error': 'Access denied'}), 403
            
            return jsonify({
                'success': True,
                'rationale': rationale
            }), 200
            
    except Exception as e:
        print(f"Error fetching rationale: {str(e)}")
        return jsonify({'error': 'Failed to fetch rationale'}), 500


@saved_rationale_bp.route('/save', methods=['POST'])
@jwt_required()
def save_rationale():
    """Save job to saved_rationale table and mark as completed"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        job_id = data.get('jobId')
        if not job_id:
            return jsonify({'error': 'Job ID is required'}), 400
        
        # Get job details from database
        with get_db_cursor(commit=True) as cursor:
            # Fetch job details
            cursor.execute("""
                SELECT j.*, c.id as channel_id
                FROM jobs j
                LEFT JOIN channels c ON j.channel_id = c.id
                WHERE j.id = %s AND j.user_id = %s
            """, (job_id, current_user_id))
            
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found or access denied'}), 404
            
            # Determine the correct step number based on tool_used
            # Manual Rationale uses Step 3, Premium Rationale uses Step 8, Media Rationale uses Step 14
            tool_used = job.get('tool_used', '')
            if tool_used == 'Manual Rationale':
                pdf_step_number = 3
            elif tool_used == 'Premium Rationale':
                pdf_step_number = 8
            else:
                pdf_step_number = 14
            
            # Get PDF path from the appropriate step
            cursor.execute("""
                SELECT output_files 
                FROM job_steps 
                WHERE job_id = %s AND step_number = %s AND status = 'success'
            """, (job_id, pdf_step_number))
            
            step_result = cursor.fetchone()
            
            if not step_result or not step_result['output_files']:
                return jsonify({'error': 'PDF not found. Please generate PDF first.'}), 400
            
            unsigned_pdf_path = step_result['output_files'][0]
            
            # Check if rationale already exists
            cursor.execute("SELECT id FROM saved_rationale WHERE job_id = %s", (job_id,))
            existing = cursor.fetchone()
            
            if existing:
                return jsonify({'error': 'This job is already saved'}), 400
            
            # Insert into saved_rationale
            cursor.execute("""
                INSERT INTO saved_rationale (
                    job_id, tool_used, channel_id, title, 
                    date, youtube_url, unsigned_pdf_path,
                    sign_status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                job_id,
                job['tool_used'],
                job['channel_id'],
                job['title'],
                job['date'],
                job['youtube_url'],
                unsigned_pdf_path,
                'Unsigned',
                datetime.now(),
                datetime.now()
            ))
            
            rationale_id = cursor.fetchone()['id']
            
            # Update job status to completed
            cursor.execute("""
                UPDATE jobs 
                SET status = 'completed', updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
            
            # Create activity log
            create_activity_log(
                current_user_id,
                'job_completed',
                f'Saved rationale for video: {job["title"]}',
                job_id,
                job['tool_used']
            )
        
        return jsonify({
            'success': True,
            'message': 'Rationale saved successfully',
            'rationaleId': rationale_id
        }), 200
        
    except Exception as e:
        print(f"Error saving rationale: {str(e)}")
        return jsonify({'error': f'Failed to save rationale: {str(e)}'}), 500


@saved_rationale_bp.route('/upload-signed', methods=['POST'])
@jwt_required()
def upload_signed_pdf():
    """Upload signed PDF and update saved_rationale"""
    try:
        current_user_id = get_jwt_identity()
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        job_id = request.form.get('jobId')
        if not job_id:
            return jsonify({'error': 'Job ID is required'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        # Verify job ownership
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                SELECT j.*, sr.id as rationale_id
                FROM jobs j
                LEFT JOIN saved_rationale sr ON j.id = sr.job_id
                WHERE j.id = %s AND j.user_id = %s
            """, (job_id, current_user_id))
            
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found or access denied'}), 404
            
            if not job['rationale_id']:
                return jsonify({'error': 'Please save the rationale first'}), 400
            
            # Save signed PDF to job folder
            job_folder = os.path.join('backend', 'job_files', job_id, 'output')
            os.makedirs(job_folder, exist_ok=True)
            
            # Generate unique filename
            original_filename = secure_filename(file.filename)
            filename_parts = original_filename.rsplit('.', 1)
            signed_filename = f"{filename_parts[0]}_signed.pdf"
            signed_pdf_path = os.path.join(job_folder, signed_filename)
            
            # Save file
            file.save(signed_pdf_path)
            
            # Convert to relative path for database
            relative_signed_path = os.path.join('backend', 'job_files', job_id, 'output', signed_filename)
            
            # Update saved_rationale
            cursor.execute("""
                UPDATE saved_rationale 
                SET signed_pdf_path = %s, 
                    sign_status = 'Signed',
                    signed_uploaded_at = %s,
                    updated_at = %s
                WHERE job_id = %s
            """, (relative_signed_path, datetime.now(), datetime.now(), job_id))
            
            # Update job_steps step 15 output_files
            cursor.execute("""
                UPDATE job_steps
                SET output_files = ARRAY[%s],
                    message = 'Signed PDF uploaded successfully',
                    ended_at = %s
                WHERE job_id = %s AND step_number = 15
            """, (relative_signed_path, datetime.now(), job_id))
            
            # Update job status to signed
            cursor.execute("""
                UPDATE jobs 
                SET status = 'signed', updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
            
            # Create activity log
            create_activity_log(
                current_user_id,
                'job_completed',
                f'Uploaded signed PDF for: {job["title"]}',
                job_id,
                job['tool_used']
            )
        
        return jsonify({
            'success': True,
            'message': 'Signed PDF uploaded successfully',
            'fileName': signed_filename,
            'uploadedAt': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error uploading signed PDF: {str(e)}")
        return jsonify({'error': f'Failed to upload signed PDF: {str(e)}'}), 500


@saved_rationale_bp.route('/download/<path:file_path>', methods=['GET'])
@jwt_required()
def download_pdf(file_path):
    """Download PDF or CSV files"""
    try:
        current_user_id = get_jwt_identity()
        user_is_admin = is_admin(current_user_id)
        
        # Verify the file belongs to user's job (or user is admin)
        job_id = file_path.split('/')[2] if '/' in file_path else None
        
        if not job_id:
            return jsonify({'error': 'Invalid file path'}), 400
        
        with get_db_cursor() as cursor:
            # Admin can access any file, employee can only access their own
            if user_is_admin:
                cursor.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
            else:
                cursor.execute("""
                    SELECT j.id
                    FROM jobs j
                    WHERE j.id = %s AND j.user_id = %s
                """, (job_id, current_user_id))
            
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Access denied'}), 403
        
        # Construct absolute path (resolve relative to workspace root)
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        absolute_file_path = os.path.join(workspace_root, file_path)
        
        # Check if file exists
        if not os.path.exists(absolute_file_path):
            return jsonify({'error': f'File not found: {absolute_file_path}'}), 404
        
        # Determine MIME type based on file extension
        file_extension = os.path.splitext(file_path)[1].lower()
        mimetype_map = {
            '.pdf': 'application/pdf',
            '.csv': 'text/csv',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.txt': 'text/plain'
        }
        mimetype = mimetype_map.get(file_extension, 'application/octet-stream')
        
        # Send file
        return send_file(
            absolute_file_path,
            as_attachment=True,
            download_name=os.path.basename(file_path),
            mimetype=mimetype
        )
        
    except Exception as e:
        print(f"Error downloading file: {str(e)}")
        return jsonify({'error': f'Failed to download file: {str(e)}'}), 500
