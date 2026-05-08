"""
Step 3: Transcribe Audio using AssemblyAI
Transcribes audio with speaker recognition/diarization
"""

import assemblyai as aai
from datetime import timedelta
import pandas as pd
import os

def transcribe_audio(job_id, audio_path, assemblyai_api_key, language_code="hi"):
    """
    Transcribe audio using AssemblyAI with speaker labels
    
    Input: audio_16k_mono.wav
    Output: transcript.csv, transcript.txt
    """
    
    print(f"🎙️ Starting AssemblyAI transcription for job {job_id} (lang={language_code})...")
    
    # Set API key
    aai.settings.api_key = assemblyai_api_key
    
    # Configure transcription with speaker labels and word boost
    # Using 'nano' model for faster transcription (up to 5x faster than 'best')
    # while maintaining good accuracy for speaker diarization
    config = aai.TranscriptionConfig(
        speaker_labels=True,
        speech_models=["nano"],
        language_code=language_code,
        punctuate=True,
        format_text=True,
        word_boost=[
            "Nifty", "Sensex", "Reliance", "HDFC Bank", "Infosys", "Tata Motors",
            "BSE", "NSE", "Nifty 50", "Nifty 200", "Bank Nifty",
            "Buy on Dip", "Stop Loss", "CMP", "target", "support",
            "resistance", "breakout", "SEBI", "intraday", "swing", "equity",
            "derivative", "F&O", "bullish", "bearish", "small-cap", "mid-cap",
            "large-cap", "The Bonus", "Money 9", "Opening Buzz",
            "Sandeep Grover", "Sandeep", "Pradip", "Pradip Halder",
            "Mr. Halder", "Halder"
        ],
        boost_param=aai.WordBoost.high
    )
    
    print(f"⚡ Using fast 'nano' model with Hindi language for optimized transcription")
    
    transcriber = aai.Transcriber(config=config)
    
    # Verify audio file exists
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    print(f"⏳ Transcribing audio from: {audio_path}")
    
    # Transcribe
    try:
        transcript = transcriber.transcribe(audio_path)
        print("✅ Transcription complete!")
    except Exception as e:
        raise Exception(f"AssemblyAI transcription failed: {str(e)}")
    
    # Helper to format time as HH:MM:SS
    def format_time(ms):
        td = timedelta(milliseconds=ms)
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    
    # Collect transcript utterances with speaker labels
    data = []
    if transcript.utterances:
        for utt in transcript.utterances:
            start = format_time(utt.start)
            end = format_time(utt.end)
            data.append([f"Speaker {utt.speaker}", start, end, utt.text])
    else:
        # Fallback if utterances missing
        data.append(["Speaker 1", "00:00:00", format_time(transcript.audio_duration), transcript.text])
    
    # Create DataFrame
    df_out = pd.DataFrame(data, columns=["Speaker", "Start Time", "End Time", "Transcription"])
    
    # Ensure chronological order
    df_out["SortKey"] = pd.to_timedelta(df_out["Start Time"])
    df_out = df_out.sort_values("SortKey").drop(columns=["SortKey"]).reset_index(drop=True)
    
    # Create transcripts directory
    transcripts_dir = f"backend/job_files/{job_id}/transcripts"
    os.makedirs(transcripts_dir, exist_ok=True)
    
    # Save to CSV
    csv_path = os.path.join(transcripts_dir, "transcript.csv")
    df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"💾 Transcript saved as {csv_path}")
    
    # Save to TXT (speaker-friendly format)
    txt_path = os.path.join(transcripts_dir, "transcript.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for i, row in df_out.iterrows():
            f.write(f"[{row['Speaker']}] {row['Start Time']} - {row['End Time']} | {row['Transcription']}\n")
    print(f"💾 Transcript also saved as {txt_path}")
    
    # Print preview
    print("\n📑 Transcript Preview (first 5 utterances):\n")
    for i, row in df_out.head(5).iterrows():
        print(f"[{row['Speaker']}] {row['Start Time']} - {row['End Time']} | {row['Transcription']}")
    
    if len(df_out) > 5:
        print(f"\n... and {len(df_out) - 5} more utterances")
    
    return [csv_path, txt_path]
