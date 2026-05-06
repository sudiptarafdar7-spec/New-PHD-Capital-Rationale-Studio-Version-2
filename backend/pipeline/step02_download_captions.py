"""
Step 2: Download Auto-Generated Captions from YouTube Video
100% Reliable - Uses RapidAPI Video Transcript Scraper API
"""
import requests
import json
import os
import re
from backend.utils.database import get_db_cursor


def normalize_youtube_url(url: str) -> str:
    """
    Converts any YouTube URL (live/shorts/embed/etc) into 
    the standard watch?v=VIDEOID format.
    
    Args:
        url: Any YouTube URL format
    
    Returns:
        str: Normalized URL in watch?v=VIDEOID format
    """
    # Patterns to extract video ID
    patterns = [
        r"youtube\.com/live/([a-zA-Z0-9_-]{6,})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{6,})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{6,})",
        r"youtu\.be/([a-zA-Z0-9_-]{6,})",
        r"[?&]v=([a-zA-Z0-9_-]{6,})"
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            return f"https://www.youtube.com/watch?v={video_id}"

    # If no match → return original
    return url


def download_captions(job_id, youtube_url, cookies_file=None):
    """
    100% Reliable Auto-Generated Caption Downloader using RapidAPI
    Downloads captions and converts to JSON3-compatible format
    
    Strategy:
    1. Use RapidAPI Video Transcript Scraper API
    2. Convert API response to JSON3 format (events array structure)
    3. Save as captions.json for downstream processing
    
    Args:
        job_id: Job identifier
        youtube_url: YouTube video URL
        cookies_file: Optional (not used with RapidAPI, kept for backward compatibility)
    
    Returns:
        dict: {
            'success': bool,
            'captions_path': str,  # Path to captions.json file
            'format': str,  # Always 'json3'
            'language': str,  # Detected language code
            'file_size_kb': float,
            'error': str or None
        }
    """
    try:
        # Setup paths
        captions_folder = os.path.join('backend', 'job_files', job_id, 'captions')
        os.makedirs(captions_folder, exist_ok=True)
        captions_json_path = os.path.join(captions_folder, 'captions.json')

        # Get RapidAPI key from database
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
            return {
                'success': False,
                'error': 'RapidAPI Video Transcript key not configured. Please add it in API Keys page (provider: rapidapi_video_transcript).'
            }

        # Normalize YouTube URL (live/shorts/embed → watch?v=)
        normalized_url = normalize_youtube_url(youtube_url)
        if normalized_url != youtube_url:
            print(f"🔄 Normalized URL: {youtube_url} → {normalized_url}")

        # RapidAPI request
        url = "https://video-transcript-scraper.p.rapidapi.com/transcript"

        payload = {"video_url": normalized_url}
        headers = {
            "x-rapidapi-key": rapidapi_key,
            "x-rapidapi-host": "video-transcript-scraper.p.rapidapi.com",
            "Content-Type": "application/json"
        }

        print("⏳ Fetching transcript using RapidAPI Video Transcript Scraper...")

        response = requests.post(url, json=payload, headers=headers, timeout=60)

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"RapidAPI request failed (Status {response.status_code}): {response.text}"
            }

        data = response.json()

        if data.get("status") != "success":
            return {
                "success": False,
                "error": f"RapidAPI returned error: {data.get('message', 'Unknown error')}"
            }

        transcript = data.get("data", {}).get("transcript")
        if not transcript:
            return {
                "success": False,
                "error": "No transcript available for this video. Captions may be disabled."
            }

        print(f"✓ API returned {len(transcript)} caption segments")

        # Convert to JSON3 structure (events array format)
        events = []
        for entry in transcript:
            text = entry.get("text", "").strip()
            start = float(entry.get("start", 0.0))
            duration = float(entry.get("duration", 0.0))  # RapidAPI provides duration, not end

            event = {
                "tStartMs": int(start * 1000),
                "dDurationMs": int(duration * 1000),  # Use duration directly
                "segs": [
                    {"utf8": text}
                ]
            }
            events.append(event)

        json3_output = {"events": events}

        # Save caption.json
        with open(captions_json_path, "w", encoding="utf-8") as f:
            json.dump(json3_output, f, ensure_ascii=False, indent=2)

        file_size = os.path.getsize(captions_json_path) / 1024

        # Extract language from API response
        video_info = data.get("data", {}).get("video_info", {})
        language = video_info.get("selected_language", "auto")

        print(f"✅ Captions saved successfully (Language: {language}, {len(events)} segments)")

        return {
            "success": True,
            "captions_path": captions_json_path,
            "format": "json3",
            "language": language,
            "file_size_kb": round(file_size, 2),
            "error": None
        }

    except requests.Timeout:
        return {
            "success": False,
            "error": "RapidAPI request timed out. Please try again."
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "error": f"RapidAPI request error: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Caption download error: {str(e)}"
        }
