"""
Step 7: Filter Transcription - Keep only Anchor & Pradip Conversation

This step filters the English transcript to keep only dialogue from:
- The TV Anchor (interviewer) - ONLY when asking questions to Pradip
- Mr. Pradip Halder (stock expert) - All responses

Uses a buffer-based state machine approach:
- Anchor lines are buffered until we confirm they lead to Pradip's response
- If next speaker after Anchor(s) is Pradip → keep all buffered Anchor lines + Pradip line
- If next speaker after Anchor(s) is someone else → discard buffered Anchor lines
- Pradip lines are always kept (as they may be continuations)

This ensures we only keep the Anchor-Pradip conversation flow, removing
Anchor questions directed at other speakers.

Input: 
  - analysis/detected_speakers.txt (from Step 6)
  - transcripts/transcript_english.txt (from Step 5)
Output: 
  - transcripts/filtered_transcription.txt
"""

import os
import re


def extract_speaker(line):
    """
    Extract speaker name from a transcript line.
    Expected format: [Speaker Name] timestamp: text
    
    Returns:
        str or None: Speaker name if found, None otherwise
    """
    match = re.match(r'^\[([^\]]+)\]', line)
    if match:
        return match.group(1).strip()
    return None


def is_ignorable_speaker(speaker):
    """
    Check if a speaker label should be ignored (not treated as a real speaker).
    
    These are typically filler labels from transcription that shouldn't break
    the Anchor-Pradip conversation flow.
    
    Args:
        speaker: Speaker name/label from transcript
        
    Returns:
        bool: True if speaker should be ignored, False otherwise
    """
    if not speaker:
        return True
    
    speaker_lower = speaker.lower().strip()
    
    # List of ignorable speaker patterns (noise, ads, music, unknown, etc.)
    ignorable_patterns = [
        'music',
        'sponsor',
        'ad',
        'advertisement',
        'unknown',
        'noise',
        'background',
        'crowd',
        'applause',
        'laughter',
        'silence',
        'break',
        'commercial',
        'jingle',
        'intro',
        'outro',
        'theme',
        'voiceover',
        'narrator',
        'announcer',
        'promo',
        '[music]',
        '[noise]',
        '[applause]',
    ]
    
    # Check if speaker matches any ignorable pattern
    for pattern in ignorable_patterns:
        if pattern in speaker_lower:
            return True
    
    # Check for common unknown speaker formats
    if speaker_lower.startswith('speaker ') and speaker_lower.split()[-1].isdigit():
        # E.g., "Speaker 1", "Speaker 2" - generic speaker labels
        return True
    
    if speaker_lower.startswith('unknown'):
        return True
    
    return False


def filter_anchor_pradip_conversation(transcript_lines, anchor_speaker, pradip_speaker):
    """
    Filter transcript to keep only Anchor-Pradip conversation using buffer-based approach.
    
    Algorithm:
    1. Parse each line to identify speaker
    2. Buffer consecutive Anchor lines
    3. When Pradip line encountered: flush buffer (emit Anchor lines) + emit Pradip line
    4. When ignorable speaker (music, noise, etc.): skip but keep Anchor buffer intact
    5. When real other speaker encountered: clear buffer (discard Anchor lines)
    6. Pradip lines always kept (could be continuations from previous context)
    
    This handles:
    - Anchor → Pradip ✓ (keep both)
    - Anchor → Music → Pradip ✓ (keep Anchor + Pradip, skip Music)
    - Anchor → Sponsor → Pradip ✓ (keep Anchor + Pradip, skip Sponsor)
    - Anchor → OtherGuest ✗ (discard Anchor, OtherGuest is a real speaker)
    - Anchor → Anchor → Pradip ✓ (keep all - split question case)
    - Anchor → Anchor → OtherGuest ✗ (discard all Anchors)
    - Pradip → Anchor → Pradip ✓ (keep all)
    - Pradip → Pradip ✓ (keep both - continuation)
    
    Args:
        transcript_lines: List of transcript lines
        anchor_speaker: Detected anchor speaker label
        pradip_speaker: Detected Pradip speaker label
        
    Returns:
        list: Filtered transcript lines containing only Anchor-Pradip conversation
    """
    filtered_lines = []
    anchor_buffer = []  # Buffer to hold consecutive Anchor lines
    skipped_ignorable = 0  # Counter for skipped ignorable speakers
    
    for line in transcript_lines:
        speaker = extract_speaker(line)
        
        if speaker is None:
            continue
        
        if speaker == pradip_speaker:
            # Pradip is speaking - flush any buffered Anchor lines and add Pradip's line
            if anchor_buffer:
                filtered_lines.extend(anchor_buffer)
                anchor_buffer = []
            filtered_lines.append(line)
            
        elif speaker == anchor_speaker:
            # Anchor is speaking - buffer the line (don't emit yet)
            anchor_buffer.append(line)
            
        elif is_ignorable_speaker(speaker):
            # Ignorable speaker (music, noise, sponsor, etc.) - skip but keep Anchor buffer
            # These shouldn't break the Anchor-Pradip conversation flow
            skipped_ignorable += 1
            continue
            
        else:
            # Real other speaker (another guest/analyst) - discard any buffered Anchor lines
            # (they were questions to this other speaker, not Pradip)
            anchor_buffer = []
    
    # End of transcript - discard any remaining buffered Anchor lines
    # (they weren't followed by Pradip, so not part of Anchor-Pradip conversation)
    
    if skipped_ignorable > 0:
        print(f"   ℹ️  Skipped {skipped_ignorable} ignorable speaker lines (music, ads, etc.)")
    
    return filtered_lines


def run(job_folder):
    """
    Filter transcript to keep only Anchor-Pradip conversation.
    
    Uses buffer-based state machine to ensure Anchor lines are only kept
    if they are immediately followed by Pradip's response (handling split
    Anchor questions with consecutive Anchor lines).
    
    Args:
        job_folder: Path to job working directory
        
    Returns:
        dict with status, message, and output_files
    """
    print(f"\n{'='*60}")
    print("STEP 7: Filter Transcription (Anchor-Pradip Conversation Only)")
    print(f"{'='*60}\n")

    try:
        # Input/Output paths
        detected_speakers_file = os.path.join(job_folder, "analysis", "detected_speakers.txt")
        transcript_file = os.path.join(job_folder, "transcripts", "transcript_english.txt")
        output_file = os.path.join(job_folder, "transcripts", "filtered_transcription.txt")
        
        # Verify input files exist
        if not os.path.exists(detected_speakers_file):
            return {
                'status': 'failed',
                'message': 'detected_speakers.txt not found. Run Step 6 first.',
                'output_files': []
            }
        
        if not os.path.exists(transcript_file):
            return {
                'status': 'failed',
                'message': 'transcript_english.txt not found. Run Step 5 first.',
                'output_files': []
            }
        
        # --- Step 1: Load detected speakers ---
        print(f"📄 Reading detected speakers: {detected_speakers_file}")
        with open(detected_speakers_file, "r", encoding="utf-8") as f:
            detected = f.read().strip().splitlines()
        
        anchor_speaker = None
        pradip_speaker = None
        
        for line in detected:
            if line.startswith("Anchor:"):
                anchor_speaker = line.split(":", 1)[1].strip()
            elif line.startswith("Pradip:"):
                pradip_speaker = line.split(":", 1)[1].strip()
        
        if not anchor_speaker or not pradip_speaker:
            return {
                'status': 'failed',
                'message': 'Could not parse Anchor and Pradip from detected_speakers.txt',
                'output_files': []
            }
        
        print(f"✅ Anchor detected as: {anchor_speaker}")
        print(f"✅ Pradip detected as: {pradip_speaker}")
        
        # --- Step 2: Load transcript ---
        print(f"\n📄 Reading transcript: {transcript_file}")
        with open(transcript_file, "r", encoding="utf-8") as f:
            transcript_lines = [line.strip() for line in f.readlines() if line.strip()]
        
        print(f"✓ Loaded {len(transcript_lines)} total lines")
        
        # Count speakers before filtering
        anchor_count_before = sum(1 for line in transcript_lines if line.startswith(f"[{anchor_speaker}]"))
        pradip_count_before = sum(1 for line in transcript_lines if line.startswith(f"[{pradip_speaker}]"))
        other_count = len(transcript_lines) - anchor_count_before - pradip_count_before
        
        print(f"\n📊 Speaker breakdown (before filtering):")
        print(f"   - {anchor_speaker}: {anchor_count_before} lines")
        print(f"   - {pradip_speaker}: {pradip_count_before} lines")
        print(f"   - Other speakers: {other_count} lines")
        
        # --- Step 3: Apply smart Anchor-Pradip conversation filter ---
        print(f"\n🔍 Applying conversation-aware filtering...")
        print(f"   Rule: Keep Anchor lines ONLY if followed by {pradip_speaker}")
        
        filtered_lines = filter_anchor_pradip_conversation(
            transcript_lines, 
            anchor_speaker, 
            pradip_speaker
        )
        
        # Count speakers after filtering
        anchor_count_after = sum(1 for line in filtered_lines if line.startswith(f"[{anchor_speaker}]"))
        pradip_count_after = sum(1 for line in filtered_lines if line.startswith(f"[{pradip_speaker}]"))
        
        print(f"\n📊 Speaker breakdown (after filtering):")
        print(f"   - {anchor_speaker}: {anchor_count_after} lines (removed {anchor_count_before - anchor_count_after} irrelevant questions)")
        print(f"   - {pradip_speaker}: {pradip_count_after} lines")
        
        removed_lines = len(transcript_lines) - len(filtered_lines)
        print(f"\n✓ Kept {len(filtered_lines)} lines, removed {removed_lines} lines")
        
        if len(filtered_lines) == 0:
            return {
                'status': 'failed',
                'message': f'No conversation found between {anchor_speaker} and {pradip_speaker}',
                'output_files': []
            }
        
        # --- Step 4: Save filtered transcript ---
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(filtered_lines))
        
        print(f"\n✅ Saved filtered transcript: {output_file}")
        
        # Preview first 5 lines to show conversation flow
        print("\n--- Preview (first 5 lines showing conversation flow) ---")
        for line in filtered_lines[:5]:
            # Truncate long lines for preview
            if len(line) > 100:
                print(f"{line[:100]}...")
            else:
                print(line)
        print()
        
        return {
            'status': 'success',
            'message': f'Filtered transcript: kept {len(filtered_lines)} conversation lines ({anchor_count_after} Anchor + {pradip_count_after} Pradip), removed {removed_lines} lines (other speakers + Anchor questions to others)',
            'output_files': ['transcripts/filtered_transcription.txt']
        }
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Error filtering transcription: {str(e)}',
            'output_files': []
        }
