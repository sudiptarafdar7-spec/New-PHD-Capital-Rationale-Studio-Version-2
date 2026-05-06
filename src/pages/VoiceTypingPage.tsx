import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '@/lib/api-config';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Mic, MicOff, Save, ArrowLeft, Loader2, Volume2, Copy, Download,
  Link as LinkIcon, Send, AlertTriangle, ExternalLink, Server, Upload,
  PlayCircle, Sparkles, RotateCcw, Wand2, CheckCircle2, Circle,
  Languages,
} from 'lucide-react';
import { getYouTubeEmbedUrl } from '@/lib/youtube-utils';

interface MediaPresenceItem {
  id: number;
  platform: string;
  channel_name?: string | null;
  event_date: string;
  event_time: string;
  video_url: string | null;
  video_title: string | null;
  rationale_tool: string;
  transcribe_status: string;
  transcript_text?: string | null;
}

interface VoiceJob {
  jobId: string;
  title: string;
  status: string;
  channelId: number | null;
  channelName?: string | null;
  platform?: string | null;
  date: string | null;
  time: string | null;
  transcriptText: string;
  translatedText: string;
  arrangedText: string;
  language: string;
  videoUrl: string;
  bulkJobId: string | null;
  arrangeError?: string | null;
  translateError?: string | null;
  transcribeError?: string | null;
  transcribeProgress?: number;
}

interface Props {
  onNavigate: (page: string, id?: string | number | null) => void;
  mediaId?: number;
  voiceJobId?: string;
}

declare global {
  interface Window {
    SpeechRecognition?: any;
    webkitSpeechRecognition?: any;
  }
}

const ytEmbedUrl = (url?: string | null, autoplay = false) =>
  getYouTubeEmbedUrl(url, { autoplay });

const STATUS_LABEL: Record<string, { label: string; classes: string }> = {
  recording: { label: '1. Transcribing…', classes: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  awaiting_review: { label: '2. Review transcript', classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  translating: { label: 'Translating to English…', classes: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
  awaiting_translate_review: { label: '3. Review translation', classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  arranging: { label: "Extracting Pradip's analysis…", classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  awaiting_arrange_review: { label: '4. Review extraction', classes: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  bulk_started: { label: '5. Sent to Bulk Rationale', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  failed: { label: 'Failed', classes: 'bg-red-500/15 text-red-300 border-red-500/30' },
  completed: { label: 'Completed', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
};

function statusBadge(status: string) {
  const meta = STATUS_LABEL[status] || { label: status, classes: 'bg-slate-500/15 text-slate-300 border-slate-500/30' };
  return <Badge variant="outline" className={`${meta.classes} border`}>{meta.label}</Badge>;
}

export default function VoiceTypingPage({ onNavigate, mediaId, voiceJobId }: Props) {
  const { token } = useAuth();

  // ----- Mode-specific state -----
  const [item, setItem] = useState<MediaPresenceItem | null>(null);
  const [job, setJob] = useState<VoiceJob | null>(null);
  const [loading, setLoading] = useState(!!(mediaId || voiceJobId));
  const [saving, setSaving] = useState(false);
  const [stoppingServer, setStoppingServer] = useState(false);
  const [uploadingAudio, setUploadingAudio] = useState(false);

  // Local edit buffer for the awaiting_review phase. We keep edits client-side
  // and autosave on a debounce so typing isn't blocked by every keystroke
  // hitting the network.
  const [editBuffer, setEditBuffer] = useState<string>('');
  const editBufferDirty = useRef(false);
  const editAutosaveTimer = useRef<number | null>(null);

  // Same idea for the translated-text editor (visible during awaiting_translate_review).
  const [translatedBuffer, setTranslatedBuffer] = useState<string>('');
  const translatedBufferDirty = useRef(false);
  const translatedAutosaveTimer = useRef<number | null>(null);

  // Same idea for the arranged-text editor (visible during awaiting_arrange_review).
  const [arrangedBuffer, setArrangedBuffer] = useState<string>('');
  const arrangedBufferDirty = useRef(false);
  const arrangedAutosaveTimer = useRef<number | null>(null);

  // Video popup (the user asked for a popup-modal player so the long YouTube
  // title doesn't blow up the page layout).
  const [videoOpen, setVideoOpen] = useState(false);
  // Right-pane tab — 'transcript' (raw editable Vosk text), 'translation'
  // (English translation, editable in awaiting_translate_review), or
  // 'arrangement' (Pradip-extracted stock\nanalysis, editable in
  // awaiting_arrange_review). We keep all three on the right side so the
  // sticky video stays visible while the user reviews each stage.
  const [activeRightTab, setActiveRightTab] = useState<'transcript' | 'translation' | 'arrangement'>('transcript');

  // Pipeline-flight flags
  const [translatingFlag, setTranslatingFlag] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [sendingToBulk, setSendingToBulk] = useState(false);

  // ----- Legacy mediaId mode (browser Web Speech) -----
  const [audioInputs, setAudioInputs] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('');
  const [legacyTranscript, setLegacyTranscript] = useState('');
  const [legacyInterim, setLegacyInterim] = useState('');
  const [legacyListening, setLegacyListening] = useState(false);
  const [legacyLanguage, setLegacyLanguage] = useState('hi-IN');
  const [legacyVu, setLegacyVu] = useState(0);
  const legacyRecogRef = useRef<any>(null);
  const legacyAudioCtxRef = useRef<AudioContext | null>(null);
  const legacyAnalyserRef = useRef<AnalyserNode | null>(null);
  const legacyVuRafRef = useRef<number | null>(null);
  const legacyMicStreamRef = useRef<MediaStream | null>(null);

  // Standalone (no media, no job) — keeps the old "scratch" mode working
  const [urlInput, setUrlInput] = useState('');
  const [standaloneVideoUrl, setStandaloneVideoUrl] = useState('');

  const speechSupported = useMemo(
    () => typeof window !== 'undefined' && (!!window.SpeechRecognition || !!window.webkitSpeechRecognition),
    [],
  );

  // ===========================================================================
  // mediaId loader (legacy Media Presence flow)
  // ===========================================================================
  useEffect(() => {
    if (!mediaId) return;
    (async () => {
      try {
        const r = await fetch(API_ENDPOINTS.mediaPresence.get(mediaId), {
          headers: getAuthHeaders(token || undefined),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || 'Load failed');
        setItem(j.item);
        setLegacyTranscript(j.item.transcript_text || '');
      } catch (e: any) {
        toast.error(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [mediaId, token]);

  // ===========================================================================
  // Voice Typing JOB loader + server-side poller
  //
  // The server's Vosk worker IS the source of truth for transcript text while
  // the job is in 'recording' status. We poll every 2 seconds during that
  // phase to surface live progress. Once the worker flips the job to
  // 'awaiting_review' we slow the poll right down (10s) and the user can edit
  // the textarea freely.
  // ===========================================================================
  useEffect(() => {
    if (!voiceJobId) return;
    let cancelled = false;
    let timer: number | null = null;

    const fetchOnce = async () => {
      try {
        const r = await fetch(API_ENDPOINTS.voiceTyping.get(voiceJobId), {
          headers: getAuthHeaders(token || undefined),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || 'Job load failed');
        if (cancelled) return j.job as VoiceJob;
        setJob(j.job);
        // Sync the raw-transcript edit buffer ONLY when we're not in the
        // awaiting_review editing phase, OR if the user hasn't touched it
        // yet. We don't want a poll to clobber half-typed edits.
        if (j.job.status === 'recording' || !editBufferDirty.current) {
          setEditBuffer(j.job.transcriptText || '');
        }
        // Same idea for the translated buffer — accept server updates while
        // GPT is still translating, but freeze once the user starts editing.
        if (j.job.status === 'translating' || !translatedBufferDirty.current) {
          setTranslatedBuffer(j.job.translatedText || '');
        }
        // Same idea for the arranged buffer — accept server updates while
        // GPT is still extracting, but freeze once the user starts editing.
        if (j.job.status === 'arranging' || !arrangedBufferDirty.current) {
          setArrangedBuffer(j.job.arrangedText || '');
        }
        return j.job as VoiceJob;
      } catch (e: any) {
        if (!cancelled) console.warn('voice-typing poll failed', e.message);
        return null;
      } finally {
        if (!cancelled && loading) setLoading(false);
      }
    };

    const schedule = (job: VoiceJob | null) => {
      if (cancelled) return;
      const status = job?.status || 'recording';
      // Aggressive 2s poll while the server is doing async work
      // (transcribing / translating / extracting); gentle 10s otherwise.
      const delay = (status === 'recording'
                  || status === 'translating'
                  || status === 'arranging') ? 2000 : 10000;
      timer = window.setTimeout(async () => {
        const next = await fetchOnce();
        schedule(next);
      }, delay);
    };

    fetchOnce().then(schedule);

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceJobId, token]);

  // ===========================================================================
  // Edit-buffer autosave (awaiting_review phase only)
  // ===========================================================================
  useEffect(() => {
    if (!voiceJobId || !job) return;
    if (job.status !== 'awaiting_review' && job.status !== 'failed') return;
    if (!editBufferDirty.current) return;

    if (editAutosaveTimer.current) window.clearTimeout(editAutosaveTimer.current);
    editAutosaveTimer.current = window.setTimeout(async () => {
      try {
        await fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ transcriptText: editBuffer }),
        });
        editBufferDirty.current = false;
      } catch (e) {
        console.warn('autosave failed', e);
      }
    }, 1500);

    return () => {
      if (editAutosaveTimer.current) window.clearTimeout(editAutosaveTimer.current);
    };
  }, [editBuffer, voiceJobId, job?.status, token]);

  // Latest-value refs: the unmount cleanup below has stable deps
  // ([voiceJobId, token]) so it would otherwise capture the *first* render's
  // editBuffer/arrangedBuffer via closure, losing every keystroke since.
  // Mirroring the buffers into refs on every render keeps the cleanup honest.
  const latestEditBuffer = useRef(editBuffer);
  const latestTranslatedBuffer = useRef(translatedBuffer);
  const latestArrangedBuffer = useRef(arrangedBuffer);
  useEffect(() => { latestEditBuffer.current = editBuffer; }, [editBuffer]);
  useEffect(() => { latestTranslatedBuffer.current = translatedBuffer; }, [translatedBuffer]);
  useEffect(() => { latestArrangedBuffer.current = arrangedBuffer; }, [arrangedBuffer]);

  // Auto-switch the right pane to the appropriate stage tab as the job
  // advances. Going back to a previous stage is always a single click on
  // the corresponding tab.
  useEffect(() => {
    const s = job?.status;
    if (s === 'arranging' || s === 'awaiting_arrange_review' || s === 'bulk_started' || s === 'completed') {
      setActiveRightTab('arrangement');
    } else if (s === 'translating' || s === 'awaiting_translate_review') {
      setActiveRightTab('translation');
    } else {
      setActiveRightTab('transcript');
    }
  }, [job?.status]);

  // Flush edits on unmount so nothing is lost when navigating away.
  useEffect(() => {
    return () => {
      if (!voiceJobId) return;
      if (editBufferDirty.current) {
        fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ transcriptText: latestEditBuffer.current }),
          keepalive: true,
        }).catch(() => {});
      }
      if (translatedBufferDirty.current) {
        fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ translatedText: latestTranslatedBuffer.current }),
          keepalive: true,
        }).catch(() => {});
      }
      if (arrangedBufferDirty.current) {
        fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ arrangedText: latestArrangedBuffer.current }),
          keepalive: true,
        }).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceJobId, token]);

  // Translated-text autosave (only meaningful while awaiting_translate_review).
  useEffect(() => {
    if (!voiceJobId || !job) return;
    if (job.status !== 'awaiting_translate_review') return;
    if (!translatedBufferDirty.current) return;

    if (translatedAutosaveTimer.current) window.clearTimeout(translatedAutosaveTimer.current);
    translatedAutosaveTimer.current = window.setTimeout(async () => {
      try {
        await fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ translatedText: translatedBuffer }),
        });
        translatedBufferDirty.current = false;
      } catch (e) {
        console.warn('translated autosave failed', e);
      }
    }, 1500);

    return () => {
      if (translatedAutosaveTimer.current) window.clearTimeout(translatedAutosaveTimer.current);
    };
  }, [translatedBuffer, voiceJobId, job?.status, token]);

  // Arranged-text autosave (only meaningful while awaiting_arrange_review).
  useEffect(() => {
    if (!voiceJobId || !job) return;
    if (job.status !== 'awaiting_arrange_review') return;
    if (!arrangedBufferDirty.current) return;

    if (arrangedAutosaveTimer.current) window.clearTimeout(arrangedAutosaveTimer.current);
    arrangedAutosaveTimer.current = window.setTimeout(async () => {
      try {
        await fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ arrangedText: arrangedBuffer }),
        });
        arrangedBufferDirty.current = false;
      } catch (e) {
        console.warn('arranged autosave failed', e);
      }
    }, 1500);

    return () => {
      if (arrangedAutosaveTimer.current) window.clearTimeout(arrangedAutosaveTimer.current);
    };
  }, [arrangedBuffer, voiceJobId, job?.status, token]);

  // ===========================================================================
  // Stop server transcription
  // ===========================================================================
  const stopServerTranscription = async () => {
    if (!voiceJobId) return;
    setStoppingServer(true);
    try {
      // Server-side Vosk worker polls jobs.status between chunks; flipping to
      // 'awaiting_review' tells it to finalize what it has and exit.
      await fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
        method: 'PATCH',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ status: 'awaiting_review' }),
      });
      toast.success('Stop signal sent. The worker will finalize the transcript shortly.');
    } catch (e: any) {
      toast.error(e.message || 'Could not stop transcription');
    } finally {
      setStoppingServer(false);
    }
  };

  // ===========================================================================
  // Step 3: send the (edited) raw transcript to OpenAI for English
  //          translation. Server parks the result at
  //          status='awaiting_translate_review' for the user to review.
  // ===========================================================================
  const translateToEnglish = async () => {
    if (!voiceJobId) return;
    const text = editBuffer.trim();
    if (!text) { toast.error('Transcript is empty.'); return; }
    setTranslatingFlag(true);
    try {
      const r = await fetch(API_ENDPOINTS.voiceTyping.translate(voiceJobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ transcriptText: text }),
      });
      const j = await r.json();
      if (!r.ok && r.status !== 202) throw new Error(j.error || 'Translate failed');
      editBufferDirty.current = false;
      // Translation will overwrite the server's translated_text; drop any
      // stale dirty flag on the translated buffer.
      translatedBufferDirty.current = false;
      toast.success('Translating — review the result on the Translation tab.');
      const refreshed = await fetch(API_ENDPOINTS.voiceTyping.get(voiceJobId), {
        headers: getAuthHeaders(token || undefined),
      });
      const refreshedJson = await refreshed.json();
      if (refreshed.ok) setJob(refreshedJson.job);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setTranslatingFlag(false);
    }
  };

  // ===========================================================================
  // Step 4: send the (edited) translated transcript to OpenAI to extract
  //          Pradip Halder's analysis. Server parks the result at
  //          status='awaiting_arrange_review' for the user to review.
  // ===========================================================================
  const extractAnalysis = async () => {
    if (!voiceJobId) return;
    const text = translatedBuffer.trim();
    if (!text) { toast.error('Translated text is empty.'); return; }
    setArranging(true);
    try {
      const r = await fetch(API_ENDPOINTS.voiceTyping.arrange(voiceJobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ translatedText: text }),
      });
      const j = await r.json();
      if (!r.ok && r.status !== 202) throw new Error(j.error || 'Extract failed');
      translatedBufferDirty.current = false;
      // Extract will overwrite the server's arranged_text; drop any stale
      // dirty flag on the arranged buffer.
      arrangedBufferDirty.current = false;
      toast.success("Extracting Pradip's analysis — review the result on the Arrangement tab.");
      const refreshed = await fetch(API_ENDPOINTS.voiceTyping.get(voiceJobId), {
        headers: getAuthHeaders(token || undefined),
      });
      const refreshedJson = await refreshed.json();
      if (refreshed.ok) setJob(refreshedJson.job);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setArranging(false);
    }
  };

  // ===========================================================================
  // Step 5: user approved the arrangement → spawn Bulk Rationale child.
  // ===========================================================================
  const sendToBulkRationale = async () => {
    if (!voiceJobId) return;
    const text = arrangedBuffer.trim();
    if (!text) { toast.error('Arranged text is empty.'); return; }
    setSendingToBulk(true);
    try {
      const r = await fetch(API_ENDPOINTS.voiceTyping.sendToBulk(voiceJobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ arrangedText: text }),
      });
      const j = await r.json();
      if (!r.ok && r.status !== 202) throw new Error(j.error || 'Send failed');
      arrangedBufferDirty.current = false;
      toast.success('Bulk Rationale child job is starting.');
      const refreshed = await fetch(API_ENDPOINTS.voiceTyping.get(voiceJobId), {
        headers: getAuthHeaders(token || undefined),
      });
      const refreshedJson = await refreshed.json();
      if (refreshed.ok) setJob(refreshedJson.job);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSendingToBulk(false);
    }
  };

  // Escape hatch: revert all the way back to raw-transcript review (user
  // wants to re-edit the source before re-translating / re-extracting).
  const revertToRawReview = async () => {
    if (!voiceJobId) return;
    if (!confirm('Go back to the raw transcript? You will need to translate and extract again from scratch.')) return;
    try {
      const r = await fetch(API_ENDPOINTS.voiceTyping.update(voiceJobId), {
        method: 'PATCH',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ status: 'awaiting_review' }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Revert failed');
      translatedBufferDirty.current = false;
      arrangedBufferDirty.current = false;
      if (j.job) setJob(j.job);
      toast.success('Back to raw transcript — edit and translate when ready.');
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  // ===========================================================================
  // Legacy mediaId-mode helpers (browser Web Speech — UNCHANGED)
  // ===========================================================================
  const refreshDevices = async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter(d => d.kind === 'audioinput');
      setAudioInputs(inputs);
      if (!selectedDeviceId && inputs[0]) setSelectedDeviceId(inputs[0].deviceId);
    } catch (e) {
      console.warn('enumerateDevices failed', e);
    }
  };

  useEffect(() => {
    if (!mediaId) return;
    refreshDevices();
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices);
    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices);
      stopLegacyMicStream();
      stopLegacyRecognition();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaId]);

  const stopLegacyMicStream = () => {
    if (legacyVuRafRef.current) cancelAnimationFrame(legacyVuRafRef.current);
    legacyVuRafRef.current = null;
    legacyMicStreamRef.current?.getTracks().forEach(t => t.stop());
    legacyMicStreamRef.current = null;
    legacyAudioCtxRef.current?.close().catch(() => {});
    legacyAudioCtxRef.current = null;
    legacyAnalyserRef.current = null;
    setLegacyVu(0);
  };

  const startLegacyVuMeter = async (deviceId: string) => {
    stopLegacyMicStream();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
    legacyMicStreamRef.current = stream;
    const ctx = new AudioContext();
    legacyAudioCtxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    legacyAnalyserRef.current = analyser;
    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      setLegacyVu(Math.sqrt(sum / data.length));
      legacyVuRafRef.current = requestAnimationFrame(tick);
    };
    tick();
    refreshDevices();
  };

  const stopLegacyRecognition = () => {
    try { legacyRecogRef.current?.stop(); } catch { /* ignore */ }
    legacyRecogRef.current = null;
    setLegacyListening(false);
  };

  const startLegacyRecognition = async () => {
    if (!speechSupported) {
      toast.error('Browser voice typing requires Chrome or Edge desktop.');
      return;
    }
    try {
      if (!legacyMicStreamRef.current) await startLegacyVuMeter(selectedDeviceId);
      const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recog = new Ctor();
      recog.continuous = true;
      recog.interimResults = true;
      recog.lang = legacyLanguage;
      recog.onresult = (event: any) => {
        let finalChunk = '';
        let interimChunk = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) finalChunk += result[0].transcript;
          else interimChunk += result[0].transcript;
        }
        if (finalChunk) {
          setLegacyTranscript(prev => (prev + ' ' + finalChunk).replace(/\s+/g, ' ').trimStart());
        }
        setLegacyInterim(interimChunk);
      };
      recog.onerror = (e: any) => {
        if (e.error === 'no-speech' || e.error === 'audio-capture') return;
        toast.error(`Voice typing error: ${e.error}`);
      };
      recog.onend = () => {
        if (legacyRecogRef.current === recog) {
          try { recog.start(); } catch { /* ignore */ }
        }
      };
      recog.start();
      legacyRecogRef.current = recog;
      setLegacyListening(true);
      toast.success('Browser voice typing on.');
    } catch (e: any) {
      toast.error(e.message || 'Could not start voice typing');
    }
  };

  const saveLegacyTranscript = async () => {
    if (!mediaId) return;
    if (!legacyTranscript.trim()) { toast.error('Transcript is empty.'); return; }
    setSaving(true);
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.saveTranscript(mediaId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({
          transcript_text: legacyTranscript,
          transcribe_method: 'voice_typing',
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Save failed');
      toast.success('Transcript saved — rationale job started.');
      onNavigate('media-presence');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  // ===========================================================================
  // Derived state
  // ===========================================================================
  const status = job?.status || 'recording';
  const isJobMode = !!voiceJobId;
  const translateBusy = status === 'translating';
  const arrangeBusy = status === 'arranging';
  // Step 3 review = user is editing the GPT translation before it goes
  // into the Pradip-extract step.
  const translateReview = isJobMode && status === 'awaiting_translate_review';
  // Step 4 review = user is editing the extracted (stock\nanalysis) text
  // before it goes into Bulk Rationale.
  const arrangeReview = isJobMode && status === 'awaiting_arrange_review';
  const finished = status === 'bulk_started' || status === 'completed';
  const transcribing = isJobMode && status === 'recording';
  // The raw transcript is editable in awaiting_review and after a failure.
  // After the user has translated, the source is locked — they revert via
  // the "Edit raw transcript" button.
  const editable = isJobMode && (status === 'awaiting_review' || status === 'failed');
  const translatedEditable = translateReview;

  const transcribeProgress = job?.transcribeProgress || 0;

  const transcriptForCopy = isJobMode ? editBuffer : legacyTranscript;

  const copyTranscript = async () => {
    if (!transcriptForCopy.trim()) { toast.error('Transcript is empty.'); return; }
    try {
      await navigator.clipboard.writeText(transcriptForCopy);
      toast.success('Transcript copied to clipboard.');
    } catch {
      toast.error('Could not copy to clipboard.');
    }
  };

  const downloadTranscript = () => {
    if (!transcriptForCopy.trim()) { toast.error('Transcript is empty.'); return; }
    const blob = new Blob([transcriptForCopy], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `voice-typing-${(voiceJobId || 'session')}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // ===========================================================================
  // Render
  // ===========================================================================
  if (loading) {
    return <div className="p-6"><Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading…</div>;
  }

  const displayedTranscript = isJobMode
    ? editBuffer
    : (legacyTranscript + (legacyInterim ? ` ${legacyInterim}` : ''));

  const effectiveVideoUrl = isJobMode ? (job?.videoUrl || '')
                          : mediaId    ? (item?.video_url || '')
                          : standaloneVideoUrl;

  // Auto-play the video so the user can follow along while the server transcribes.
  const wantAutoplay = isJobMode && (status === 'recording' || status === 'awaiting_review');

  const headingDescription = isJobMode && job ? (
    <>For: <b>{(job.platform || '').toUpperCase()}</b> · {job.channelName || '—'} · {job.date || ''} {job.time || ''}</>
  ) : mediaId && item ? (
    <>For: <b>{item.platform.toUpperCase()}</b> · {item.channel_name || '—'} · {item.event_date} {item.event_time}</>
  ) : (
    'Standalone mode — paste a video URL below, play it, and start voice typing.'
  );

  const backTarget = isJobMode ? 'voice-typing' : mediaId ? 'media-presence' : null;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl text-foreground flex items-center gap-2">
            <Mic className="w-6 h-6 text-primary" /> Voice Typing
            {isJobMode && job && <span className="ml-2">{statusBadge(job.status)}</span>}
          </h1>
          <p className="text-muted-foreground">{headingDescription}</p>
          {isJobMode && (
            // Long YouTube titles wreck the page layout, so we only show the
            // (short, predictable) job id here. The full title is still
            // available on hover via the title= attribute.
            <p
              className="text-xs text-muted-foreground mt-0.5 font-mono"
              title={job?.title || voiceJobId}
            >
              {voiceJobId}
            </p>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          {backTarget && (
            <Button variant="outline" onClick={() => onNavigate(backTarget, null)}>
              <ArrowLeft className="w-4 h-4 mr-1" /> Back
            </Button>
          )}
          <Button variant="outline" onClick={copyTranscript} disabled={!transcriptForCopy.trim()}>
            <Copy className="w-4 h-4 mr-1" /> Copy
          </Button>
          <Button variant="outline" onClick={downloadTranscript} disabled={!transcriptForCopy.trim()}>
            <Download className="w-4 h-4 mr-1" /> .txt
          </Button>
          {/* Watch-video popup trigger — keeps the long YouTube embed out of
              the main layout. Only shown when this job actually has a URL
              (uploaded-audio jobs won't). */}
          {isJobMode && job?.videoUrl && (
            <Button variant="outline" onClick={() => setVideoOpen(true)}>
              <PlayCircle className="w-4 h-4 mr-1" /> Watch video
            </Button>
          )}
          {isJobMode && transcribing && (
            <Button onClick={stopServerTranscription} variant="destructive" disabled={stoppingServer}>
              {stoppingServer
                ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                : <MicOff className="w-4 h-4 mr-1" />}
              Stop transcribing
            </Button>
          )}

          {/* Step 2 → 3: editable raw transcript → translate to English */}
          {isJobMode && (editable || status === 'awaiting_review') && (
            <Button
              onClick={translateToEnglish}
              disabled={translatingFlag || translateBusy || transcribing || !editBuffer.trim()}
            >
              {translatingFlag || translateBusy
                ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                : <Languages className="w-4 h-4 mr-1" />}
              Translate to English
            </Button>
          )}

          {/* Step 3 → 4: user reviewed translation → extract Pradip's analysis */}
          {translateReview && (
            <>
              <Button
                variant="outline"
                onClick={revertToRawReview}
                disabled={translatingFlag || arranging}
              >
                <RotateCcw className="w-4 h-4 mr-1" /> Edit raw transcript
              </Button>
              <Button
                variant="outline"
                onClick={translateToEnglish}
                disabled={translatingFlag || translateBusy || arranging || !editBuffer.trim()}
              >
                {translatingFlag
                  ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                  : <Languages className="w-4 h-4 mr-1" />}
                Re-translate
              </Button>
              <Button
                onClick={extractAnalysis}
                disabled={arranging || arrangeBusy || translatingFlag || !translatedBuffer.trim()}
              >
                {arranging || arrangeBusy
                  ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                  : <Wand2 className="w-4 h-4 mr-1" />}
                Extract Pradip's Analysis
              </Button>
            </>
          )}

          {/* Step 4 → 5: user reviewed extraction → Bulk Rationale */}
          {arrangeReview && (
            <>
              <Button
                variant="outline"
                onClick={revertToRawReview}
                disabled={arranging || sendingToBulk}
              >
                <RotateCcw className="w-4 h-4 mr-1" /> Edit raw transcript
              </Button>
              <Button
                variant="outline"
                onClick={extractAnalysis}
                disabled={arranging || arrangeBusy || sendingToBulk || !translatedBuffer.trim()}
              >
                {arranging
                  ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                  : <Sparkles className="w-4 h-4 mr-1" />}
                Re-extract
              </Button>
              <Button
                onClick={sendToBulkRationale}
                disabled={sendingToBulk || arranging || arrangeBusy || !arrangedBuffer.trim()}
              >
                {sendingToBulk
                  ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                  : <Send className="w-4 h-4 mr-1" />}
                Send to Bulk Rationale
              </Button>
            </>
          )}

          {mediaId && (
            <Button onClick={saveLegacyTranscript} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}
              Save &amp; trigger rationale
            </Button>
          )}
        </div>
      </div>

      {isJobMode && transcribing && (
        <Alert>
          <Server className="w-4 h-4 animate-pulse" />
          <AlertTitle>Server is transcribing this video</AlertTitle>
          <AlertDescription className="space-y-2 mt-1">
            <div>
              You can close this tab and come back later — Vosk is running on the server.
              Live transcript text appears below as the engine processes the audio.
            </div>
            <div className="w-full bg-slate-700/50 rounded-full h-2 overflow-hidden">
              <div
                className="bg-rose-400 h-full transition-all"
                style={{ width: `${Math.max(2, transcribeProgress)}%` }}
              />
            </div>
            <div className="text-xs text-muted-foreground">{transcribeProgress}% — {STATUS_LABEL[status].label}</div>
          </AlertDescription>
        </Alert>
      )}

      {isJobMode && status === 'failed' && (job?.transcribeError || job?.translateError || job?.arrangeError) && (
        <Alert variant="destructive">
          <AlertTriangle className="w-4 h-4" />
          <AlertTitle>
            {job?.transcribeError
              ? 'Transcription failed'
              : job?.translateError
                ? 'Translate step failed'
                : 'Extract step failed'}
          </AlertTitle>
          <AlertDescription>
            <div className="whitespace-pre-line">
              {job?.transcribeError || job?.translateError || job?.arrangeError}
            </div>
            <div className="mt-2 text-xs">
              Edit the transcript and click <b>Translate to English</b> to retry,
              upload an audio file below, or delete this job and start over.
            </div>
            {job?.transcribeError && (
              <UploadAudioFallback
                jobId={job.jobId}
                token={token || undefined}
                uploading={uploadingAudio}
                setUploading={setUploadingAudio}
                onUploaded={(updated) => setJob(updated)}
              />
            )}
          </AlertDescription>
        </Alert>
      )}

      {isJobMode && finished && job?.bulkJobId && (
        <Alert>
          <Send className="w-4 h-4" />
          <AlertTitle>Bulk Rationale started</AlertTitle>
          <AlertDescription className="flex items-center gap-2 mt-1">
            Child job <code>{job.bulkJobId}</code> is now running in Bulk Rationale.
            <Button size="sm" variant="link" className="px-1" onClick={() => onNavigate('bulk-rationale', job.bulkJobId!)}>
              Open it <ExternalLink className="w-3 h-3 ml-1" />
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {!isJobMode && !speechSupported && (
        <Alert variant="destructive">
          <AlertTitle>Browser not supported</AlertTitle>
          <AlertDescription>
            The legacy Media Presence voice-typing flow uses the browser Web Speech API
            and only works in Chrome / Edge desktop. For the new server-side flow,
            use the Voice Typing jobs page.
          </AlertDescription>
        </Alert>
      )}

      {/* Layout: side-by-side video + transcript whenever we actually have
          a video to show (standalone, mediaId-legacy, OR a server-side job
          with a videoUrl). Otherwise the transcript takes the full width.
          Grid cells stretch to equal heights by default — needed so the
          sticky Card inside the video cell has room to "stick" within its
          grid cell as the user scrolls the long transcript. (CSS-Grid
          sticky pitfall: if you give the sticky element itself
          `self-start`, the cell shrinks to fit the element and there's
          nowhere to scroll → sticky becomes a no-op. Wrapping the Card in
          a plain div lets the cell stretch while the inner Card stays
          sticky.) */}
      <div className={
        (effectiveVideoUrl || !isJobMode)
          ? 'grid grid-cols-1 lg:grid-cols-2 gap-4'
          : 'space-y-4'
      }>
        {(!isJobMode || !!job?.videoUrl) && (
          <div>
            <Card className="lg:sticky lg:top-4">
              <CardHeader>
                <CardTitle>Video</CardTitle>
                <CardDescription className="break-all line-clamp-2">
                  {isJobMode
                    ? (job?.title || job?.videoUrl || 'Reference video for this job.')
                    : mediaId
                      ? (item?.video_title || item?.video_url || 'No video URL set on this entry.')
                      : 'Paste any YouTube / video URL — it will be embedded so you can play it while voice typing.'}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* URL input is only meaningful in standalone mode (no
                    mediaId, no job). For jobMode + mediaId we already have
                    a fixed video URL on the entry / job. */}
                {!isJobMode && !mediaId && (
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <LinkIcon className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        value={urlInput}
                        onChange={e => setUrlInput(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter' && urlInput.trim()) setStandaloneVideoUrl(urlInput.trim()); }}
                        placeholder="https://www.youtube.com/watch?v=..."
                        className="pl-8"
                      />
                    </div>
                    <Button onClick={() => urlInput.trim() && setStandaloneVideoUrl(urlInput.trim())} variant="secondary">Load</Button>
                  </div>
                )}

                {/* Player area — fixed 16:9 aspect ratio (the only sane
                    shape for a YouTube embed). `aspect-video` keeps width
                    100% of the column and computes height = width * 9/16,
                    so the player always looks correct regardless of
                    viewport. `getYouTubeEmbedUrl` returns '' for anything
                    we can't safely embed; in that case we render a
                    fallback in the same 16:9 box (with an "Open on
                    YouTube" link) instead of an iframe with junk src —
                    an iframe with `src=''` silently loads the parent
                    document (= the Dashboard SPA route), which was the
                    "video card showing dashboard" bug. */}
                {effectiveVideoUrl ? (() => {
                  const embedSrc = ytEmbedUrl(effectiveVideoUrl, wantAutoplay);
                  const containerCls = 'w-full aspect-video bg-black rounded-lg overflow-hidden';
                  if (embedSrc) {
                    return (
                      <div className={containerCls}>
                        <iframe
                          key={embedSrc}
                          src={embedSrc}
                          title="video"
                          className="w-full h-full block"
                          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                          allowFullScreen
                        />
                      </div>
                    );
                  }
                  return (
                    <div className={`${containerCls} bg-slate-900 flex flex-col items-center justify-center gap-3 p-6 text-center`}>
                      <AlertTriangle className="w-8 h-8 text-amber-400" />
                      <div className="text-sm text-muted-foreground max-w-md">
                        This video can't be embedded inline (only YouTube videos can be played here). Open it in a new tab to watch while you transcribe.
                      </div>
                      <a
                        href={effectiveVideoUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 text-sm text-primary hover:underline break-all"
                      >
                        <ExternalLink className="w-4 h-4" /> Open video
                      </a>
                    </div>
                  );
                })() : (
                  <div className="w-full aspect-video bg-slate-900 rounded-lg flex items-center justify-center text-muted-foreground text-sm">
                    {mediaId ? 'No video URL on this entry' : 'Paste a video URL above and click Load.'}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {/* Right column.
            - jobMode: Tabs with Transcript + Arrangement. The arrangement
              used to render in a third row below the grid; users asked
              for it on the right beside the video instead, so the sticky
              video stays visible while reviewing the arrangement. Tab
              auto-switches to Arrangement when ChatGPT starts working
              (see the activeRightTab effect).
            - legacy/standalone (non-jobMode): just the transcript card. */}
        {isJobMode ? (
          <div>
            <Tabs
              value={activeRightTab}
              onValueChange={(v: string) => setActiveRightTab(v as 'transcript' | 'translation' | 'arrangement')}
              className="w-full"
            >
              <TabsList className="grid grid-cols-3 w-full mb-3">
                <TabsTrigger value="transcript">
                  Transcript
                  {transcribing && (
                    <Server className="ml-2 w-3 h-3 animate-pulse text-rose-300" />
                  )}
                </TabsTrigger>
                <TabsTrigger value="translation">
                  <Languages className="w-3 h-3 mr-1 text-cyan-300" />
                  Translation
                  {translateBusy && (
                    <Loader2 className="ml-2 w-3 h-3 animate-spin text-cyan-300" />
                  )}
                </TabsTrigger>
                <TabsTrigger value="arrangement">
                  <Sparkles className="w-3 h-3 mr-1 text-violet-300" />
                  Arrangement
                  {arrangeBusy && (
                    <Loader2 className="ml-2 w-3 h-3 animate-spin text-sky-300" />
                  )}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="transcript" className="mt-0">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      Transcript
                      {transcribing && (
                        <span className="flex items-center gap-1 text-xs text-rose-300">
                          <Server className="w-3 h-3 animate-pulse" /> server transcribing
                        </span>
                      )}
                    </CardTitle>
                    <CardDescription>
                      {transcribing
                        ? 'Read-only while Vosk is working — text updates every couple of seconds.'
                        : editable
                          ? 'Step 2: edit freely (changes autosave 1.5s after you stop typing). When happy, click Translate to English.'
                          : translateBusy
                            ? 'GPT is translating to English — see the Translation tab.'
                            : translateReview
                              ? 'Locked — review the translation on the Translation tab. Use "Edit raw transcript" to come back here.'
                              : arrangeReview
                                ? 'Locked — review the extraction on the Arrangement tab. Use "Edit raw transcript" to come back here.'
                                : arrangeBusy
                                  ? "GPT is extracting Pradip's analysis — see the Arrangement tab."
                                  : 'Transcript is locked — bulk pipeline is in flight.'}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Textarea
                      value={displayedTranscript}
                      onChange={e => {
                        if (!editable) return;
                        editBufferDirty.current = true;
                        setEditBuffer(e.target.value);
                      }}
                      rows={20}
                      readOnly={!editable}
                      placeholder={transcribing
                        ? 'Vosk is working… transcript will appear here.'
                        : 'Transcript will be editable once the server finishes.'}
                      className="font-mono text-sm"
                    />
                    <p className="text-xs text-muted-foreground">
                      Tip: server transcription keeps running even if you close this tab. Re-open the job from the Voice Typing list any time.
                    </p>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="translation" className="mt-0">
                {translateBusy ? (
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Languages className="w-4 h-4 text-cyan-300" />
                        Translating to English…
                      </CardTitle>
                      <CardDescription>
                        GPT-4o is translating the reviewed transcript to English.
                        This usually takes 10–40 seconds depending on length.
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <TranslateStepLoader />
                    </CardContent>
                  </Card>
                ) : (translateReview || translatedBuffer || arrangeReview || arrangeBusy || finished) ? (
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Languages className="w-4 h-4 text-cyan-300" />
                        English translation {translateReview && <span className="text-xs text-amber-300">(step 3 — review &amp; edit)</span>}
                      </CardTitle>
                      <CardDescription>
                        {translateReview
                          ? 'GPT translated the transcript to English. Edit here (autosaves 1.5s after you stop typing), then click "Extract Pradip\u2019s Analysis".'
                          : 'Locked — this is the English text used for the extraction step.'}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <Textarea
                        value={translatedBuffer}
                        onChange={(e) => {
                          if (!translatedEditable) return;
                          translatedBufferDirty.current = true;
                          setTranslatedBuffer(e.target.value);
                        }}
                        rows={20}
                        readOnly={!translatedEditable}
                        placeholder="Translation will appear here once GPT finishes."
                        className="font-mono text-sm"
                      />
                      {translateReview && (
                        <p className="text-xs text-muted-foreground">
                          Need to fix the source instead? Use <b>Edit raw transcript</b> at the top of the page.
                        </p>
                      )}
                    </CardContent>
                  </Card>
                ) : (
                  <Card>
                    <CardContent className="py-12 flex flex-col items-center justify-center gap-3 text-center text-sm text-muted-foreground">
                      <Languages className="w-8 h-8 text-cyan-300/60" />
                      <div>No translation yet.</div>
                      <div className="max-w-sm text-xs">
                        Switch to the <b>Transcript</b> tab, fix any mistakes, then click
                        {' '}<b>Translate to English</b> at the top of the page. The translation will appear here.
                      </div>
                    </CardContent>
                  </Card>
                )}
              </TabsContent>

              <TabsContent value="arrangement" className="mt-0">
                {arrangeBusy ? (
                  // Step loader — shown while GPT is extracting. The server
                  // only exposes a coarse 'arranging' status (no sub-
                  // progress), so we render a deterministic checklist with
                  // the active step animated. This makes the wait feel like
                  // progress instead of a blank screen.
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-violet-300" />
                        Extracting Pradip's analysis via ChatGPT…
                      </CardTitle>
                      <CardDescription>
                        Reorganising the translation into <code>stock\nanalysis\nstock\nanalysis…</code> form.
                        This usually takes 20–60 seconds depending on length.
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ArrangementStepLoader />
                    </CardContent>
                  </Card>
                ) : (arrangeReview || finished) ? (
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-violet-300" />
                        Pradip's analysis {arrangeReview && <span className="text-xs text-violet-300">(step 4 — review &amp; edit)</span>}
                      </CardTitle>
                      <CardDescription>
                        {arrangeReview
                          ? 'GPT re-ordered the translation into stock\\nanalysis\\nstock\\nanalysis… form. Edit here (autosaves 1.5s after you stop typing) and then click "Send to Bulk Rationale".'
                          : 'This is the exact text that was sent to Bulk Rationale.'}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <Textarea
                        value={arrangedBuffer}
                        onChange={(e) => {
                          if (!arrangeReview) return;
                          arrangedBufferDirty.current = true;
                          setArrangedBuffer(e.target.value);
                        }}
                        rows={20}
                        readOnly={!arrangeReview}
                        placeholder="Extraction will appear here once GPT finishes."
                        className="font-mono text-sm"
                      />
                      {arrangeReview && (
                        <p className="text-xs text-muted-foreground">
                          Need to fix the source instead? Switch to the <b>Translation</b> tab, or use <b>Edit raw transcript</b> at the top.
                        </p>
                      )}
                    </CardContent>
                  </Card>
                ) : (
                  // Pre-extract: nothing exists yet. Tell the user how
                  // to get here from the translation step.
                  <Card>
                    <CardContent className="py-12 flex flex-col items-center justify-center gap-3 text-center text-sm text-muted-foreground">
                      <Sparkles className="w-8 h-8 text-violet-300/60" />
                      <div>No extraction yet.</div>
                      <div className="max-w-sm text-xs">
                        Finish the <b>Translation</b> review, then click
                        {' '}<b>Extract Pradip's Analysis</b> at the top of the page. The result will appear here.
                      </div>
                    </CardContent>
                  </Card>
                )}
              </TabsContent>
            </Tabs>
          </div>
        ) : (
          /* Legacy mediaId / standalone mode — keeps the existing
             single-card layout (no arrangement step in this mode). */
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Live transcript
                {legacyListening && (
                  <span className="flex items-center gap-1 text-xs text-rose-300">
                    <Mic className="w-3 h-3 animate-pulse" /> mic listening
                  </span>
                )}
              </CardTitle>
              <CardDescription>
                Edit freely while listening — corrections are kept.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <Label>Microphone (audio input)</Label>
                  <Select value={selectedDeviceId} onValueChange={async (v: string) => {
                    setSelectedDeviceId(v);
                    if (legacyListening) stopLegacyRecognition();
                    await startLegacyVuMeter(v);
                  }}>
                    <SelectTrigger><SelectValue placeholder="Default" /></SelectTrigger>
                    <SelectContent>
                      {audioInputs.length === 0 && (
                        <SelectItem value="default">Allow mic access to populate</SelectItem>
                      )}
                      {audioInputs.map(d => (
                        <SelectItem key={d.deviceId} value={d.deviceId}>
                          {d.label || `Mic ${d.deviceId.slice(0, 6)}`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Recognition language</Label>
                  <Select value={legacyLanguage} onValueChange={(v: string) => setLegacyLanguage(v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="hi-IN">Hindi (India)</SelectItem>
                      <SelectItem value="en-IN">English (India)</SelectItem>
                      <SelectItem value="en-US">English (US)</SelectItem>
                      <SelectItem value="mr-IN">Marathi (India)</SelectItem>
                      <SelectItem value="gu-IN">Gujarati (India)</SelectItem>
                      <SelectItem value="ta-IN">Tamil (India)</SelectItem>
                      <SelectItem value="te-IN">Telugu (India)</SelectItem>
                      <SelectItem value="bn-IN">Bengali (India)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="flex items-center gap-3 flex-wrap">
                {!legacyListening ? (
                  <Button onClick={startLegacyRecognition} disabled={!speechSupported}>
                    <Mic className="w-4 h-4 mr-1" /> Start voice typing
                  </Button>
                ) : (
                  <Button onClick={stopLegacyRecognition} variant="destructive">
                    <MicOff className="w-4 h-4 mr-1" /> Stop
                  </Button>
                )}
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Volume2 className="w-3 h-3" />
                  <div className="w-32 h-1.5 bg-slate-700 rounded overflow-hidden">
                    <div
                      className="h-full bg-emerald-500 transition-all"
                      style={{ width: `${Math.min(100, legacyVu * 250)}%` }}
                    />
                  </div>
                  {legacyListening ? 'Listening…' : 'Idle'}
                </div>
              </div>

              <Textarea
                value={displayedTranscript}
                onChange={e => setLegacyTranscript(e.target.value)}
                rows={20}
                placeholder="Transcript will appear here as you speak or play the video."
                className="font-mono text-sm"
              />

              <p className="text-xs text-muted-foreground">
                Tip: pause the recognition before doing heavy edits; restart it to continue where you left off.
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* ===================================================================
          Video popup — playback in a modal so the long YouTube title and
          16:9 embed don't break the editor layout.
          =================================================================== */}
      {isJobMode && job?.videoUrl && (
        <Dialog open={videoOpen} onOpenChange={setVideoOpen}>
          {/* Bigger dialog (5xl) so the video has room to breathe. The
              viewport-relative iframe wrapper guards against both the
              dialog's max-h constraints squashing the embed AND the
              "iframe-loads-parent-page" bug — same fallback as the
              inline player when the URL isn't an embeddable YouTube one. */}
          <DialogContent className="max-w-5xl">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <PlayCircle className="w-5 h-5 text-primary" /> Reference video
              </DialogTitle>
            </DialogHeader>
            {(() => {
              const embedSrc = ytEmbedUrl(job.videoUrl, true);
              const wrapperCls = 'w-full h-[60vh] min-h-[360px] max-h-[640px] bg-black rounded-lg overflow-hidden';
              if (videoOpen && embedSrc) {
                return (
                  <div className={wrapperCls}>
                    <iframe
                      src={embedSrc}
                      title="video"
                      className="w-full h-full block"
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                      allowFullScreen
                    />
                  </div>
                );
              }
              if (videoOpen) {
                return (
                  <div className={`${wrapperCls} bg-slate-900 flex flex-col items-center justify-center gap-3 p-6 text-center`}>
                    <AlertTriangle className="w-8 h-8 text-amber-400" />
                    <div className="text-sm text-muted-foreground max-w-md">
                      This video can't be embedded inline. Open it in a new tab to watch.
                    </div>
                    <a
                      href={job.videoUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 text-sm text-primary hover:underline break-all"
                    >
                      <ExternalLink className="w-4 h-4" /> Open video
                    </a>
                  </div>
                );
              }
              return null;
            })()}
            <p className="text-xs text-muted-foreground break-all">{job.videoUrl}</p>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// ArrangementStepLoader
//
// Visual progress indicator shown while ChatGPT is arranging the transcript.
// The server only exposes a coarse 'arranging' status (no streaming
// sub-progress), so we render a deterministic 4-step checklist where the
// first two are marked done (we wouldn't be on this screen otherwise) and
// the third is shown as in-progress with a spinner. Makes the wait feel
// like real progress instead of a blank screen.
// ---------------------------------------------------------------------------

function TranslateStepLoader() {
  const steps = [
    { label: 'Transcribed audio', state: 'done' as const },
    { label: 'Reviewed transcript', state: 'done' as const },
    { label: 'Translating to English via GPT-4o', state: 'active' as const, hint: 'Translating while preserving stock names, numbers, and intent…' },
    { label: 'Review translation', state: 'pending' as const },
    { label: "Extract Pradip's analysis", state: 'pending' as const },
    { label: 'Send to Bulk Rationale', state: 'pending' as const },
  ];
  return (
    <ol className="space-y-3" role="status" aria-live="polite" aria-busy="true">
      {steps.map((s, i) => (
        <li key={i} className="flex items-start gap-3">
          <span className="mt-0.5 shrink-0">
            {s.state === 'done' && <CheckCircle2 className="w-5 h-5 text-emerald-400" />}
            {s.state === 'active' && <Loader2 className="w-5 h-5 text-cyan-300 animate-spin" />}
            {s.state === 'pending' && <Circle className="w-5 h-5 text-muted-foreground/40" />}
          </span>
          <div className="flex-1">
            <div className={
              s.state === 'pending'
                ? 'text-sm text-muted-foreground'
                : s.state === 'active'
                  ? 'text-sm text-foreground font-medium'
                  : 'text-sm text-muted-foreground line-through decoration-emerald-400/40'
            }>
              {i + 1}. {s.label}
            </div>
            {s.hint && (
              <div className="text-xs text-muted-foreground mt-0.5 font-mono">{s.hint}</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ArrangementStepLoader() {
  const steps = [
    { label: 'Transcribed audio', state: 'done' as const },
    { label: 'Reviewed transcript', state: 'done' as const },
    { label: 'Translated to English', state: 'done' as const },
    { label: 'Reviewed translation', state: 'done' as const },
    { label: "Extracting Pradip's analysis via ChatGPT", state: 'active' as const, hint: 'Reorganising into stock\\nanalysis blocks…' },
    { label: 'Review extraction', state: 'pending' as const },
  ];
  return (
    <ol className="space-y-3" role="status" aria-live="polite" aria-busy="true">
      {steps.map((s, i) => (
        <li key={i} className="flex items-start gap-3">
          <span className="mt-0.5 shrink-0">
            {s.state === 'done' && <CheckCircle2 className="w-5 h-5 text-emerald-400" />}
            {s.state === 'active' && <Loader2 className="w-5 h-5 text-sky-300 animate-spin" />}
            {s.state === 'pending' && <Circle className="w-5 h-5 text-muted-foreground/40" />}
          </span>
          <div className="flex-1">
            <div className={
              s.state === 'pending'
                ? 'text-sm text-muted-foreground'
                : s.state === 'active'
                  ? 'text-sm text-foreground font-medium'
                  : 'text-sm text-muted-foreground line-through decoration-emerald-400/40'
            }>
              {i + 1}. {s.label}
            </div>
            {s.hint && (
              <div className="text-xs text-muted-foreground mt-0.5 font-mono">{s.hint}</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// UploadAudioFallback
//
// Shown inside the "Transcription failed" alert. Lets the user attach a local
// audio file (mp3 / m4a / wav / etc.) which the server will convert via
// ffmpeg and run through Vosk — bypassing the failed YouTube downloader.
// ---------------------------------------------------------------------------

interface UploadAudioFallbackProps {
  jobId: string;
  token: string | undefined;
  uploading: boolean;
  setUploading: (b: boolean) => void;
  onUploaded: (job: VoiceJob) => void;
}

function UploadAudioFallback({
  jobId, token, uploading, setUploading, onUploaded,
}: UploadAudioFallbackProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handlePick = () => {
    if (uploading) return;
    inputRef.current?.click();
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    const MAX_BYTES = 500 * 1024 * 1024;
    if (file.size > MAX_BYTES) {
      toast.error(`File too large (${(file.size / 1024 / 1024).toFixed(0)} MB). Max 500 MB.`);
      return;
    }

    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(API_ENDPOINTS.voiceTyping.uploadAudio(jobId), {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        toast.error(j.error || `Upload failed (HTTP ${r.status})`);
        return;
      }
      toast.success('Audio uploaded — transcription restarting on the server.');
      if (j.job) onUploaded(j.job);
    } catch (err: any) {
      toast.error(err?.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mt-3 flex items-center gap-2 flex-wrap">
      <input
        ref={inputRef}
        type="file"
        accept=".mp3,.m4a,.wav,.ogg,.opus,.webm,.mp4,.aac,.flac,.wma,audio/*"
        className="hidden"
        onChange={handleFile}
      />
      <Button
        size="sm"
        variant="secondary"
        onClick={handlePick}
        disabled={uploading}
      >
        {uploading ? (
          <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> Uploading…</>
        ) : (
          <><Upload className="w-3 h-3 mr-1" /> Upload audio file instead</>
        )}
      </Button>
      <span className="text-xs text-muted-foreground">
        Skip the YouTube download and run Vosk on a file from your computer.
        MP3 / M4A / WAV / OGG, up to 500 MB.
      </span>
    </div>
  );
}
