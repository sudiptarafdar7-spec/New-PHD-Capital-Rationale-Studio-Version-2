"""
Step 1: Download Audio from YouTube Video
PRIMARY: RapidAPI youtube-mp36 (100% tested in Google Colab)
FALLBACK: yt-dlp with cookies and rotating clients
"""
import os
import subprocess
import requests
import random
import time
from yt_dlp import YoutubeDL
from backend.pipeline.fetch_video_data import extract_video_id
from backend.utils.database import get_db_cursor


def download_audio_rapidapi(video_id, audio_folder):
    """
    PRIMARY METHOD: Download audio using RapidAPI youtube-mp36
    
    This method is 100% tested and working in Google Colab.
    Uses innertube API through RapidAPI for reliable downloads.
    
    Args:
        video_id: YouTube video ID (11 characters)
        audio_folder: Output directory for audio files
    
    Returns:
        str: Path to downloaded MP3 file, or None if failed
    """
    print("\n" + "="*60)
    print("🎯 PRIMARY METHOD: RapidAPI youtube-mp36")
    print("="*60)
    
    try:
        # Fetch RapidAPI key from database
        rapidapi_key = None
        try:
            with get_db_cursor() as cursor:
                cursor.execute("SELECT key_value FROM api_keys WHERE provider = %s", ('rapidapi_video_transcript',))
                result = cursor.fetchone()
                if result:
                    rapidapi_key = result['key_value']
        except Exception as db_error:
            print(f"⚠️ Database error fetching API key: {db_error}")
        
        if not rapidapi_key:
            print("❌ RapidAPI key not configured in database (provider: rapidapi_video_transcript)")
            print("   Please add it in Settings → API Keys page")
            return None
        
        # Step 1: Get MP3 download link from RapidAPI
        api_url = "https://youtube-mp36.p.rapidapi.com/dl"
        querystring = {"id": video_id}
        
        headers = {
            "x-rapidapi-key": rapidapi_key,
            "x-rapidapi-host": "youtube-mp36.p.rapidapi.com"
        }
        
        print(f"📡 Requesting MP3 link for video ID: {video_id}")
        
        # Poll RapidAPI with retry logic (video processing can take time)
        max_retries = 12  # 12 retries × 5 seconds = 1 minute max wait
        retry_delay = 5   # Wait 5 seconds between retries
        data = None
        
        for attempt in range(1, max_retries + 1):
            response = requests.get(api_url, headers=headers, params=querystring, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            status = data.get("status")
            progress = data.get("progress", 0)
            
            # Success case: conversion complete
            if status == "ok" and data.get("link"):
                print(f"✅ API Response: {data}")
                break
            
            # Processing case: video is being converted
            elif status == "processing":
                if attempt == 1:
                    print(f"⏳ Video is being processed by RapidAPI (progress: {progress}%)")
                    print(f"   Polling every {retry_delay} seconds (max {max_retries} attempts)...")
                else:
                    print(f"   Attempt {attempt}/{max_retries} - Progress: {progress}%")
                
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"Timeout: Video still processing after {max_retries * retry_delay} seconds. Progress: {progress}%. Try again in a few minutes.")
            
            # Error case: API returned error status
            else:
                raise Exception(f"API returned unexpected status. Response: {data}")
        
        # Final validation
        if not data:
            raise Exception("No response received from RapidAPI")
        
        if data.get("status") != "ok" or not data.get("link"):
            raise Exception(f"API did not return a valid link after {max_retries} attempts. Response: {data}")
        
        mp3_url = data["link"]
        title = data.get("title", "audio").replace("/", "_").replace("\\", "_").replace(":", "_")
        
        # Step 2: Download the MP3 file with proper headers
        print(f"⏬ Downloading audio: {title}")
        
        download_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Referer": "https://youtube-mp36.p.rapidapi.com/",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }
        
        # Download with streaming to avoid corrupted files
        output_path = os.path.join(audio_folder, "raw_audio.mp3")
        
        with requests.get(mp3_url, headers=download_headers, stream=True, 
                         allow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        # Verify file size (ensure it's not corrupted)
        file_size = os.path.getsize(output_path)
        if file_size < 1024:  # Less than 1KB is definitely corrupted
            raise Exception(f"Downloaded file is corrupted (only {file_size} bytes)")
        
        print(f"✅ Download complete: {output_path}")
        print(f"📦 File size: {round(file_size / (1024 * 1024), 2)} MB")
        
        return output_path
        
    except Exception as e:
        print(f"❌ RapidAPI method failed: {str(e)}")
        return None


def download_audio_ytdlp(youtube_url, audio_folder, cookies_file_path):
    """
    FALLBACK METHOD: Download audio using yt-dlp with cookies and rotating clients
    
    Uses uploaded youtube_cookies.txt and multiple client strategies:
    - tv_html5 (strongest bypass)
    - ios (mobile client)
    - android (mobile client)
    
    Args:
        youtube_url: Full YouTube URL
        audio_folder: Output directory for audio files
        cookies_file_path: Path to cookies.txt file
    
    Returns:
        str: Path to downloaded audio file, or None if failed
    """
    print("\n" + "="*60)
    print("🔄 FALLBACK METHOD: yt-dlp with cookies & rotating clients")
    print("="*60)
    
    # Check if cookies file exists
    using_cookies = os.path.exists(cookies_file_path)
    if using_cookies:
        print(f"✅ Using cookies from: {cookies_file_path}")
    else:
        print(f"⚠️  No cookies found at: {cookies_file_path}")
        print("   Proceeding without cookies (may fail for restricted videos)")
    
    # Randomized user agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
    ]
    
    output_template = os.path.join(audio_folder, "raw_audio.%(ext)s")
    
    # yt-dlp configuration with rotating clients
    ydl_opts = {
        "format": "bestaudio/best",
        
        # CRITICAL: Best YouTube clients to bypass restrictions
        "youtube_include_dash_manifest": False,
        "youtube_skip_dash_manifest": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_html5", "ios", "android"],
                "player_skip": ["web"]
            }
        },
        
        # Output template
        "outtmpl": output_template,
        
        # Convert to mp3
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        
        # Cookies support (if available)
        "cookiefile": cookies_file_path if using_cookies else None,
        
        # Networking stability
        "nocheckcertificate": True,
        "forceipv4": True,
        "retries": 20,
        "fragment_retries": 20,
        
        # Randomized user-agent
        "http_headers": {
            "User-Agent": random.choice(USER_AGENTS)
        },
        
        # Logging
        "verbose": True,
        "quiet": False,
    }
    
    # Remove None values
    ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}
    
    try:
        print(f"⏬ Attempting download with yt-dlp...")
        print(f"🎲 Using randomized user agent for anti-fingerprinting")
        print(f"🔧 Rotating clients: tv_html5, ios, android")
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        
        # Find the downloaded file
        downloaded_file = None
        for ext in ['mp3', 'webm', 'm4a', 'mp4', 'opus', 'ogg']:
            test_path = os.path.join(audio_folder, f"raw_audio.{ext}")
            if os.path.exists(test_path):
                downloaded_file = test_path
                break
        
        if not downloaded_file:
            raise FileNotFoundError("Audio file not found after yt-dlp download")
        
        file_size = os.path.getsize(downloaded_file)
        print(f"✅ yt-dlp download complete: {downloaded_file}")
        print(f"📦 File size: {round(file_size / (1024 * 1024), 2)} MB")
        
        return downloaded_file
        
    except Exception as e:
        print(f"❌ yt-dlp method failed: {str(e)}")
        return None


def download_audio(job_id, youtube_url, cookies_file=None):
    """
    Master function to download YouTube audio with dual-method fallback
    
    PRIMARY: RapidAPI youtube-mp36 (fast, reliable, 100% tested)
    FALLBACK: yt-dlp with cookies and rotating clients
    
    Args:
        job_id: Job identifier
        youtube_url: YouTube video URL (supports all formats: regular, live, shorts, etc.)
        cookies_file: Optional (uses uploaded cookies if available)
    
    Returns:
        dict: {
            'success': bool,
            'raw_audio': str,
            'prepared_audio': str,
            'raw_size_mb': float,
            'prepared_size_mb': float,
            'error': str or None
        }
    """
    print("\n" + "="*60)
    print("🎧 YOUTUBE AUDIO DOWNLOADER - DUAL-METHOD FALLBACK")
    print("="*60)
    print(f"📹 Video URL: {youtube_url}")
    
    # Setup paths
    audio_folder = os.path.join("backend", "job_files", job_id, "audio")
    os.makedirs(audio_folder, exist_ok=True)
    
    prepared_audio_path = os.path.join(audio_folder, "audio_16k_mono.wav")
    cookies_file_path = os.path.join("backend", "uploaded_files", "youtube_cookies.txt")
    
    try:
        # Extract video ID from URL (supports all YouTube URL formats)
        print(f"\n🔍 Extracting video ID from URL...")
        video_id = extract_video_id(youtube_url)
        print(f"✅ Video ID: {video_id}")
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to extract video ID: {str(e)}"
        }
    
    # Try PRIMARY method: RapidAPI
    raw_audio_path = download_audio_rapidapi(video_id, audio_folder)
    
    # If primary failed, try FALLBACK method: yt-dlp
    if not raw_audio_path:
        print("\n⚠️  PRIMARY method failed, switching to FALLBACK...")
        raw_audio_path = download_audio_ytdlp(youtube_url, audio_folder, cookies_file_path)
    
    # If both methods failed
    if not raw_audio_path:
        error_msg = "Both download methods failed (RapidAPI and yt-dlp)."
        error_msg += "\n\n💡 Solutions:"
        error_msg += "\n   1. Upload fresh YouTube cookies (youtube_cookies.txt)"
        error_msg += "\n   2. Try a different video"
        error_msg += "\n   3. Check if video is age-restricted or private"
        
        return {"success": False, "error": error_msg}
    
    # Convert to 16kHz mono WAV for transcription
    print("\n" + "="*60)
    print("🔊 Converting to 16kHz mono WAV for transcription")
    print("="*60)
    
    ffmpeg_cmd = [
        "ffmpeg",
        "-i", raw_audio_path,
        "-ar", "16000",
        "-ac", "1",
        "-y",
        prepared_audio_path
    ]
    
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {
            "success": False,
            "error": f"FFmpeg conversion failed: {result.stderr}"
        }
    
    print("✅ Audio converted successfully!")
    
    # Calculate sizes
    raw_size_mb = round(os.path.getsize(raw_audio_path) / (1024 * 1024), 2)
    prepared_size_mb = round(os.path.getsize(prepared_audio_path) / (1024 * 1024), 2)
    
    print(f"\n📊 Final Results:")
    print(f"   📦 Raw audio: {raw_size_mb} MB")
    print(f"   🎵 Prepared audio: {prepared_size_mb} MB")
    print(f"   ✅ Status: SUCCESS\n")
    
    return {
        "success": True,
        "raw_audio": raw_audio_path,
        "prepared_audio": prepared_audio_path,
        "raw_size_mb": raw_size_mb,
        "prepared_size_mb": prepared_size_mb,
        "error": None,
    }
