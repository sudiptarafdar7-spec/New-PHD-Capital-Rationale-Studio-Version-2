"""
Step 6: Detect Speakers (Anchor & Pradip) using OpenAI API

This step analyzes the English transcript to identify:
- The TV Anchor / interviewer
- Mr. Pradip Halder (the stock expert)

Input: transcript_english.txt
Output: detected_speakers.txt
"""

import os
import psycopg2
from openai import OpenAI


def get_openai_api_key():
    """Fetch OpenAI API key from database"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT key_value 
            FROM api_keys 
            WHERE LOWER(provider) = 'openai'
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            return result[0]
        else:
            raise ValueError("OpenAI API key not found in database")
    
    except Exception as e:
        raise Exception(f"Failed to fetch OpenAI API key: {str(e)}")


def run(job_folder):
    """
    Detect speakers using OpenAI API.
    
    Args:
        job_folder: Path to job working directory
        
    Returns:
        dict with status, message, and output_files
    """
    print(f"\n{'='*60}")
    print("STEP 6: Detect Speakers (Anchor & Pradip)")
    print(f"{'='*60}\n")

    try:
        # Get OpenAI API key from database
        print("🔑 Fetching OpenAI API key from database...")
        api_key = get_openai_api_key()
        
        # Initialize OpenAI client
        print("🤖 Initializing OpenAI client...")
        client = OpenAI(api_key=api_key)
        
        # Input/Output paths
        input_file = os.path.join(job_folder, "transcripts", "transcript_english.txt")
        output_file = os.path.join(job_folder, "analysis", "detected_speakers.txt")
        
        if not os.path.exists(input_file):
            return {
                'status': 'failed',
                'message': 'transcript_english.txt not found',
                'output_files': []
            }
        
        # Read transcript
        print(f"📄 Reading transcript: {input_file}")
        with open(input_file, "r", encoding="utf-8") as f:
            transcript_lines = [line.strip() for line in f.readlines() if line.strip()]
        
        print(f"✓ Loaded {len(transcript_lines)} lines")
        
        # Take first 200 lines as sample for speaker detection
        sample_size = min(200, len(transcript_lines))
        sample_text = "\n".join(transcript_lines[:sample_size])
        
        print(f"🔍 Using first {sample_size} lines as sample for detection...")
        
        # Create prompt for speaker detection
        prompt_detect_speakers = f"""
You are reading a stock market discussion transcript with multiple speakers (A, B, C, etc.).
Identify:
1. The speaker who is the TV Anchor / interviewer.
2. The speaker who is Mr. Pradip Halder (the stock expert).

Return ONLY in this format:
Anchor: Speaker X
Pradip: Speaker Y

Transcript sample:
{sample_text}
"""
        
        # Call OpenAI API
        print("🤖 Calling OpenAI API for speaker detection...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Detect the TV Anchor and Pradip Halder speakers."},
                {"role": "user", "content": prompt_detect_speakers}
            ],
            temperature=0.3,
            max_tokens=100
        )
        
        speakers_detected = response.choices[0].message.content.strip()
        
        print(f"\n✅ Detected Speakers:")
        print(speakers_detected)
        
        # Save detected speakers
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(speakers_detected)
        
        print(f"\n💾 Saved detected speakers: {output_file}")
        
        return {
            'status': 'success',
            'message': f'Successfully detected speakers: {speakers_detected}',
            'output_files': ['analysis/detected_speakers.txt']
        }
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Error detecting speakers: {str(e)}',
            'output_files': []
        }
