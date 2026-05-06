import os
import uuid
import threading
from datetime import datetime
from typing import Dict, List
from backend.utils.database import get_db_cursor
from .utils import create_input_csv
from .step01_fetch_cmp import fetch_cmp_for_stocks
from .step02_generate_charts import generate_charts_for_stocks
from .step03_generate_pdf import generate_manual_pdf

class ManualRationaleOrchestrator:
    
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.folder_path = os.path.join('backend', 'job_files', job_id)
        os.makedirs(self.folder_path, exist_ok=True)
        os.makedirs(os.path.join(self.folder_path, 'analysis'), exist_ok=True)
        os.makedirs(os.path.join(self.folder_path, 'charts'), exist_ok=True)
        os.makedirs(os.path.join(self.folder_path, 'pdf'), exist_ok=True)
    
    def update_job_status(self, status: str, progress: int = 0, current_step: int = 0):
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE jobs SET status = %s, progress = %s, current_step = %s, updated_at = %s WHERE id = %s",
                (status, progress, current_step, datetime.now(), self.job_id)
            )
    
    def update_step_status(self, step_number: int, status: str, message: str = '', output_files: list = None):
        with get_db_cursor(commit=True) as cursor:
            if status == 'running':
                cursor.execute(
                    "UPDATE job_steps SET status = %s, started_at = %s WHERE job_id = %s AND step_number = %s",
                    (status, datetime.now(), self.job_id, step_number)
                )
            elif status in ['success', 'failed']:
                if output_files:
                    import json
                    cursor.execute(
                        "UPDATE job_steps SET status = %s, message = %s, ended_at = %s, output_files = %s WHERE job_id = %s AND step_number = %s",
                        (status, message or '', datetime.now(), output_files, self.job_id, step_number)
                    )
                else:
                    cursor.execute(
                        "UPDATE job_steps SET status = %s, message = %s, ended_at = %s WHERE job_id = %s AND step_number = %s",
                        (status, message or '', datetime.now(), self.job_id, step_number)
                    )
    
    def run_pipeline(self):
        try:
            # Create input.csv with all master data enrichment
            print(f"📄 Creating input.csv for job {self.job_id}...")
            input_csv_path = create_input_csv(self.job_id, self.folder_path)
            print(f"✓ input.csv created: {input_csv_path}")
            
            # Start the 3-step pipeline
            self.update_job_status('processing', progress=0, current_step=1)
            
            # Step 1: Fetch CMP
            self.update_step_status(1, 'running')
            stocks_with_cmp = fetch_cmp_for_stocks(self.job_id, self.folder_path)
            self.update_step_status(1, 'success', 'CMP fetched successfully')
            self.update_job_status('processing', progress=33, current_step=2)
            
            self.update_step_status(2, 'running')
            stocks_with_charts = generate_charts_for_stocks(self.job_id, self.folder_path, stocks_with_cmp)
            self.update_step_status(2, 'success', 'Charts generated successfully')
            self.update_job_status('processing', progress=66, current_step=3)
            
            self.update_step_status(3, 'running')
            pdf_path = generate_manual_pdf(self.job_id, self.folder_path, stocks_with_charts)
            self.update_step_status(3, 'success', 'PDF generated successfully', output_files=[pdf_path])
            
            # Save PDF filename to payload
            pdf_filename = os.path.basename(pdf_path)
            with get_db_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE jobs 
                    SET payload = jsonb_set(COALESCE(payload, '{}'::jsonb), '{pdf_filename}', to_jsonb(%s::text))
                    WHERE id = %s
                """, (pdf_filename, self.job_id))
            
            self.update_job_status('pdf_ready', progress=100, current_step=3)
            
            print(f"✓ Manual Rationale pipeline completed for job {self.job_id}")
            print(f"✓ PDF saved: {pdf_filename}")
            
        except Exception as e:
            print(f"✗ Pipeline failed for job {self.job_id}: {str(e)}")
            current_step = 1
            with get_db_cursor() as cursor:
                cursor.execute("SELECT current_step FROM jobs WHERE id = %s", (self.job_id,))
                result = cursor.fetchone()
                if result:
                    current_step = result['current_step']
            
            self.update_step_status(current_step, 'failed', str(e))
            self.update_job_status('failed', current_step=current_step)
    
    def run_async(self):
        thread = threading.Thread(target=self.run_pipeline)
        thread.daemon = True
        thread.start()
