"""
Live Transcribe — server-side live YouTube → AssemblyAI Realtime worker.

This module owns the long-running background job that:
  1. Spawns yt-dlp to pull a YouTube *live* stream's audio.
  2. Pipes it through ffmpeg, which simultaneously
       - writes the captured audio to a WAV on disk (for later
         speaker-diarized re-transcription), AND
       - emits raw 16 kHz / mono / 16-bit PCM frames on stdout for the
         AssemblyAI Realtime websocket.
  3. Streams those PCM frames into AssemblyAI Realtime; partial + final
     captions land in a callback that merges them into jobs.payload via
     a Postgres JSONB merge (race-safe with the user's PATCH writes).
  4. When the live stream ends (ffmpeg EOFs) OR the user presses Stop
     (status flipped away from 'live'), tears everything down cleanly,
     parks the job at status='awaiting_review' with an interim
     transcript, then triggers the diarized final pass.

Runs as a daemon thread — the user can close the tab and the
transcript continues to grow in the database. `recover_orphans()` at
server startup re-spawns workers for any jobs left in 'live' state
after a process restart.
"""

import os
import json
import time
import select
import subprocess
import threading
from datetime import datetime
from typing import Optional

from backend.utils.database import get_db_cursor


# ---------------------------------------------------------------------------
# DB helpers — same race-safe JSONB-merge pattern as voice_typing/transcribe_vosk
# ---------------------------------------------------------------------------

def _payload_dict(row) -> dict:
    if not row:
        return {}
    p = row.get('payload') if isinstance(row, dict) else row['payload']
    if not p:
        return {}
    if isinstance(p, dict):
        return p
    try:
        return json.loads(p)
    except Exception:
        return {}


def _read_job(job_id: str):
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT id, status, payload, youtube_url FROM jobs WHERE id = %s",
            (job_id,),
        )
        return cursor.fetchone()


def _patch_payload(job_id: str, **payload_updates) -> bool:
    """Atomically merge payload_updates into jobs.payload."""
    if not payload_updates:
        return True
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE jobs "
            "SET payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
            "    updated_at = %s "
            "WHERE id = %s",
            (json.dumps(payload_updates), datetime.now(), job_id),
        )
        return cursor.rowcount > 0


def _patch_progress(job_id: str, *, live_text: str, progress: int,
                    status: Optional[str] = None) -> bool:
    payload_patch = {
        'live_transcript': live_text,
        'transcribe_progress': progress,
    }
    sql = (
        "UPDATE jobs "
        "SET payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
        "    progress = %s, updated_at = %s"
    )
    params: list = [json.dumps(payload_patch), progress, datetime.now()]
    if status:
        sql += ", status = %s"
        params.append(status)
    sql += " WHERE id = %s"
    params.append(job_id)
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount > 0


def _mark_failed(job_id: str, error: str):
    payload_patch = {'transcribe_error': (error or '')[:1000]}
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE jobs "
            "SET status = 'failed', "
            "    payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
            "    updated_at = %s "
            "WHERE id = %s",
            (json.dumps(payload_patch), datetime.now(), job_id),
        )


def _is_cancelled(job_id: str) -> bool:
    """User stopped the worker by PATCHing status away from 'live'."""
    row = _read_job(job_id)
    if not row:
        return True
    return row['status'] != 'live'


# ---------------------------------------------------------------------------
# AssemblyAI key (stored in api_keys table, like the AI Transcribe path)
# ---------------------------------------------------------------------------

def _get_assemblyai_key() -> str:
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT key_value FROM api_keys WHERE LOWER(provider) = 'assemblyai'"
        )
        row = cursor.fetchone()
    if not row or not row.get('key_value'):
        # Fall back to env (the project's standard env var).
        env_key = os.environ.get('ASSEMBLYAI_API_KEY', '').strip()
        if env_key:
            return env_key
        raise RuntimeError(
            "AssemblyAI API key not configured. Add it under Administration → API Keys."
        )
    return row['key_value'].strip()


# ---------------------------------------------------------------------------
# Subprocess pipeline: yt-dlp → ffmpeg(WAV file + raw PCM stdout)
# ---------------------------------------------------------------------------

def _resolve_youtube_cookies_file() -> str | None:
    """Return the path to the uploaded YouTube cookies.txt if present,
    else None. Mirrors the lookup used by the Media Rationale pipeline so
    a single uploaded cookies file works across every YouTube-touching
    tool. YouTube increasingly returns a 'Sign in to confirm you're not
    a bot' challenge for unauthenticated requests, especially on live
    streams — without cookies, capture fails immediately."""
    candidates = [
        os.path.join('backend', 'youtube_cookies.txt'),
        os.path.join('backend', 'uploaded_files', 'youtube_cookies.txt'),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    return None


def _resolve_hls_url(live_url: str, log_fh) -> tuple[str, dict[str, str]]:
    """Ask yt-dlp for the direct HLS manifest URL **and** the HTTP
    headers it expects to be sent with each request. We hand both to
    ffmpeg so the segment GETs are authenticated (User-Agent, Cookie,
    etc.) — without those headers YouTube's edge returns a small HTML
    error page instead of TS data and ffmpeg fails with "Invalid data
    found when processing input"."""
    import json as _json
    cmd = [
        'yt-dlp',
        '-f', 'bestaudio/best',
        '--no-warnings',
        '-j',  # one-line JSON dict per format
    ]
    cookies_path = _resolve_youtube_cookies_file()
    if cookies_path:
        cmd += ['--cookies', cookies_path]
        print(f"🍪 [live-transcribe] using YouTube cookies from {cookies_path}")
    else:
        print("⚠️  [live-transcribe] no youtube_cookies.txt found — "
              "YouTube may reject the stream with a bot-check.")
    cmd.append(live_url)

    # See big comment below about scrubbing PYTHONPATH/PYTHONHOME.
    yt_env = {k: v for k, v in os.environ.items()
              if k not in ('PYTHONPATH', 'PYTHONHOME')}
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=yt_env, timeout=45,
    )
    if proc.returncode != 0:
        try:
            log_fh.write(f"yt-dlp -j failed (rc={proc.returncode}):\n".encode())
            log_fh.write((proc.stderr or '').encode(errors='replace'))
        except Exception:
            pass
        raise RuntimeError(
            (proc.stderr or 'yt-dlp could not resolve the live stream URL.').strip().splitlines()[-1]
        )

    info = _json.loads((proc.stdout or '').strip().splitlines()[0])
    url = info.get('url')
    headers = info.get('http_headers') or {}

    # If -f returned a multi-stream pick (video+audio merged), drill into
    # `requested_formats` and grab the audio one.
    if not url and isinstance(info.get('requested_formats'), list):
        for fmt in info['requested_formats']:
            if (fmt.get('vcodec') == 'none' or
                fmt.get('acodec') and fmt.get('acodec') != 'none'):
                url = fmt.get('url')
                headers = fmt.get('http_headers') or headers
                if fmt.get('vcodec') == 'none':
                    break
    if not url:
        raise RuntimeError('yt-dlp returned no media URL for this live stream.')
    return url, headers


class _HLSSegmentFetcher:
    """Pumps live HLS segments straight into ffmpeg's stdin.

    Background: YouTube's live HLS playlists list `*/file/seg.ts` segments
    that are actually raw ADTS-AAC (with ID3 timestamp tags), not the
    MPEG-TS containers ffmpeg's `-i <m3u8_url>` demuxer expects. Letting
    ffmpeg open the manifest itself fails with "Invalid data found when
    processing input" on the first segment. We sidestep that demuxer
    entirely by fetching segments in Python and concat-piping the raw AAC
    bytes to ffmpeg via `-f aac -i pipe:0`. Bonus: starting at the live
    edge ("only newest unseen segment, never backfill") is trivial here,
    which is exactly what the user asked for.

    Exposes a Popen-like surface (`poll`, `terminate`, `kill`, `wait`,
    `returncode`) so the existing worker loop can treat us interchangeably
    with the previous `yt_proc` slot.
    """

    def __init__(self, hls_url: str, headers: dict, ff_stdin, log_fh):
        self.hls_url = hls_url
        self.headers = headers
        self.ff_stdin = ff_stdin
        self.log_fh = log_fh
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='live-hls-fetcher')
        self.returncode: Optional[int] = None

    def start(self):
        self._thread.start()

    # --- Popen-compatible API ---
    def poll(self) -> Optional[int]:
        if self._thread.is_alive():
            return None
        return self.returncode if self.returncode is not None else 0

    def terminate(self):
        self._stop.set()

    def kill(self):
        self._stop.set()

    def wait(self, timeout: Optional[float] = None):
        self._thread.join(timeout)

    # --- internals ---
    def _log(self, msg: str):
        try:
            self.log_fh.write((msg + '\n').encode(errors='replace'))
            self.log_fh.flush()
        except Exception:
            pass

    def _http_get(self, url: str, timeout: float = 20.0) -> bytes:
        import urllib.request
        # Strip private bookkeeping keys (we stash __live_url__ in
        # self.headers so we can re-resolve on URL expiry).
        send_headers = {k: v for k, v in self.headers.items()
                        if not k.startswith('__')}
        req = urllib.request.Request(url, headers=send_headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def _parse_manifest(self, manifest: str) -> tuple[list[tuple[int, str]], float, bool]:
        """Return ([(seq, url), ...], target_duration_secs, endlist_seen)."""
        media_seq = 0
        target_dur = 5.0
        endlist = False
        segments: list[tuple[int, str]] = []
        next_seq = None
        for raw in manifest.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                try:
                    media_seq = int(line.split(':', 1)[1])
                    next_seq = media_seq
                except ValueError:
                    pass
            elif line.startswith('#EXT-X-TARGETDURATION:'):
                try:
                    target_dur = float(line.split(':', 1)[1])
                except ValueError:
                    pass
            elif line.startswith('#EXT-X-ENDLIST'):
                endlist = True
            elif not line.startswith('#'):
                seq = next_seq if next_seq is not None else media_seq
                segments.append((seq, line))
                if next_seq is not None:
                    next_seq += 1
        return segments, target_dur, endlist

    def _run(self):
        # First-iteration jump-to-live-edge: we set last_seq so we skip
        # ALL existing segments in the playlist and only download the
        # segment that appears AFTER our first manifest poll.  This is
        # the strongest possible "current stream only, no past content"
        # guarantee — the user's hard requirement.
        last_seq = -1
        first_pass = True
        endlist_seen = False
        consecutive_errors = 0
        url_refreshed_at = time.time()

        while not self._stop.is_set():
            try:
                manifest_bytes = self._http_get(self.hls_url, timeout=15.0)
                manifest = manifest_bytes.decode('utf-8', errors='replace')
            except Exception as e:
                consecutive_errors += 1
                self._log(f"manifest fetch failed ({consecutive_errors}): {e}")
                # YouTube signed URLs expire after ~6h. If we get repeated
                # failures, try to re-resolve the HLS URL once.
                if consecutive_errors == 5:
                    try:
                        new_url, new_headers = _resolve_hls_url(
                            self.headers.get('__live_url__', ''), self.log_fh)
                        if new_url:
                            self.hls_url = new_url
                            new_headers.setdefault(
                                '__live_url__',
                                self.headers.get('__live_url__', ''))
                            self.headers = new_headers
                            url_refreshed_at = time.time()
                            self._log("HLS URL refreshed")
                            consecutive_errors = 0
                    except Exception as refresh_err:
                        self._log(f"HLS URL refresh failed: {refresh_err}")
                if consecutive_errors > 12:
                    self._log("too many manifest errors, giving up")
                    self.returncode = 2
                    break
                if self._stop.wait(2.0):
                    break
                continue

            consecutive_errors = 0
            segments, target_dur, endlist = self._parse_manifest(manifest)
            if endlist:
                endlist_seen = True

            if not segments:
                if endlist_seen:
                    break
                if self._stop.wait(2.0):
                    break
                continue

            if first_pass:
                # Skip everything currently in the manifest — only
                # download segments produced AFTER we attached.
                last_seq = segments[-1][0]
                first_pass = False
                self._log(f"live-edge attached at seq={last_seq} "
                          f"(target_dur={target_dur}s)")
            else:
                new_segs = [(s, u) for s, u in segments if s > last_seq]
                for seq, seg_url in new_segs:
                    if self._stop.is_set():
                        break
                    try:
                        data = self._http_get(seg_url, timeout=20.0)
                    except Exception as seg_err:
                        self._log(f"segment {seq} fetch failed: {seg_err}")
                        continue
                    try:
                        self.ff_stdin.write(data)
                        self.ff_stdin.flush()
                        last_seq = seq
                    except (BrokenPipeError, ValueError, OSError) as pipe_err:
                        # ffmpeg died or stdin closed — caller will notice
                        # via ff_proc.poll() and tear us down.
                        self._log(f"ffmpeg stdin closed: {pipe_err}")
                        self.returncode = 0
                        # Best-effort close so the worker loop sees EOF.
                        try:
                            self.ff_stdin.close()
                        except Exception:
                            pass
                        return

            if endlist_seen:
                self._log("playlist ENDLIST seen — stream ended")
                break
            # Re-poll roughly twice per segment duration (HLS spec
            # recommendation). Floor at 1 s, cap at 5 s.
            sleep_for = max(1.0, min(5.0, target_dur / 2))
            if self._stop.wait(sleep_for):
                break

        # Close ffmpeg's stdin so its WAV muxer flushes the trailer and
        # exits cleanly — that's how the worker loop sees EOF.
        try:
            self.ff_stdin.close()
        except Exception:
            pass
        if self.returncode is None:
            self.returncode = 0


def _start_capture_pipeline(live_url: str, wav_path: str,
                            log_path: str) -> tuple[Optional[object], subprocess.Popen]:
    """Spawn ffmpeg reading raw AAC from stdin, plus a Python segment
    fetcher that pumps live HLS segments into that stdin. Returns
    (fetcher, ffmpeg_proc). Both expose `.poll()/.terminate()` so the
    main worker loop is unchanged.

    Why this shape? See _HLSSegmentFetcher docstring — YouTube's live HLS
    segments are raw ADTS-AAC and ffmpeg's HLS demuxer rejects them with
    "Invalid data found when processing input". Fetching segments in
    Python and piping to `ffmpeg -f aac -i pipe:0` works perfectly and
    gives us trivial "live edge only" control."""
    os.makedirs(os.path.dirname(wav_path), exist_ok=True)

    # ffmpeg stderr goes to log_path so we can debug live capture
    # failures without losing them on container restart.
    log_fh = open(log_path, 'ab', buffering=0)

    hls_url, hls_headers = _resolve_hls_url(live_url, log_fh)
    print(f"🎯 [live-transcribe] resolved HLS URL ({len(hls_url)} chars, "
          f"{len(hls_headers)} headers)")

    # Make sure we always send a User-Agent (some YouTube edges 403
    # bare-headers requests).
    hls_headers.setdefault(
        'User-Agent',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36',
    )
    # Stash the original watch URL inside headers so the fetcher can
    # call _resolve_hls_url() again if YouTube's signed URL expires.
    hls_headers['__live_url__'] = live_url

    ff_cmd = [
        'ffmpeg',
        '-loglevel', 'warning',
        # NOTE: do NOT pass -nostdin here — we feed ffmpeg via stdin.
        # -y: overwrite an existing full.wav left from a prior crashed
        # worker (orphan recovery) instead of aborting with "file exists".
        '-y',
        # Input format is raw AAC ADTS frames (with optional ID3 tags),
        # which is what YouTube live HLS segments actually contain.
        '-f', 'aac',
        '-i', 'pipe:0',
        # Output 1: the on-disk WAV (full quality 16 kHz mono — used by
        # the diarized re-transcription pass after the stream ends).
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-f', 'wav', wav_path,
        # Output 2: raw PCM frames for the AssemblyAI Realtime websocket.
        '-ar', '16000', '-ac', '1', '-f', 's16le', 'pipe:1',
    ]
    ff = subprocess.Popen(
        ff_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_fh,
        bufsize=0,
    )

    fetcher = _HLSSegmentFetcher(hls_url, hls_headers, ff.stdin, log_fh)
    fetcher.start()
    return fetcher, ff


def _verify_url_is_live(live_url: str) -> None:
    """Best-effort: confirm the URL is currently live (not a past
    broadcast). Raises RuntimeError with a user-friendly message if the
    stream has clearly ended or never was live. Silent (no exception)
    when yt-dlp can't decide, so we don't block valid edge cases."""
    yt_env = {k: v for k, v in os.environ.items()
              if k not in ('PYTHONPATH', 'PYTHONHOME')}
    cookies_path = _resolve_youtube_cookies_file()
    cmd = ['yt-dlp', '--no-warnings', '--print', '%(is_live)s|%(live_status)s']
    if cookies_path:
        cmd += ['--cookies', cookies_path]
    cmd.append(live_url)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=yt_env, timeout=30)
    except Exception:
        return
    out = (proc.stdout or '').strip().splitlines()[-1] if proc.stdout else ''
    if not out:
        return
    is_live, _, live_status = out.partition('|')
    if is_live.lower() == 'false' and live_status in ('was_live', 'post_live', 'not_live'):
        raise RuntimeError(
            "This YouTube broadcast is not live right now "
            f"(live_status={live_status}). Use AI Transcribe or Auto for "
            "ended/recorded broadcasts."
        )


def _terminate(*procs: subprocess.Popen):
    for p in procs:
        if p is None:
            continue
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    # Give them a moment, then SIGKILL stragglers.
    deadline = time.time() + 4
    for p in procs:
        if p is None:
            continue
        try:
            timeout = max(0.1, deadline - time.time())
            p.wait(timeout=timeout)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------

CHUNK_BYTES = 3200  # 100 ms at 16 kHz / mono / 16-bit


def transcribe_live_job(job_id: str, live_url: str):
    """Background-thread entry point. Owns the entire live capture +
    realtime transcription lifecycle for one Live Transcribe job."""
    print(f"\n📡 [live-transcribe] Worker started for job {job_id}")
    print(f"    url: {live_url}")

    folder = os.path.join('backend', 'job_files', job_id)
    audio_dir = os.path.join(folder, 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    wav_path = os.path.join(audio_dir, 'full.wav')
    log_path = os.path.join(folder, 'capture.log')

    # Orphan-recovery safety: if a previous worker for this job already wrote
    # a partial full.wav (process killed mid-stream), rotate it aside so the
    # diarized finalize pass at stream end can still concat multiple segments
    # if desired, and so ffmpeg's `-y` overwrite never silently destroys the
    # only audio captured before the crash.
    try:
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            ts = int(time.time())
            os.rename(wav_path, os.path.join(audio_dir, f'full.part-{ts}.wav'))
    except Exception as rotate_err:
        print(f"⚠️  [live-transcribe] Could not rotate prior full.wav: {rotate_err}")

    # ---- AssemblyAI Universal-Streaming (v3) setup ----------------------
    # The legacy v2 RealtimeTranscriber endpoint was sunset and now returns
    # HTTP 404. We use the v3 StreamingClient which speaks AssemblyAI's
    # Universal-Streaming protocol over WSS to streaming.assemblyai.com.
    #
    # CRITICAL: AssemblyAI v3 REQUIRES the `speech_model` query parameter on
    # every connection — there is no default. The bundled SDK's
    # StreamingParameters dataclass does NOT expose `speech_model`, so its
    # `connect()` builds a URL without it and the server rejects the
    # handshake (which is why we were seeing "AssemblyAI error: See Error
    # message for details"). We subclass StreamingClient and override
    # connect() to append `speech_model=u3-rt-pro` (Universal-3 Pro
    # Streaming, the recommended model for live audio) to the URL.
    try:
        from assemblyai.streaming.v3 import (
            StreamingClient, StreamingClientOptions, StreamingParameters,
            StreamingEvents, BeginEvent, TurnEvent, TerminationEvent,
        )
    except Exception as e:
        _mark_failed(job_id, f"AssemblyAI streaming SDK import failed: {e}")
        return

    try:
        key = _get_assemblyai_key()
    except Exception as e:
        _mark_failed(job_id, str(e))
        return

    class _SpeechModelStreamingClient(StreamingClient):
        """Adds the required `speech_model` query parameter to the v3 WS URL."""

        def connect(self, params):
            from urllib.parse import urlencode
            from websockets.sync.client import connect as websocket_connect
            # Pull the SDK's private helpers via the original method's
            # closure globals — they're module-private so a plain import
            # fails, but they are guaranteed to exist for the SDK version
            # that exposes StreamingClient.connect.
            sdk_globals = StreamingClient.connect.__globals__
            dump_model = sdk_globals.get('_dump_model') or (
                lambda p: p.model_dump(exclude_none=True)
            )
            user_agent = sdk_globals.get('_user_agent') or (lambda: 'phd-capital/1.0')
            params_dict = dump_model(params)
            params_dict['speech_model'] = 'u3-rt-pro'
            uri = f"wss://{self._options.api_host}/v3/ws?{urlencode(params_dict)}"
            headers = {
                "Authorization": self._options.token or self._options.api_key,
                "User-Agent": user_agent(),
                "AssemblyAI-Version": "2025-05-12",
            }
            self._websocket = websocket_connect(uri, additional_headers=headers, open_timeout=15)
            self._write_thread.start()
            self._read_thread.start()

    finals: list[str] = []   # accumulated end-of-turn transcripts
    partial_text = {'value': ''}   # most recent in-progress turn
    last_flush = {'t': 0.0}
    flush_lock = threading.Lock()

    def flush_if_due(force: bool = False):
        now = time.time()
        if not force and (now - last_flush['t'] < 1.5):
            return
        last_flush['t'] = now
        with flush_lock:
            live_text = ' '.join(s for s in finals if s).strip()
            if partial_text['value']:
                live_text = (live_text + ' ' + partial_text['value']).strip()
        try:
            _patch_progress(job_id, live_text=live_text, progress=min(95, 5 + len(finals)))
        except Exception as e:
            print(f"⚠️  [live-transcribe] {job_id} flush failed: {e}")

    def on_begin(_client, event: 'BeginEvent'):
        print(f"📡 [live-transcribe] {job_id} AssemblyAI session opened (id={event.id})")
        _patch_payload(job_id, realtime_session_id=str(event.id))

    def on_turn(_client, event: 'TurnEvent'):
        text = (event.transcript or '').strip()
        if not text:
            return
        if event.end_of_turn:
            with flush_lock:
                finals.append(text)
                partial_text['value'] = ''
        else:
            with flush_lock:
                partial_text['value'] = text
        flush_if_due()

    def on_termination(_client, event: 'TerminationEvent'):
        print(f"📡 [live-transcribe] {job_id} AssemblyAI session closed "
              f"(audio={event.audio_duration_seconds}s)")

    def on_error(_client, error):
        msg = str(error)
        print(f"⚠️  [live-transcribe] {job_id} AssemblyAI error: {msg}")
        try:
            _patch_payload(job_id, last_realtime_error=msg[:500])
        except Exception:
            pass

    transcriber = _SpeechModelStreamingClient(
        StreamingClientOptions(api_key=key)
    )
    transcriber.on(StreamingEvents.Begin, on_begin)
    transcriber.on(StreamingEvents.Turn, on_turn)
    transcriber.on(StreamingEvents.Termination, on_termination)
    transcriber.on(StreamingEvents.Error, on_error)

    try:
        transcriber.connect(StreamingParameters(sample_rate=16000))
    except Exception as e:
        _mark_failed(job_id, f"AssemblyAI Streaming connect failed: {e}")
        return

    # ---- Start the audio capture pipeline -------------------------------
    if _is_cancelled(job_id):
        try:
            transcriber.disconnect(terminate=True)
        except Exception:
            pass
        return

    try:
        yt_proc, ff_proc = _start_capture_pipeline(live_url, wav_path, log_path)
    except FileNotFoundError as e:
        _mark_failed(job_id, f"yt-dlp / ffmpeg not installed on server: {e}")
        try:
            transcriber.disconnect(terminate=True)
        except Exception:
            pass
        return
    except Exception as e:
        _mark_failed(job_id, f"Capture pipeline failed to start: {e}")
        try:
            transcriber.disconnect(terminate=True)
        except Exception:
            pass
        return

    _patch_progress(job_id, live_text='[Connecting to live stream…]', progress=2)

    # ---- Main streaming loop --------------------------------------------
    # We poll the ffmpeg stdout via select() with a 1 s timeout instead of
    # blocking on read() so the worker can:
    #   1. notice when both child processes have exited (stream ended
    #      naturally — broadcaster stopped, HLS playlist EOF, etc.) and
    #      auto-tear down without waiting on a manual Stop click.
    #   2. notice user cancellation promptly.
    #   3. flush partial transcripts on a heartbeat even if no audio is
    #      arriving for a while.
    # When both yt-dlp and ffmpeg have exited we still drain any final
    # buffered bytes from ffmpeg's stdout before breaking, so we don't
    # lose the tail of the captured audio.
    last_cancel_check = 0.0
    children_dead_since: Optional[float] = None
    try:
        while True:
            stdout_fd = ff_proc.stdout
            data = b''
            if stdout_fd is not None:
                try:
                    rlist, _, _ = select.select([stdout_fd], [], [], 1.0)
                except (ValueError, OSError):
                    # stdout was closed underneath us — treat as EOF.
                    rlist = []
                if rlist:
                    # Use read1() so we never block waiting for a full
                    # CHUNK_BYTES — return whatever is currently available
                    # in the pipe buffer (or b'' on EOF).
                    try:
                        data = stdout_fd.read1(CHUNK_BYTES)
                    except AttributeError:
                        data = stdout_fd.read(CHUNK_BYTES)
                    if not data:
                        # ffmpeg closed stdout — EOF on the live stream.
                        print(f"📡 [live-transcribe] {job_id} stream EOF — finalising")
                        break

            if data:
                try:
                    transcriber.stream(data)
                except Exception as stream_err:
                    print(f"⚠️  [live-transcribe] {job_id} stream() failed: {stream_err}")
                    # Don't kill the worker — try to keep going. If the
                    # websocket is truly dead, on_error will surface it and
                    # the user can stop manually.

            # Auto-stop: if both child processes have exited, the upstream
            # is gone. Give it a brief grace window (2 s) so any in-flight
            # bytes still in the pipe can be drained by the read above
            # before we break out and finalize.
            yt_done = yt_proc is None or yt_proc.poll() is not None
            ff_done = ff_proc.poll() is not None
            if yt_done and ff_done:
                if children_dead_since is None:
                    children_dead_since = time.time()
                elif time.time() - children_dead_since > 2.0:
                    print(
                        f"📡 [live-transcribe] {job_id} children exited "
                        f"(yt={getattr(yt_proc, 'returncode', 'n/a')}, ff={ff_proc.returncode}) — finalising"
                    )
                    break
            else:
                children_dead_since = None

            # Cancellation + heartbeat flush every ~2 s.
            now = time.time()
            if now - last_cancel_check > 2.0:
                last_cancel_check = now
                if _is_cancelled(job_id):
                    print(f"🛑 [live-transcribe] {job_id} cancelled by user")
                    break
                flush_if_due()
    finally:
        # Tear down audio capture first so the WAV is finalised on disk.
        _terminate(ff_proc, yt_proc)
        try:
            transcriber.disconnect(terminate=True)
        except Exception:
            pass

    # ---- Finalise: write whatever realtime gave us, then trigger diarized
    flush_if_due(force=True)

    # Park the job at awaiting_review with the interim live transcript so
    # the user sees something immediately. The diarized pass runs next and
    # will overwrite jobs.payload.diarized_transcript when ready.
    with flush_lock:
        live_text = ' '.join(s for s in finals if s).strip()
    if not live_text:
        live_text = '[No speech captured during the live stream.]'

    # Conditional teardown — only flip to awaiting_review if status is
    # STILL 'live'. If the user already advanced to extracting / bulk,
    # clobbering back to awaiting_review would let extract run twice.
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE jobs
                SET payload = (COALESCE(payload, '{}'::jsonb)
                               || jsonb_build_object('live_transcript', %s,
                                                     'transcribe_progress', %s)),
                    status = CASE WHEN status = 'live' THEN 'awaiting_review' ELSE status END,
                    progress = GREATEST(COALESCE(progress, 0), %s),
                    updated_at = %s
                WHERE id = %s
                """,
                (live_text, 98, 98, datetime.now(), job_id),
            )
    except Exception as teardown_err:
        print(f"⚠️  [live-transcribe] {job_id} teardown patch failed: {teardown_err}")

    # Kick off the diarized re-transcription as a separate background step.
    # This is best-effort — failure here doesn't fail the whole job; the
    # user still has the realtime transcript to review.
    try:
        from backend.pipeline.live_transcribe.finalize_diarized import run_finalize
        run_finalize(job_id, wav_path)
    except Exception as e:
        print(f"⚠️  [live-transcribe] {job_id} diarized finalize failed: {e}")
        _patch_payload(job_id, diarize_error=str(e)[:500])

    print(f"✅ [live-transcribe] Worker finished {job_id}")


def spawn(job_id: str, live_url: str):
    """Fire-and-forget thread launcher. Use from request handlers."""
    t = threading.Thread(
        target=transcribe_live_job,
        args=(job_id, live_url),
        name=f"live-transcribe-{job_id}",
        daemon=True,
    )
    t.start()
    return t


# ---------------------------------------------------------------------------
# Orphan recovery
# ---------------------------------------------------------------------------

def recover_orphans() -> int:
    """Re-spawn workers for any Live Transcribe jobs left in 'live' OR
    'extracting' status after a server restart. Daemon threads don't
    survive a process restart, but the partial transcript already in
    jobs.payload is preserved.

    - 'live' rows  -> respawn the realtime capture worker (`spawn`)
    - 'extracting' rows -> re-kick the OpenAI extraction (`_recover_extract`)
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id, payload, youtube_url, status
                FROM jobs
                WHERE tool_used = 'Live Transcribe'
                  AND status IN ('live', 'extracting')
                """
            )
            rows = cursor.fetchall() or []
    except Exception as e:
        print(f"[live-transcribe] orphan scan failed: {e}")
        return 0

    recovered = 0
    for row in rows:
        try:
            payload = _payload_dict(row)
            if row['status'] == 'extracting':
                print(f"♻️  [live-transcribe] Recovering extract orphan {row['id']}")
                _recover_extract(row['id'], payload)
                recovered += 1
                continue

            live_url = payload.get('live_url') or row.get('youtube_url')
            if not live_url:
                print(f"⚠️  [live-transcribe] orphan {row['id']} has no live_url — marking failed")
                _mark_failed(row['id'], 'No live_url to resume from after server restart.')
                continue
            print(f"♻️  [live-transcribe] Recovering live orphan {row['id']}")
            _patch_progress(row['id'], live_text='[Resumed after server restart…]', progress=1)
            spawn(row['id'], live_url)
            recovered += 1
        except Exception as e:
            print(f"⚠️  [live-transcribe] failed to recover {row.get('id')}: {e}")
    return recovered


def _recover_extract(job_id: str, payload: dict) -> None:
    """Re-kick OpenAI extraction for a job left in 'extracting' after restart.
    Runs in a daemon thread so server startup isn't blocked."""
    import threading
    transcript = (
        payload.get('diarized_transcript')
        or payload.get('live_transcript')
        or ''
    )
    if not transcript.strip():
        _mark_failed(job_id, 'Cannot resume extract: transcript is empty.')
        return
    # Local import to avoid a startup cycle (live_transcribe API imports us).
    from backend.api.live_transcribe import _extract_only
    threading.Thread(
        target=_extract_only, args=(job_id, transcript), daemon=True
    ).start()
