"""
Step 1: Download Audio from YouTube Video
PRIMARY: yt-dlp with cookies and rotating clients (free, no quota)
FALLBACK: RapidAPI youtube-mp310 (paid, used only when yt-dlp fails)
"""
import os
import subprocess
import requests
import random
from urllib.parse import quote
from yt_dlp import YoutubeDL
from backend.pipeline.fetch_video_data import extract_video_id
from backend.utils.database import get_db_cursor


def _get_rapidapi_key():
    """Fetch the RapidAPI key from the api_keys table (provider =
    'rapidapi_video_transcript', kept for backward compatibility with
    keys saved before the youtube-mp36 → youtube-mp310 swap).
    Returns the key string, or None if not configured."""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT key_value FROM api_keys WHERE provider = %s",
                ('rapidapi_video_transcript',)
            )
            result = cursor.fetchone()
            if result and result['key_value']:
                return result['key_value']
    except Exception as db_error:
        print(f"⚠️ Database error fetching RapidAPI key: {db_error}")
    return None


def download_audio_rapidapi(youtube_url, audio_folder):
    """
    FALLBACK METHOD: Download audio via RapidAPI's youtube-mp310 endpoint.

    Uses GET /download/mp3?url=<encoded YouTube URL> on
    youtube-mp310.p.rapidapi.com. The first call returns a JSON body with
    a session-bound `downloadUrl`; the actual MP3 is then streamed from
    that URL. The downloadUrl is single-use, so if anything goes wrong
    after fetching it we have to start over.

    Args:
        youtube_url: Full YouTube URL (the API takes the URL, not the ID).
        audio_folder: Output directory for audio files.

    Returns:
        str: Path to downloaded MP3 file, or None if failed.
    """
    print("\n" + "="*60)
    print("🆘 FALLBACK METHOD: RapidAPI youtube-mp310")
    print("="*60)

    rapidapi_key = _get_rapidapi_key()
    if not rapidapi_key:
        print("❌ RapidAPI key not configured in database "
              "(provider: rapidapi_video_transcript)")
        print("   Add it under Admin → API Keys → RapidAPI to enable this fallback.")
        return None

    api_host = "youtube-mp310.p.rapidapi.com"
    api_url = f"https://{api_host}/download/mp3"
    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": api_host,
    }

    try:
        print(f"📡 Requesting download URL from {api_host} ...")
        r = requests.get(
            api_url,
            params={"url": youtube_url},
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"❌ RapidAPI request failed: {e}")
        return None

    download_url = (
        payload.get("downloadUrl")
        or payload.get("download_url")
        or payload.get("url")
        or payload.get("link")
    )
    if not download_url:
        print(f"❌ RapidAPI response missing downloadUrl. Body: {payload}")
        return None

    title = str(payload.get("title", "audio"))
    for ch in ("/", "\\", ":"):
        title = title.replace(ch, "_")
    print(f"⏬ Streaming MP3: {title[:80]}")

    output_path = os.path.join(audio_folder, "raw_audio.mp3")
    download_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Connection": "keep-alive",
    }

    try:
        with requests.get(
            download_url,
            headers=download_headers,
            stream=True,
            allow_redirects=True,
            timeout=600,
        ) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        print(f"❌ MP3 stream download failed: {e}")
        # Clean up partial file
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return None

    file_size = os.path.getsize(output_path)
    if file_size < 1024:
        print(f"❌ Downloaded file is corrupted (only {file_size} bytes)")
        try:
            os.remove(output_path)
        except OSError:
            pass
        return None

    print(f"✅ RapidAPI download complete: {output_path} "
          f"({round(file_size / (1024 * 1024), 2)} MB)")
    return output_path


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
    Master function to download YouTube audio with dual-method fallback.

    PRIMARY: yt-dlp with cookies and rotating clients (free, no quota)
    FALLBACK: RapidAPI youtube-mp310 (paid, used only if yt-dlp fails —
              key required in api_keys.provider = 'rapidapi_video_transcript')

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
    print("🎧 YOUTUBE AUDIO DOWNLOADER — yt-dlp PRIMARY, RapidAPI FALLBACK")
    print("="*60)
    print(f"📹 Video URL: {youtube_url}")

    # Setup paths
    audio_folder = os.path.join("backend", "job_files", job_id, "audio")
    os.makedirs(audio_folder, exist_ok=True)

    prepared_audio_path = os.path.join(audio_folder, "audio_16k_mono.wav")
    cookies_file_path = os.path.join("backend", "uploaded_files", "youtube_cookies.txt")

    # Validate URL early (cheap; helps both methods give a good error)
    try:
        print(f"\n🔍 Extracting video ID from URL...")
        video_id = extract_video_id(youtube_url)
        print(f"✅ Video ID: {video_id}")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to extract video ID: {str(e)}"
        }

    # Try PRIMARY method: yt-dlp
    raw_audio_path = download_audio_ytdlp(youtube_url, audio_folder, cookies_file_path)

    # If yt-dlp failed, fall back to RapidAPI
    if not raw_audio_path:
        print("\n⚠️  yt-dlp failed, switching to RapidAPI fallback...")
        raw_audio_path = download_audio_rapidapi(youtube_url, audio_folder)

    # If both methods failed
    if not raw_audio_path:
        error_msg = "Both download methods failed (yt-dlp and RapidAPI youtube-mp310)."
        error_msg += "\n\n💡 Solutions:"
        error_msg += "\n   1. Upload fresh YouTube cookies (youtube_cookies.txt)"
        error_msg += "\n   2. Add / refresh the RapidAPI key under Admin → API Keys"
        error_msg += "\n   3. Try a different video"
        error_msg += "\n   4. Check if video is age-restricted or private"

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
