"""
Fetch YouTube Video Metadata using YouTube Data API v3
Returns a dictionary with video_id, title, channel_name, date, time, and duration.
"""

import os
import re
import requests
import isodate
import psycopg2
from datetime import datetime, timezone, timedelta

# Timezone setup for IST (India Standard Time)
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    IST = timezone(timedelta(hours=5, minutes=30))


def get_youtube_api_key():
    """Fetch YouTube Data API key from database"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT key_value 
            FROM api_keys 
            WHERE LOWER(provider) = 'youtubedata'
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            return result[0]
        else:
            raise ValueError(
                "YouTube Data API key not found in database. Please add it in API Keys settings."
            )
    
    except Exception as e:
        raise Exception(f"Failed to fetch YouTube Data API key: {str(e)}")


def extract_video_id(youtube_url):
    """Extract video ID from YouTube URL or return it if already an ID."""
    # If already a video ID (11 characters)
    if re.match(r"^[a-zA-Z0-9_-]{11}$", youtube_url):
        return youtube_url
    
    # Match all YouTube URL formats:
    # - https://www.youtube.com/watch?v=VIDEO_ID
    # - https://www.youtube.com/live/VIDEO_ID
    # - https://youtu.be/VIDEO_ID
    # - https://www.youtube.com/embed/VIDEO_ID
    # - https://www.youtube.com/shorts/VIDEO_ID
    # - https://www.youtube.com/watch?v=VIDEO_ID&other_params
    # - https://www.youtube.com/live/VIDEO_ID?si=...
    match = re.search(r"(?:v=|youtu\.be/|embed/|shorts/|live/)([a-zA-Z0-9_-]{11})", youtube_url)
    if match:
        return match.group(1)
    
    raise ValueError("Invalid YouTube URL or Video ID")


def fetch_video_metadata(youtube_url):
    """
    Fetch video metadata from YouTube using YouTube Data API v3.

    Args:
        youtube_url: YouTube video URL or video ID

    Returns:
        dict: Video metadata including:
            - video_id: YouTube video ID
            - title: Video title
            - channel_name: Channel name
            - date: Upload date (YYYY-MM-DD)
            - time: Upload time (HH:MM:SS)
            - duration: Duration in MM:SS or HH:MM:SS format
            - thumbnail: Thumbnail URL
            - description: Video description
    """
    try:
        # Fetch API key from database
        api_key = get_youtube_api_key()
        
        # Extract video ID from URL
        video_id = extract_video_id(youtube_url)

        # Build YouTube Data API v3 request
        url = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=snippet,contentDetails&id={video_id}&key={api_key}"
        )

        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            raise Exception(f"YouTube API error: {res.text}")

        data = res.json()
        items = data.get("items", [])
        if not items:
            raise Exception(f"No video found for ID: {video_id}")

        snippet = items[0]["snippet"]
        content = items[0]["contentDetails"]

        # Parse upload datetime
        published_at = snippet.get("publishedAt")
        utc_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        ist_dt = utc_dt.astimezone(IST)
        date = ist_dt.strftime("%Y-%m-%d")
        time = ist_dt.strftime("%H:%M:%S")

        # Parse duration (ISO 8601 → HH:MM:SS or MM:SS)
        duration_td = isodate.parse_duration(content.get("duration", "PT0S"))
        total_seconds = int(duration_td.total_seconds())
        if total_seconds >= 3600:
            duration = f"{total_seconds//3600:02d}:{(total_seconds%3600)//60:02d}:{total_seconds%60:02d}"
        else:
            duration = f"{(total_seconds%3600)//60:02d}:{total_seconds%60:02d}"

        return {
            "video_id": video_id,
            "title": snippet.get("title", "Unknown Title"),
            "channel_name": snippet.get("channelTitle", "Unknown Channel"),
            "date": date,
            "time": time,
            "duration": duration,
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            "description": snippet.get("description", "")
        }

    except requests.Timeout:
        raise Exception("Request timed out while fetching video metadata")
    except Exception as e:
        raise Exception(f"Failed to fetch video metadata: {str(e)}")
