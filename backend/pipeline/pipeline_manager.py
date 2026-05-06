"""
Pipeline Manager for Media Rationale Processing
Orchestrates all 15 steps of the video analysis pipeline
"""
import os
from backend.utils.database import get_db_cursor
from backend.pipeline.step01_download_audio import download_audio
from backend.pipeline.step02_download_captions import download_captions
from backend.pipeline.step03_assemblyai_transcribe import transcribe_audio
from backend.pipeline import step04_merge_transcripts
from backend.pipeline import step05_translate
from backend.pipeline import step06_detect_speakers
from backend.pipeline import step07_filter_transcription
from backend.pipeline import step08_extract_stocks
from backend.pipeline import step09_map_master_file
from backend.pipeline import step10_convert_timestamps
from backend.pipeline import step11_fetch_cmp
from backend.pipeline import step12_extract_analysis
from backend.pipeline import step13_generate_charts
from backend.pipeline import step14_generate_pdf
# Step 15 removed - it's not part of automatic pipeline (user actions only via API)
from datetime import datetime

# Pipeline step definitions matching frontend pipelineSteps
# NOTE: Step 15 removed - user actions (Save/Sign/Delete) handled via API endpoints only
PIPELINE_STEPS = [
    {'number': 1, 'name': 'Download Audio', 'description': 'Extract audio from YouTube video'},
    {'number': 2, 'name': 'Download Captions', 'description': 'Fetch auto-generated captions'},
    {'number': 3, 'name': 'Transcribe Audio', 'description': 'AssemblyAI transcription with speaker labels'},
    {'number': 4, 'name': 'Merge Transcripts', 'description': 'Combine captions and transcript data'},
    {'number': 5, 'name': 'Translate to English', 'description': 'Google Cloud Translation'},
    {'number': 6, 'name': 'Detect Speakers', 'description': 'Identify Anchor and Pradip using AI'},
    {'number': 7, 'name': 'Filter Transcription', 'description': 'Keep only Anchor & Pradip dialogue'},
    {'number': 8, 'name': 'Extract Stock Mentions', 'description': 'AI extraction of stock names and timestamps'},
    {'number': 9, 'name': 'Map Master File', 'description': 'Match stocks to api-scrip-master.csv'},
    {'number': 10, 'name': 'Convert Timestamps', 'description': 'Convert to absolute time and date'},
    {'number': 11, 'name': 'Fetch CMP', 'description': 'Get current market price from Dhan API'},
    {'number': 12, 'name': 'Extract Analysis', 'description': 'AI-generated stock analysis'},
    {'number': 13, 'name': 'Generate Charts', 'description': 'Fetch data and plot technical charts'},
    {'number': 14, 'name': 'Generate PDF', 'description': 'Create branded PDF report'},
]

def create_job_directory(job_id):
    """Create directory structure for job files"""
    base_path = os.path.join('backend', 'job_files', job_id)
    subdirs = ['audio', 'captions', 'transcripts', 'analysis', 'charts', 'output']
    
    for subdir in subdirs:
        os.makedirs(os.path.join(base_path, subdir), exist_ok=True)
    
    return base_path

def update_step_status(job_id, step_number, status, message=None, output_files=None):
    """Update the status of a specific pipeline step"""
    try:
        with get_db_cursor(commit=True) as cursor:
            if status == 'running':
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = %s, started_at = %s, message = %s
                    WHERE job_id = %s AND step_number = %s
                """, (status, datetime.now(), message, job_id, step_number))
            
            elif status in ['success', 'failed']:
                cursor.execute("""
                    UPDATE job_steps 
                    SET status = %s, ended_at = %s, message = %s, output_files = %s
                    WHERE job_id = %s AND step_number = %s
                """, (status, datetime.now(), message, output_files or [], job_id, step_number))
            
            # Update job's current step and progress
            if status == 'success':
                # Pipeline has 14 steps (Step 15 is API-only, not part of automatic pipeline)
                progress = int((step_number / 14) * 100)
                cursor.execute("""
                    UPDATE jobs 
                    SET current_step = %s, progress = %s, updated_at = %s
                    WHERE id = %s
                """, (step_number, progress, datetime.now(), job_id))
            
            return True
    except Exception as e:
        print(f"Error updating step status: {str(e)}")
        return False

def run_pipeline_step(job_id, step_number):
    """Execute a single pipeline step"""
    try:
        step_info = PIPELINE_STEPS[step_number - 1]
        
        # Update status to running
        update_step_status(job_id, step_number, 'running', f"Processing {step_info['description']}...")
        
        # Get job details from database
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT youtube_url FROM jobs WHERE id = %s
            """, (job_id,))
            job = cursor.fetchone()
            
            if not job:
                raise Exception(f"Job {job_id} not found")
        
        job_folder = os.path.join('backend', 'job_files', job_id)
        output_files = []
        message = None
        
        # Get cookies file path for steps that need it
        cookies_file = os.path.join('backend', 'youtube_cookies.txt')
        if not os.path.exists(cookies_file):
            cookies_file = None
        
        # Execute step based on step_number
        if step_number == 1:
            # Step 1: Download and prepare audio
            result = download_audio(
                job_id,
                job['youtube_url'],
                cookies_file
            )
            
            if not result['success']:
                raise Exception(result['error'])
            
            output_files = [result['raw_audio'], result['prepared_audio']]
            message = f"Audio downloaded and converted to 16kHz mono ({result['prepared_size_mb']} MB)"
        
        elif step_number == 2:
            # Step 2: Download auto-generated captions
            result = download_captions(
                job_id,
                job['youtube_url'],
                cookies_file
            )
            
            if not result['success']:
                raise Exception(result['error'])
            
            output_files = [result['captions_path']]
            message = f"Captions downloaded ({result['format']} format, {result['language']} language, {result['file_size_kb']} KB)"
        
        elif step_number == 3:
            # Step 3: Transcribe audio with AssemblyAI
            # Get AssemblyAI API key from database
            with get_db_cursor() as cursor:
                cursor.execute("""
                    SELECT key_value FROM api_keys 
                    WHERE LOWER(provider) = 'assemblyai'
                """)
                api_key_row = cursor.fetchone()
                
                if not api_key_row:
                    raise Exception("AssemblyAI API key not found in database. Please add it in Settings > API Keys.")
            
            assemblyai_api_key = api_key_row['key_value']
            audio_path = os.path.join(job_folder, 'audio', 'audio_16k_mono.wav')
            
            output_files = transcribe_audio(job_id, audio_path, assemblyai_api_key)
            message = f"Transcription completed with speaker detection"
        
        elif step_number == 4:
            # Step 4: Merge AssemblyAI transcript with YouTube captions
            result = step04_merge_transcripts.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 5:
            # Step 5: Translate to English using Google Cloud Translate
            # Get Google Cloud credentials path from database
            with get_db_cursor() as cursor:
                cursor.execute("""
                    SELECT key_value FROM api_keys 
                    WHERE LOWER(provider) = 'google_cloud' OR LOWER(provider) = 'google cloud'
                """)
                credentials_row = cursor.fetchone()
                
                if not credentials_row:
                    raise Exception("Google Cloud credentials not found in database. Please add the JSON file path in Settings > API Keys with provider 'Google Cloud'.")
            
            google_credentials_path = credentials_row['key_value']
            
            # Verify the credentials file exists
            if not os.path.exists(google_credentials_path):
                raise Exception(f"Google Cloud credentials file not found at: {google_credentials_path}")
            
            result = step05_translate.run(job_folder, google_credentials_path)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 6:
            # Step 6: Detect Speakers (Anchor & Pradip) using OpenAI
            result = step06_detect_speakers.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 7:
            # Step 7: Filter Transcription (Keep only Anchor & Pradip)
            result = step07_filter_transcription.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 8:
            # Step 8: Extract Stock Mentions (Pradip's analysis)
            result = step08_extract_stocks.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 9:
            # Step 9: Map Master File (Match stocks to master reference)
            result = step09_map_master_file.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 10:
            # Step 10: Convert Timestamps (Video time to actual clock time)
            result = step10_convert_timestamps.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 11:
            # Step 11: Fetch CMP (Current Market Price from Dhan API)
            result = step11_fetch_cmp.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 12:
            # Step 12: Extract Analysis (GPT-4o extracts Pradip's analysis)
            result = step12_extract_analysis.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 13:
            # Step 13: Generate Charts (Dhan API candlestick charts with indicators)
            result = step13_generate_charts.run(job_folder)
            
            if result['status'] == 'failed':
                raise Exception(result['message'])
            
            output_files = result['output_files']
            message = result['message']
        
        elif step_number == 14:
            # Step 14: Generate PDF (Professional SEBI-compliant report)
            pdf_path = step14_generate_pdf.generate_pdf_report(job_id)
            
            # Store full relative path for frontend to access
            output_files = [pdf_path]
            message = f"PDF generated: {os.path.basename(pdf_path)} (Path: {pdf_path})"
        
        # Step 15 is NOT part of automatic pipeline
        # It's triggered by user button clicks via API endpoints:
        # - /api/v1/saved-rationale/save (Save)
        # - /api/v1/saved-rationale/upload-signed (Save & Sign)
        # - /api/v1/media-rationale/job/{job_id} DELETE (Delete)
        
        else:
            # Step 15 or any invalid step - should not be executed
            if step_number == 15:
                raise Exception("Step 15 is not part of automatic pipeline. Use API endpoints for Save/Sign/Delete actions.")
            else:
                raise Exception(f"Invalid step number: {step_number}")
        
        # Update status to success
        update_step_status(
            job_id, 
            step_number, 
            'success', 
            message, 
            output_files
        )
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        print(f"Pipeline step {step_number} error: {error_msg}")
        update_step_status(job_id, step_number, 'failed', error_msg)
        return False

async def run_pipeline(job_id, start_step=1, end_step=15):
    """Run pipeline steps from start_step to end_step"""
    try:
        # Step 15 is NOT part of automatic pipeline - it's for user actions only
        # Pipeline runs from Step 1 to Step 14 automatically
        actual_end_step = min(end_step, 14)
        
        for step_num in range(start_step, actual_end_step + 1):
            success = run_pipeline_step(job_id, step_num)
            if not success:
                # Update job status to failed
                with get_db_cursor(commit=True) as cursor:
                    cursor.execute("""
                        UPDATE jobs 
                        SET status = 'failed', updated_at = %s
                        WHERE id = %s
                    """, (datetime.now(), job_id))
                return False
        
        # After Step 14, set status to 'pdf_ready' (awaiting user action)
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE jobs 
                SET status = 'pdf_ready', progress = 93, updated_at = %s
                WHERE id = %s
            """, (datetime.now(), job_id))
        
        return True
        
    except Exception as e:
        print(f"Pipeline error: {str(e)}")
        return False
