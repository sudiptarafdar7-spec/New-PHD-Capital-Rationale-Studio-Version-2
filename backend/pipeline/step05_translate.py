"""
Step 5: Translate to English using Google Cloud Translate API

Translates final_transcript.txt from Hindi/mixed language to English
while preserving speaker labels and timestamps.
"""

import os
import html
from google.cloud import translate_v2 as translate


def run(job_folder, google_credentials_path):
    """
    Translate transcript to English using Google Cloud Translate API.
    
    Args:
        job_folder: Path to job working directory
        google_credentials_path: Path to Google Cloud credentials JSON file
        
    Returns:
        dict with status, message, and output_files
    """
    print(f"\n{'='*60}")
    print("STEP 5: Translate to English")
    print(f"{'='*60}\n")
    
    try:
        # Set Google Cloud credentials
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = google_credentials_path
        
        # Initialize Translation Client
        print("🔑 Initializing Google Cloud Translate client...")
        translate_client = translate.Client()
        
        # Input/Output paths
        input_file = os.path.join(job_folder, "transcripts", "final_transcript.txt")
        output_file = os.path.join(job_folder, "transcripts", "transcript_english.txt")
        
        if not os.path.exists(input_file):
            return {
                'status': 'failed',
                'message': 'final_transcript.txt not found',
                'output_files': []
            }
        
        print(f"📄 Reading: {input_file}")
        
        # Load transcript lines
        with open(input_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        print(f"✓ Total lines to translate: {len(lines)}")
        
        # Translate each line
        translated_lines = []
        for i, raw_line in enumerate(lines):
            orig = raw_line.rstrip("\n")
            
            # Keep blank lines
            if not orig.strip():
                translated_lines.append("")
                print(f"Line {i+1}: ⏭ blank")
                continue
            
            # Unescape any HTML entities already present
            line = html.unescape(orig).strip()
            
            # Detect speaker/timestamp prefix if present
            if "|" in line:
                prefix, text = line.split("|", 1)
                text = text.strip()
                
                if text:
                    # Translate only the text part, preserve prefix
                    result = translate_client.translate(
                        text,
                        source_language="hi",
                        target_language="en",
                        format_="text"
                    )
                    eng = html.unescape(result["translatedText"])
                    translated_line = f"{prefix} | {eng}"
                else:
                    translated_line = line
            else:
                # No prefix, translate entire line
                result = translate_client.translate(
                    line,
                    source_language="hi",
                    target_language="en",
                    format_="text"
                )
                eng = html.unescape(result["translatedText"])
                translated_line = eng
            
            translated_lines.append(translated_line)
            print(f"Line {i+1}: ✅")
        
        # Save translated transcript
        with open(output_file, "w", encoding="utf-8") as f:
            for line in translated_lines:
                f.write(line + "\n")
        
        print(f"\n✅ Translated transcript saved: {output_file}")
        
        # Preview first 10 lines
        print("\n--- Preview (first 10 lines) ---")
        for line in translated_lines[:10]:
            print(line)
        print()
        
        return {
            'status': 'success',
            'message': f'Translated {len(translated_lines)} lines to English',
            'output_files': ['transcript_english.txt']
        }
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Error translating transcript: {str(e)}',
            'output_files': []
        }
