"""Shared YouTube URL helpers.

The original `normalize_youtube_url` lived inside `step02_download_captions`
which meant Step 1 (audio download) and the various job-creation endpoints
(Voice Typing, AI Transcribe, Media Presence) couldn't reuse it without
pulling in the captions module. As a result, /live/ URLs were passed
verbatim to yt-dlp and the RapidAPI youtube-mp310 endpoint — both of which
fail on the live-stream URL form because the upstream API only accepts the
canonical `watch?v=<id>` shape.

This module owns the canonical normalisation. Everyone (download_audio,
job-create endpoints, captions step) must call `normalize_youtube_url`
before persisting or shipping a URL downstream.
"""

import re

# Patterns are tried in order. Each must capture the 11-char video id (we
# accept 6+ to mirror the historical step02 behaviour, but YouTube ids are
# always exactly 11 chars in practice).
_VIDEO_ID_PATTERNS = (
    r"youtube\.com/live/([a-zA-Z0-9_-]{6,})",
    r"youtube\.com/shorts/([a-zA-Z0-9_-]{6,})",
    r"youtube\.com/embed/([a-zA-Z0-9_-]{6,})",
    r"youtube\.com/v/([a-zA-Z0-9_-]{6,})",
    r"youtu\.be/([a-zA-Z0-9_-]{6,})",
    r"[?&]v=([a-zA-Z0-9_-]{6,})",
)


def normalize_youtube_url(url):
    """Convert any YouTube URL (live / shorts / embed / youtu.be / watch)
    into the canonical ``https://www.youtube.com/watch?v=<id>`` form.

    Non-YouTube URLs and unrecognised shapes are returned unchanged so the
    caller's existing error path still fires with a meaningful message.
    """
    if not url:
        return url
    s = url.strip()
    for pattern in _VIDEO_ID_PATTERNS:
        match = re.search(pattern, s)
        if match:
            video_id = match.group(1)[:11]  # YouTube ids are exactly 11 chars
            return f"https://www.youtube.com/watch?v={video_id}"
    return s
