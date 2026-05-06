"""
Live Transcribe — diarized finalize pass.

After the realtime capture ends, the captured WAV on disk is uploaded to
AssemblyAI's async transcription endpoint with `speaker_labels=true`. We
then format the result as a speaker-attributed, timestamped transcript:

    [00:00:12] Speaker A: …
    [00:00:18] Speaker B: …

…and merge it into jobs.payload.diarized_transcript so the review UI can
show a higher-quality, properly-attributed version of what realtime
already streamed live.

This is best-effort: realtime transcript stays available if diarized
fails (network blip, AssemblyAI quota, etc).
"""

import os
import json
from datetime import datetime

from backend.utils.database import get_db_cursor


def _patch_payload(job_id: str, **payload_updates):
    if not payload_updates:
        return
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE jobs "
            "SET payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb, "
            "    updated_at = %s "
            "WHERE id = %s",
            (json.dumps(payload_updates), datetime.now(), job_id),
        )


def _get_assemblyai_key() -> str:
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT key_value FROM api_keys WHERE LOWER(provider) = 'assemblyai'"
        )
        row = cursor.fetchone()
    if row and row.get('key_value'):
        return row['key_value'].strip()
    env_key = os.environ.get('ASSEMBLYAI_API_KEY', '').strip()
    if env_key:
        return env_key
    raise RuntimeError("AssemblyAI API key not configured.")


def _map_speaker_roles(utterances) -> dict:
    """Heuristic Anchor / Pradip / Speaker N mapping for AssemblyAI's
    raw 'A', 'B', 'C'… speaker labels.

    Pradip's shows follow a consistent pattern: Pradip Halder is by far
    the dominant speaker (longest utterances, most total words — he is
    delivering stock analyses), and there is typically one Anchor / host
    who interviews him with shorter prompts. Any remaining diarized
    speakers are co-guests / callers and are surfaced as `Speaker 1`,
    `Speaker 2`, … in the order they first appear.
    """
    word_totals: dict = {}
    first_seen: dict = {}
    for idx, u in enumerate(utterances):
        spk = getattr(u, 'speaker', None)
        if spk is None:
            continue
        text = (getattr(u, 'text', '') or '').strip()
        if not text:
            continue
        word_totals[spk] = word_totals.get(spk, 0) + len(text.split())
        first_seen.setdefault(spk, idx)

    if not word_totals:
        return {}

    # Sort by total words desc — top speaker = Pradip. If there's only one
    # speaker total, label them Pradip (his solo broadcast).
    by_volume = sorted(word_totals.items(), key=lambda kv: kv[1], reverse=True)
    mapping: dict = {}
    if len(by_volume) == 1:
        mapping[by_volume[0][0]] = 'Pradip'
        return mapping

    # Top speaker = Pradip; second = Anchor; rest = Speaker N in
    # first-appearance order so labels are stable across re-runs.
    mapping[by_volume[0][0]] = 'Pradip'
    mapping[by_volume[1][0]] = 'Anchor'
    rest = [
        spk for spk, _ in by_volume[2:]
    ]
    rest.sort(key=lambda s: first_seen.get(s, 0))
    for i, spk in enumerate(rest, start=1):
        mapping[spk] = f"Speaker {i}"
    return mapping


def _format_timestamp(ms: int) -> str:
    s = max(0, int(ms) // 1000)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _merge_recovery_segments(wav_path: str) -> str:
    """If orphan-recovery rotated prior captures aside as
    `audio/full.part-<ts>.wav`, concatenate them in chronological order
    with the current `full.wav` into a single merged WAV so the diarized
    pass sees the COMPLETE stream (pre-restart + post-restart). Returns
    the path to use for transcription."""
    import glob, subprocess
    audio_dir = os.path.dirname(wav_path)
    parts = sorted(glob.glob(os.path.join(audio_dir, 'full.part-*.wav')))
    if not parts:
        return wav_path
    if not os.path.exists(wav_path) or os.path.getsize(wav_path) < 1024:
        # No new audio after restart — just use the most recent part.
        return parts[-1]
    merged_path = os.path.join(audio_dir, 'full.merged.wav')
    list_path = os.path.join(audio_dir, 'concat.txt')
    try:
        with open(list_path, 'w') as fh:
            for p in parts + [wav_path]:
                fh.write(f"file '{os.path.abspath(p)}'\n")
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
             '-i', list_path, '-c', 'copy', merged_path],
            check=True, capture_output=True, timeout=300,
        )
        return merged_path
    except Exception as merge_err:
        print(f"⚠️  [diarize] segment merge failed, falling back to current full.wav: {merge_err}")
        return wav_path


def run_finalize(job_id: str, wav_path: str) -> bool:
    """Upload the captured WAV to AssemblyAI with speaker_labels=True,
    poll for completion, and write the diarized transcript into the job's
    payload. Returns True on success."""
    # Merge any rotated pre-restart segments with the current capture so a
    # process restart mid-stream doesn't drop the early portion of the show.
    wav_path = _merge_recovery_segments(wav_path)

    if not os.path.exists(wav_path):
        _patch_payload(job_id, diarize_error=f"WAV missing at {wav_path}")
        return False

    size = os.path.getsize(wav_path)
    if size < 1024:
        _patch_payload(
            job_id,
            diarize_error=f"Captured WAV is too small ({size} bytes) — nothing to diarize.",
        )
        return False

    print(f"\n🎙️  [diarize] {job_id} uploading {size//1024} KB to AssemblyAI…")

    try:
        import assemblyai as aai
    except Exception as e:
        _patch_payload(job_id, diarize_error=f"AssemblyAI SDK import failed: {e}")
        return False

    try:
        aai.settings.api_key = _get_assemblyai_key()
    except Exception as e:
        _patch_payload(job_id, diarize_error=str(e))
        return False

    try:
        cfg = aai.TranscriptionConfig(
            speaker_labels=True,
            # Best-effort language detection — works for Hindi/English mixed
            # financial shows. Falls back to English if undetected.
            language_detection=True,
        )
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(wav_path, config=cfg)
    except Exception as e:
        _patch_payload(job_id, diarize_error=f"AssemblyAI transcribe call failed: {e}")
        return False

    if transcript.status == aai.TranscriptStatus.error:
        _patch_payload(
            job_id,
            diarize_error=f"AssemblyAI returned error: {transcript.error}",
        )
        return False

    utterances = getattr(transcript, 'utterances', None) or []
    lines: list[str] = []
    if utterances:
        speaker_map = _map_speaker_roles(utterances)
        for u in utterances:
            ts = _format_timestamp(getattr(u, 'start', 0) or 0)
            raw = getattr(u, 'speaker', '?') or '?'
            label = speaker_map.get(raw, f"Speaker {raw}")
            text = (getattr(u, 'text', '') or '').strip()
            if text:
                lines.append(f"[{ts}] {label}: {text}")
    else:
        # No utterances (mono speaker / very short audio). Fall back to the
        # plain transcript text so the user still gets the diarized pane.
        # On Pradip's own show a single-speaker recording is almost
        # certainly Pradip himself.
        plain = (getattr(transcript, 'text', '') or '').strip()
        if plain:
            lines.append(f"[00:00:00] Pradip: {plain}")

    diarized = '\n'.join(lines).strip()
    if not diarized:
        diarized = '[No speech detected in the recorded stream.]'

    _patch_payload(
        job_id,
        diarized_transcript=diarized,
        diarize_error=None,
    )
    print(f"✅ [diarize] {job_id} → {len(lines)} utterance(s), {len(diarized)} chars")
    return True
