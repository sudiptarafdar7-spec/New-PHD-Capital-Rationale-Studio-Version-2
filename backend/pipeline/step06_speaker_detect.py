"""
Step 6: Detect Speakers (Anchor and Pradip) using OpenAI
Identifies which speaker labels correspond to Anchor and Pradip
"""

def detect_speakers(job_id, transcript_path, openai_api_key):
    """
    Detect which speakers are Anchor and Pradip
    
    Input: transcript_english.txt
    Output: detected_speakers.txt
    """
    # TODO: Implement OpenAI speaker detection
    # - Send transcript to OpenAI
    # - Prompt: "Identify which speaker is the Anchor (host) and which is Pradip (analyst)"
    # - Parse response and create mapping (e.g., Speaker_A = Anchor, Speaker_B = Pradip)
    
    output_path = f"backend/job_files/{job_id}/analysis/detected_speakers.txt"
    return output_path
