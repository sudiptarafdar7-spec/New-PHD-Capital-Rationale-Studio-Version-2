from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.utils.database import get_db_cursor
from backend.utils.path_utils import resolve_job_folder_path
from backend.api import premium_rationale_bp
from backend.models.user import User
from datetime import datetime
import os
import secrets
import threading
import shutil

def is_admin(user_id):
    user = User.find_by_id(user_id)
    return user and user.get('role') == 'admin'

def check_job_access(job_id, current_user_id):
    """Verify user owns this job or is admin"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT user_id FROM jobs WHERE id = %s", (job_id,))
        job = cursor.fetchone()
        
        if not job:
            return False, "Job not found"
        
        if job['user_id'] != current_user_id and not is_admin(current_user_id):
            return False, "Access denied"
        
        return True, None

@premium_rationale_bp.route('/create-job', methods=['POST'])
@jwt_required()
def create_job():
    """Create a new Premium Rationale job"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        # Extract input data
        channel_id = data.get('channelId')
        call_date = data.get('callDate')  # e.g., "2025-11-03"
        call_time = data.get('callTime', '00:00:00')  # e.g., "14:30:00"
        stock_calls_text = data.get('stockCallsText', '')
        
        if not channel_id or not call_date or not stock_calls_text:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Get channel details
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, channel_name, platform, channel_url 
                FROM channels 
                WHERE id = %s
            """, (channel_id,))
            channel = cursor.fetchone()
            
            if not channel:
                return jsonify({'error': 'Channel not found'}), 404
        
        # Generate unique job ID
        job_id = f"premium-{secrets.token_hex(4)}"
        
        # Create job folder structure
        job_folder = os.path.join('backend', 'job_files', job_id)
        os.makedirs(job_folder, exist_ok=True)
        os.makedirs(os.path.join(job_folder, 'analysis'), exist_ok=True)
        os.makedirs(os.path.join(job_folder, 'charts'), exist_ok=True)
        os.makedirs(os.path.join(job_folder, 'pdf'), exist_ok=True)
        
        # Save input text to input.txt
        input_file_path = os.path.join(job_folder, 'input.txt')
        with open(input_file_path, 'w', encoding='utf-8') as f:
            f.write(f"DATE: {call_date}\n")
            f.write(f"TIME: {call_time}\n")
            f.write(f"PLATFORM: {channel['platform']}\n")
            f.write(f"CHANNEL: {channel['channel_name']}\n")
            f.write(f"\nSTOCK CALLS:\n{stock_calls_text}\n")
        
        # Canonical title: "{Platform} - {Channel} - {DD-MM-YYYY} - {HH:MM}"
        from backend.utils.job_title import build_job_title
        rationale_title = build_job_title(channel['platform'], channel['channel_name'], call_date, call_time)
        
        # Create job record in database
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO jobs (
                    id, user_id, channel_id, tool_used, title, 
                    date, time, youtube_url, video_id, duration,
                    status, current_step, progress, folder_path,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                job_id,
                current_user_id,
                channel_id,
                'Premium Rationale',
                rationale_title,
                call_date,
                call_time,
                None,  # youtube_url set to NULL for Premium Rationale
                None,  # video_id set to NULL for Premium Rationale
                None,  # duration set to NULL for Premium Rationale
                'pending',
                0,
                0,
                job_folder,
                datetime.now(),
                datetime.now()
            ))
            
            # Initialize job steps (8 steps for Premium Rationale)
            premium_steps = [
                {'step_number': 1, 'step_name': 'Generate CSV from Input'},
                {'step_number': 2, 'step_name': 'Map Stock Symbols'},
                {'step_number': 3, 'step_name': 'Fetch Current Market Price'},
                {'step_number': 4, 'step_name': 'Generate Stock Charts'},
                {'step_number': 5, 'step_name': 'Fetch Technical Indicators'},
                {'step_number': 6, 'step_name': 'Fetch Fundamental Data'},
                {'step_number': 7, 'step_name': 'Generate Analysis'},
                {'step_number': 8, 'step_name': 'Generate PDF Report'},
            ]
            
            for step in premium_steps:
                cursor.execute("""
                    INSERT INTO job_steps (job_id, step_number, step_name, status, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (job_id, step['step_number'], step['step_name'], 'pending', datetime.now()))
        
        # Start processing in background thread
        thread = threading.Thread(target=process_premium_job_async, args=(job_id,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Premium Rationale job created successfully',
            'jobId': job_id,
            'title': rationale_title
        }), 201
        
    except Exception as e:
        print(f"Error creating Premium Rationale job: {str(e)}")
        return jsonify({'error': str(e)}), 500

def process_premium_job_async(job_id):
    """Process Premium Rationale job in background"""
    try:
        # Import pipeline steps
        from backend.pipeline.premium import (
            step01_generate_csv,
            step02_map_master,
            step03_fetch_cmp,
            step04_generate_charts,
            step05_fetch_technical,
            step06_fetch_fundamental,
            step07_generate_analysis,
            step08_generate_pdf
        )
        
        # Update job status to processing
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs 
                SET status = 'processing', current_step = 1, updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
        
        # Get job details
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
        
        job_folder = job['folder_path']
        
        # Read input text
        input_file_path = os.path.join(job_folder, 'input.txt')
        with open(input_file_path, 'r', encoding='utf-8') as f:
            input_text = f.read()
        
        # Get API keys from database
        with get_db_cursor() as cursor:
            cursor.execute("SELECT key_value FROM api_keys WHERE LOWER(provider) = 'openai'")
            openai_key_row = cursor.fetchone()
            openai_api_key = openai_key_row['key_value'] if openai_key_row else None
            
            cursor.execute("SELECT key_value FROM api_keys WHERE LOWER(provider) = 'dhan'")
            dhan_key_row = cursor.fetchone()
            dhan_api_key = dhan_key_row['key_value'] if dhan_key_row else None
        
        # Process steps 1-7 (before CSV review)
        steps_before_review = [
            (1, lambda: step01_generate_csv.run(job_folder, input_text, openai_api_key)),
            (2, lambda: step02_map_master.run(job_folder)),
            (3, lambda: step03_fetch_cmp.run(job_folder, dhan_api_key)),
            (4, lambda: step04_generate_charts.run(job_folder, dhan_api_key)),
            (5, lambda: step05_fetch_technical.run(job_folder, dhan_api_key)),
            (6, lambda: step06_fetch_fundamental.run(job_folder)),
            (7, lambda: step07_generate_analysis.run(job_folder, openai_api_key)),
        ]
        
        for step_num, step_func in steps_before_review:
            # Update current step
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE jobs 
                    SET current_step = %s, progress = %s, updated_at = %s
                    WHERE id = %s
                """, (step_num, int((step_num / 8) * 100), datetime.now(), job_id))
                
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = 'running', started_at = %s
                    WHERE job_id = %s AND step_number = %s
                """, (datetime.now(), job_id, step_num))
            
            # Run step
            result = step_func()
            
            if not result.get('success'):
                # Mark step and job as failed
                with get_db_cursor(commit=True) as cursor:
                    cursor.execute("""
                        UPDATE job_steps 
                        SET status = 'failed', message = %s, ended_at = %s
                        WHERE job_id = %s AND step_number = %s
                    """, (result.get('error', 'Unknown error'), datetime.now(), job_id, step_num))
                    
                    cursor.execute("""
                        UPDATE jobs 
                        SET status = 'failed', updated_at = %s
                        WHERE id = %s
                    """, (datetime.now(), job_id))
                
                return
            
            # Mark step as completed
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = 'success', message = 'Step completed successfully', ended_at = %s
                    WHERE job_id = %s AND step_number = %s
                """, (datetime.now(), job_id, step_num))
        
        # After Step 7, set status to awaiting CSV review
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs 
                SET status = 'awaiting_csv_review', current_step = 7, progress = 87, updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
        
    except Exception as e:
        print(f"Error processing Premium Rationale job {job_id}: {str(e)}")
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs 
                SET status = 'failed', updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))

@premium_rationale_bp.route('/jobs/<job_id>', methods=['GET'])
@jwt_required()
def get_job_status(job_id):
    """Get job status and progress"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check access
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT j.*, c.channel_name, c.platform
                FROM jobs j
                LEFT JOIN channels c ON j.channel_id = c.id
                WHERE j.id = %s
            """, (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            cursor.execute("""
                SELECT id, job_id, step_number, step_name, status, started_at, ended_at, message
                FROM job_steps
                WHERE job_id = %s
                ORDER BY step_number
            """, (job_id,))
            steps = cursor.fetchall()
            
            # Fetch unsigned and signed PDF paths from saved_rationale table
            unsigned_pdf_path = None
            signed_pdf_path = None
            if job['status'] in ('signed', 'completed'):
                cursor.execute("""
                    SELECT unsigned_pdf_path, signed_pdf_path
                    FROM saved_rationale
                    WHERE job_id = %s
                """, (job_id,))
                rationale = cursor.fetchone()
                if rationale:
                    unsigned_pdf_path = rationale.get('unsigned_pdf_path')
                    signed_pdf_path = rationale.get('signed_pdf_path')
        
        # Check for PDF file (for pdf_ready status)
        pdf_path = None
        if job['status'] in ['pdf_ready', 'signed', 'completed']:
            pdf_file = os.path.join(job['folder_path'], 'pdf', 'premium_rationale.pdf')
            if os.path.exists(pdf_file):
                pdf_path = pdf_file
                
                # For 'completed' status, if no unsigned_pdf_path from database, use pdf_file
                if job['status'] == 'completed' and not unsigned_pdf_path:
                    unsigned_pdf_path = pdf_file
        
        return jsonify({
            'jobId': job['id'],
            'status': job['status'],
            'progress': job['progress'],
            'currentStep': job['current_step'],
            'title': job['title'],
            'platform': job.get('platform'),
            'channelName': job.get('channel_name'),
            'callDate': job['date'].isoformat() if job['date'] else None,
            'callTime': str(job['time']) if job['time'] else None,
            'createdAt': job['created_at'].isoformat() if job['created_at'] else None,
            'pdfPath': pdf_path,
            'unsignedPdfPath': unsigned_pdf_path,
            'signedPdfPath': signed_pdf_path,
            'job_steps': [
                {
                    'id': step['id'],
                    'job_id': step['job_id'],
                    'step_number': step['step_number'],
                    'step_name': step['step_name'],
                    'status': step['status'],
                    'started_at': step['started_at'].isoformat() if step.get('started_at') else None,
                    'completed_at': step['ended_at'].isoformat() if step.get('ended_at') else None,
                    'error_message': step.get('message')
                }
                for step in steps
            ]
        }), 200
        
    except Exception as e:
        print(f"Error getting job status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@premium_rationale_bp.route('/jobs/<job_id>/csv', methods=['GET'])
@jwt_required()
def get_analysis_csv(job_id):
    """Get the analysis CSV for review after Step 7"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check access
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT folder_path, status FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
        
        # Resolve path to fix double "backend" issue
        resolved_folder = resolve_job_folder_path(job['folder_path'])
        csv_path = os.path.join(resolved_folder, 'analysis', 'stocks_with_analysis.csv')
        
        if not os.path.exists(csv_path):
            print(f"CSV not found at: {csv_path}")
            return jsonify({'error': 'CSV file not found'}), 404
        
        return send_file(csv_path, mimetype='text/csv', as_attachment=True, 
                        download_name=f'{job_id}_analysis.csv')
        
    except Exception as e:
        print(f"Error getting CSV: {str(e)}")
        return jsonify({'error': str(e)}), 500

@premium_rationale_bp.route('/jobs/<job_id>/upload-csv', methods=['POST'])
@jwt_required()
def upload_edited_csv(job_id):
    """Upload edited CSV and replace the existing one"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check access
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        if 'csv_file' not in request.files:
            return jsonify({'error': 'No CSV file provided'}), 400
        
        file = request.files['csv_file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT folder_path FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
        
        # Resolve path and save uploaded CSV
        resolved_folder = resolve_job_folder_path(job['folder_path'])
        csv_path = os.path.join(resolved_folder, 'analysis', 'stocks_with_analysis.csv')
        file.save(csv_path)
        
        print(f"✅ Uploaded CSV saved to: {csv_path}")
        
        return jsonify({
            'success': True,
            'message': 'CSV uploaded successfully'
        }), 200
        
    except Exception as e:
        print(f"Error uploading CSV: {str(e)}")
        return jsonify({'error': str(e)}), 500

@premium_rationale_bp.route('/jobs/<job_id>/continue-to-pdf', methods=['POST'])
@jwt_required()
def continue_to_pdf(job_id):
    """Continue to Step 8 (PDF generation) after CSV review/upload"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check access
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        # Start Step 8 in background
        thread = threading.Thread(target=run_step_8_async, args=(job_id,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'PDF generation started'
        }), 200
        
    except Exception as e:
        print(f"Error continuing to PDF: {str(e)}")
        return jsonify({'error': str(e)}), 500

def run_step_8_async(job_id):
    """Run Step 8 (PDF generation) in background"""
    try:
        from backend.pipeline.premium import step08_generate_pdf
        
        # Update status
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs 
                SET status = 'processing', current_step = 8, progress = 95, updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
            
            cursor.execute("""
                UPDATE job_steps 
                SET status = 'running', started_at = %s
                WHERE job_id = %s AND step_number = 8
            """, (datetime.now(), job_id))
            
            cursor.execute("SELECT folder_path FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
            
            # Get PDF template config
            cursor.execute("SELECT * FROM pdf_template LIMIT 1")
            template = cursor.fetchone()
        
        # Run Step 8
        result = step08_generate_pdf.run(job['folder_path'], template)
        
        if result.get('success'):
            # Mark as PDF ready
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE jobs 
                    SET status = 'pdf_ready', progress = 100, updated_at = %s
                    WHERE id = %s
                """, (datetime.now(), job_id))
                
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = 'success', message = 'PDF generated successfully', ended_at = %s
                    WHERE job_id = %s AND step_number = 8
                """, (datetime.now(), job_id))
        else:
            # Mark as failed
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE jobs 
                    SET status = 'failed', updated_at = %s
                    WHERE id = %s
                """, (datetime.now(), job_id))
                
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = 'failed', message = %s, ended_at = %s
                    WHERE job_id = %s AND step_number = 8
                """, (result.get('error', 'Unknown error'), datetime.now(), job_id))
        
    except Exception as e:
        print(f"Error in Step 8: {str(e)}")
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs 
                SET status = 'failed', updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))

@premium_rationale_bp.route('/restart-step/<job_id>/<int:step_number>', methods=['POST'])
@jwt_required()
def restart_step(job_id, step_number):
    """Restart Premium Rationale pipeline from a specific step"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check authorization
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        # Validate step number (Premium Rationale has 8 steps)
        if step_number < 1 or step_number > 8:
            return jsonify({'error': 'Invalid step number. Must be between 1 and 8'}), 400
        
        # Check if job exists
        with get_db_cursor() as cursor:
            cursor.execute("SELECT id, status, folder_path FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
        
        # Reset the specified step and all subsequent steps to 'pending'
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE job_steps
                SET status = 'pending', message = NULL, 
                    started_at = NULL, ended_at = NULL
                WHERE job_id = %s AND step_number >= %s
            """, (job_id, step_number))
            
            # Mark previous steps as success if they exist
            if step_number > 1:
                cursor.execute("""
                    UPDATE job_steps
                    SET status = 'success'
                    WHERE job_id = %s AND step_number < %s AND status != 'success'
                """, (job_id, step_number))
            
            # Update job status to processing and reset progress
            # Progress should reflect that we're starting from step_number
            # If restarting from step 2, we've completed step 1, so progress = 1/8 = 12%
            progress = int(((step_number - 1) / 8) * 100)
            cursor.execute("""
                UPDATE jobs 
                SET status = 'processing', current_step = %s, progress = %s, updated_at = %s
                WHERE id = %s
            """, (step_number, progress, datetime.now(), job_id))
        
        # Restart pipeline execution from the specified step in background thread
        def run_pipeline_from_step():
            try:
                from backend.pipeline.premium import (
                    step01_generate_csv, step02_map_master, step03_fetch_cmp,
                    step04_generate_charts, step05_fetch_technical, step06_fetch_fundamental,
                    step07_generate_analysis, step08_generate_pdf
                )
                
                # Get necessary data
                with get_db_cursor() as cursor:
                    cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
                    job = cursor.fetchone()
                    
                    cursor.execute("SELECT key_value FROM api_keys WHERE LOWER(provider) = 'openai'")
                    openai_key_row = cursor.fetchone()
                    openai_api_key = openai_key_row['key_value'] if openai_key_row else None
                    
                    cursor.execute("SELECT key_value FROM api_keys WHERE LOWER(provider) = 'dhan'")
                    dhan_key_row = cursor.fetchone()
                    dhan_api_key = dhan_key_row['key_value'] if dhan_key_row else None
                    
                    cursor.execute("SELECT * FROM pdf_template LIMIT 1")
                    template = cursor.fetchone()
                
                job_folder = job['folder_path']
                
                # Read input text for Step 1
                input_file_path = os.path.join(job_folder, 'input.txt')
                with open(input_file_path, 'r', encoding='utf-8') as f:
                    input_text = f.read()
                
                # Define step functions
                steps_config = [
                    (1, lambda: step01_generate_csv.run(job_folder, input_text, openai_api_key)),
                    (2, lambda: step02_map_master.run(job_folder)),
                    (3, lambda: step03_fetch_cmp.run(job_folder, dhan_api_key)),
                    (4, lambda: step04_generate_charts.run(job_folder, dhan_api_key)),
                    (5, lambda: step05_fetch_technical.run(job_folder, dhan_api_key)),
                    (6, lambda: step06_fetch_fundamental.run(job_folder)),
                    (7, lambda: step07_generate_analysis.run(job_folder, openai_api_key)),
                    (8, lambda: step08_generate_pdf.run(job_folder, template)),
                ]
                
                # Determine end step (pause at Step 7 for CSV review if restarting before Step 8)
                end_step = 8 if step_number >= 8 else 7
                
                # Run steps
                all_success = True
                for step_num, step_func in steps_config:
                    if step_num < step_number:
                        continue  # Skip steps before restart point
                    if step_num > end_step:
                        break
                    
                    # Update current step
                    with get_db_cursor(commit=True) as cursor:
                        cursor.execute("""
                            UPDATE jobs 
                            SET current_step = %s, progress = %s, updated_at = %s
                            WHERE id = %s
                        """, (step_num, int((step_num / 8) * 100), datetime.now(), job_id))
                        
                        cursor.execute("""
                            UPDATE job_steps 
                            SET status = 'running', started_at = %s
                            WHERE job_id = %s AND step_number = %s
                        """, (datetime.now(), job_id, step_num))
                    
                    # Run step
                    result = step_func()
                    
                    if not result.get('success'):
                        # Mark step and job as failed
                        with get_db_cursor(commit=True) as cursor:
                            cursor.execute("""
                                UPDATE job_steps 
                                SET status = 'failed', message = %s, ended_at = %s
                                WHERE job_id = %s AND step_number = %s
                            """, (result.get('error', 'Unknown error'), datetime.now(), job_id, step_num))
                            
                            cursor.execute("""
                                UPDATE jobs 
                                SET status = 'failed', updated_at = %s
                                WHERE id = %s
                            """, (datetime.now(), job_id))
                        
                        all_success = False
                        break
                    
                    # Mark step as completed
                    with get_db_cursor(commit=True) as cursor:
                        cursor.execute("""
                            UPDATE job_steps 
                            SET status = 'success', message = 'Step completed successfully', ended_at = %s
                            WHERE job_id = %s AND step_number = %s
                        """, (datetime.now(), job_id, step_num))
                
                # Update final status
                if all_success:
                    if end_step == 7:
                        # Paused for CSV review
                        with get_db_cursor(commit=True) as cursor:
                            cursor.execute("""
                                UPDATE jobs 
                                SET status = 'awaiting_csv_review', current_step = 7, progress = 87, updated_at = %s
                                WHERE id = %s
                            """, (datetime.now(), job_id))
                    else:
                        # Completed
                        with get_db_cursor(commit=True) as cursor:
                            cursor.execute("""
                                UPDATE jobs 
                                SET status = 'pdf_ready', progress = 100, updated_at = %s
                                WHERE id = %s
                            """, (datetime.now(), job_id))
                        
            except Exception as e:
                print(f"Pipeline restart error for job {job_id}: {str(e)}")
                with get_db_cursor(commit=True) as cursor:
                    cursor.execute("""
                        UPDATE jobs 
                        SET status = 'failed', updated_at = %s
                        WHERE id = %s
                    """, (datetime.now(), job_id))
        
        # Start background thread
        thread = threading.Thread(target=run_pipeline_from_step)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Pipeline restarted from step {step_number}'
        }), 200
        
    except Exception as e:
        print(f"Error restarting step: {str(e)}")
        return jsonify({'error': f'Failed to restart step: {str(e)}'}), 500

@premium_rationale_bp.route('/job/<job_id>/save', methods=['POST'])
@jwt_required()
def save_rationale(job_id):
    """Save Premium Rationale to saved_rationale table"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check authorization
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        # Get job details
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, channel_id, tool_used, title, 
                       date, youtube_url
                FROM jobs WHERE id = %s
            """, (job_id,))
            
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
        
        # Path to unsigned PDF
        pdf_path = os.path.join('backend', 'job_files', job_id, 'pdf', 'premium_rationale.pdf')
        
        if not os.path.exists(pdf_path):
            return jsonify({'error': 'PDF not found. Please generate PDF first.'}), 404
        
        # Check if already saved
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id FROM saved_rationale WHERE job_id = %s
            """, (job_id,))
            existing = cursor.fetchone()
        
        if existing:
            # Update existing entry with latest PDF path
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE saved_rationale
                    SET unsigned_pdf_path = %s, 
                        title = %s,
                        date = %s,
                        updated_at = %s
                    WHERE job_id = %s
                    RETURNING id
                """, (pdf_path, job['title'], job['date'], datetime.now(), job_id))
                
                result = cursor.fetchone()
                rationale_id = result['id'] if result else None
        else:
            # Create new entry
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    INSERT INTO saved_rationale (
                        job_id, channel_id, tool_used, title, 
                        date, youtube_url, unsigned_pdf_path, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    job_id, job['channel_id'], job['tool_used'], job['title'],
                    job['date'], job['youtube_url'], pdf_path, datetime.now()
                ))
                
                result = cursor.fetchone()
                rationale_id = result['id'] if result else None
        
        # Update job status to 'completed'
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs
                SET status = 'completed', updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
        
        # Create activity log
        from backend.api.activity_logs import create_activity_log
        create_activity_log(
            current_user_id,
            'saved_rationale',
            f"Saved Premium Rationale: {job['title']}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Rationale saved successfully',
            'rationaleId': rationale_id
        }), 200
        
    except Exception as e:
        print(f"Error saving rationale: {str(e)}")
        return jsonify({'error': str(e)}), 500

@premium_rationale_bp.route('/jobs/<job_id>', methods=['DELETE'])
@jwt_required()
def delete_job(job_id):
    """Delete a Premium Rationale job and all its files"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check authorization
        has_access, error_msg = check_job_access(job_id, current_user_id)
        if not has_access:
            return jsonify({'error': error_msg}), 403
        
        # Check if job exists
        with get_db_cursor() as cursor:
            cursor.execute("SELECT id, folder_path FROM jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
            
            if not job:
                return jsonify({'error': 'Job not found'}), 404
        
        # Delete job from database (will cascade delete job_steps)
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        
        # Delete job directory and all files
        resolved_folder = resolve_job_folder_path(job['folder_path'])
        if resolved_folder and os.path.exists(resolved_folder):
            shutil.rmtree(resolved_folder)
            print(f"✅ Deleted job directory: {resolved_folder}")
        
        # Create activity log
        from backend.api.activity_logs import create_activity_log
        create_activity_log(
            current_user_id,
            'premium_rationale',
            f"Deleted Premium Rationale job: {job_id}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Job deleted successfully'
        }), 200
        
    except Exception as e:
        print(f"Error deleting job: {str(e)}")
        return jsonify({'error': f'Failed to delete job: {str(e)}'}), 500
