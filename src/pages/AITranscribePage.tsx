import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '@/lib/api-config';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import {
  Sparkles, Save, ArrowLeft, Loader2, Upload, Info, Copy, Download,
  CheckCircle2, AlertTriangle, Mic2, Circle, XCircle, ListChecks, Trash2,
  Languages, Filter, Send, RefreshCw, RotateCcw, Plus, ArrowRight, ExternalLink,
  Calendar, Clock, Youtube, Facebook, Instagram, MessageCircle, Globe,
  Send as TgIcon,
} from 'lucide-react';

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
  transcribe_method?: string | null;
  transcript_text?: string | null;
}

interface JobStep {
  step_number: number;
  step_name: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  message?: string | null;
  output_files?: string[];
  started_at?: string | null;
  ended_at?: string | null;
}

interface JobPayload {
  jobId: string;
  title: string;
  status: string;
  progress: number;
  currentStep: number;
  totalSteps: number;
  youtubeUrl?: string | null;
  channelId?: number | null;
  channelName?: string | null;
  date?: string | null;
  time?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  transcriptText?: string | null;
  translatedText?: string | null;
  extractedText?: string | null;
  bulkJobId?: string | null;
  transcriptFile?: string | null;
  steps: JobStep[];
}

interface ChannelOption {
  id: number;
  channel_name: string;
  platform: string;
}

interface JobListItem {
  jobId: string;
  title: string;
  status: string;
  progress?: number;
  currentStep?: number;
  youtubeUrl?: string | null;
  channelId?: number | null;
  channelName?: string | null;
  platform?: string | null;
  date?: string | null;
  time?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  bulkJobId?: string | null;
  bulkJobStatus?: string | null;
  bulkJobProgress?: number | null;
}

function platformIcon(platform?: string | null) {
  const p = (platform || '').toLowerCase();
  switch (p) {
    case 'youtube':   return <Youtube className="w-4 h-4 text-red-500" />;
    case 'facebook':  return <Facebook className="w-4 h-4 text-blue-500" />;
    case 'instagram': return <Instagram className="w-4 h-4 text-pink-500" />;
    case 'telegram':  return <TgIcon className="w-4 h-4 text-sky-500" />;
    case 'whatsapp':  return <MessageCircle className="w-4 h-4 text-emerald-500" />;
    default:          return <Globe className="w-4 h-4 text-slate-400" />;
  }
}

interface Props {
  onNavigate: (page: string, id?: string | number | null) => void;
  /** When provided, the page is bound to a Media Presence row and saving the
   *  transcript triggers the downstream rationale job. */
  mediaId?: number;
  /** When provided, the page shows a previously-created standalone AI
   *  Transcribe job (used when navigating from the dashboard). */
  selectedJobId?: string;
}

const LANGUAGES = [
  { value: 'hi', label: 'Hindi' },
  { value: 'en', label: 'English' },
  { value: 'mr', label: 'Marathi' },
  { value: 'gu', label: 'Gujarati' },
  { value: 'ta', label: 'Tamil' },
  { value: 'te', label: 'Telugu' },
  { value: 'bn', label: 'Bengali' },
];

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  processing: { label: 'Running', className: 'bg-blue-500/20 text-blue-300 border-blue-500/40' },
  translating: { label: 'Translating', className: 'bg-blue-500/20 text-blue-300 border-blue-500/40' },
  extracting: { label: 'Extracting', className: 'bg-blue-500/20 text-blue-300 border-blue-500/40' },
  awaiting_review: { label: 'Review Transcript', className: 'bg-amber-500/20 text-amber-300 border-amber-500/40' },
  awaiting_translate_review: { label: 'Review Translation', className: 'bg-amber-500/20 text-amber-300 border-amber-500/40' },
  awaiting_extract_review: { label: 'Review Extract', className: 'bg-amber-500/20 text-amber-300 border-amber-500/40' },
  bulk_started: { label: 'Sent to Bulk', className: 'bg-purple-500/20 text-purple-300 border-purple-500/40' },
  completed: { label: 'Completed', className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' },
  failed: { label: 'Failed', className: 'bg-red-500/20 text-red-300 border-red-500/40' },
  pending: { label: 'Pending', className: 'bg-slate-500/20 text-slate-300 border-slate-500/40' },
};

function StepIcon({ status }: { status: JobStep['status'] }) {
  if (status === 'success') return <CheckCircle2 className="w-5 h-5 text-emerald-400" />;
  if (status === 'failed') return <XCircle className="w-5 h-5 text-red-400" />;
  if (status === 'running') return <Loader2 className="w-5 h-5 animate-spin text-blue-400" />;
  return <Circle className="w-5 h-5 text-muted-foreground/60" />;
}

function StatusBadge({ status }: { status: string }) {
  const conf = STATUS_BADGE[status] || { label: status, className: 'bg-slate-500/20 text-slate-300 border-slate-500/40' };
  return <Badge variant="outline" className={conf.className}>{conf.label}</Badge>;
}

export default function AITranscribePage({ onNavigate, mediaId, selectedJobId }: Props) {
  const { token } = useAuth();
  const mode: 'media-presence' | 'job-view' | 'jobs-list' =
    mediaId ? 'media-presence' : selectedJobId ? 'job-view' : 'jobs-list';

  // ---------- Shared state ----------
  const [language, setLanguage] = useState('hi');
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>('');

  // ---------- New-job state (used inside the New dialog) ----------
  const [standaloneUrl, setStandaloneUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newChannelId, setNewChannelId] = useState<string>('');
  const [newDate, setNewDate] = useState<string>('');
  const [newTime, setNewTime] = useState<string>('');
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [fetchingMeta, setFetchingMeta] = useState(false);
  const [showNew, setShowNew] = useState(false);

  // ---------- Jobs-list state ----------
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [jobsLoading, setJobsLoading] = useState(mode === 'jobs-list');

  // ---------- Job-view state ----------
  const [job, setJob] = useState<JobPayload | null>(null);
  const [jobLoading, setJobLoading] = useState(!!selectedJobId);
  const [editTranscript, setEditTranscript] = useState('');
  const [editTranslated, setEditTranslated] = useState('');
  const [editExtracted, setEditExtracted] = useState('');
  const [savingStage, setSavingStage] = useState<'' | 'transcript' | 'translated' | 'extracted' | 'bulk'>('');
  const [selectedRestartStep, setSelectedRestartStep] = useState<number>(1);
  const [isRestarting, setIsRestarting] = useState(false);
  // Track the last status we hydrated edit-fields from so editor changes
  // are NOT clobbered by 3-second polls.
  const lastHydratedStatusRef = useRef<string>('');

  // ---------- Media-presence state ----------
  const [item, setItem] = useState<MediaPresenceItem | null>(null);
  const [transcript, setTranscript] = useState('');
  const [mpRunning, setMpRunning] = useState(false);
  const [mpStatusMsg, setMpStatusMsg] = useState('');
  const [mpLoading, setMpLoading] = useState(!!mediaId);
  const [mpSaving, setMpSaving] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };
  // Guards the one-shot auto-start when arriving from Media Presence with a
  // brand-new entry. Without this, every poll tick that sees a still-pending
  // entry would re-trigger startMpTranscribe.
  const autoStartTriedRef = useRef(false);

  // ===========================================================================
  // Load channels for the new-job form
  // ===========================================================================

  useEffect(() => {
    if (mode !== 'jobs-list') return;
    (async () => {
      try {
        const r = await fetch(API_ENDPOINTS.channels.getAll, {
          headers: getAuthHeaders(token || undefined),
        });
        const j = await r.json();
        if (r.ok) setChannels(Array.isArray(j) ? j : (j.channels || []));
      } catch { /* non-fatal */ }
    })();
    // Default the date to today.
    if (!newDate) {
      const d = new Date();
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      setNewDate(`${yyyy}-${mm}-${dd}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // ===========================================================================
  // Jobs-list mode — load + poll the table of all AI Transcribe jobs
  // ===========================================================================

  const fetchJobs = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.list, {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to load jobs');
      setJobs(j.jobs || []);
    } catch (e: any) {
      console.warn('AI Transcribe list error', e);
      toast.error(e.message || 'Could not load AI Transcribe jobs');
    } finally {
      setJobsLoading(false);
    }
  };

  useEffect(() => {
    if (mode !== 'jobs-list') return;
    fetchJobs();
    const id = window.setInterval(fetchJobs, 6000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const resetNewJobForm = () => {
    setStandaloneUrl(''); setNewTitle(''); setNewChannelId('');
    setNewTime(''); setAudioFile(null); setErrorMsg('');
    const d = new Date();
    setNewDate(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`);
  };

  const deleteJobFromList = async (jobId: string) => {
    if (!confirm(`Delete AI Transcribe job ${jobId}? Files and history are removed.`)) return;
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.deleteJob(jobId), {
        method: 'DELETE',
        headers: getAuthHeaders(token || undefined),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || 'Delete failed');
      }
      toast.success('Job deleted');
      setJobs(prev => prev.filter(p => p.jobId !== jobId));
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  // ===========================================================================
  // YouTube metadata auto-fetch
  // ===========================================================================

  const handleFetchMetadata = async () => {
    const url = standaloneUrl.trim();
    if (!url) return;
    setFetchingMeta(true);
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.fetchMetadata, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ youtubeUrl: url }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not fetch video metadata');
      const d = j.data || {};
      if (d.title && !newTitle) setNewTitle(d.title);
      if (d.uploadDate) setNewDate(d.uploadDate);
      if (d.uploadTime) setNewTime(String(d.uploadTime).slice(0, 5));
      // Try to match the channel name to an existing channel option.
      if (d.channelName && !newChannelId) {
        const match = channels.find(c =>
          c.channel_name.toLowerCase() === String(d.channelName).toLowerCase(),
        );
        if (match) setNewChannelId(String(match.id));
      }
      toast.success('Filled in video details');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setFetchingMeta(false);
    }
  };

  // ===========================================================================
  // Job-view mode (standalone)
  // ===========================================================================

  const fetchJob = async (jobId: string) => {
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.getJob(jobId), {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to load job');
      setJob(j);
      setErrorMsg('');

      // Hydrate the editable buffers ONLY when the status transitions into a
      // new review stage. Otherwise we'd clobber user edits every 3 seconds.
      const last = lastHydratedStatusRef.current;
      if (j.status !== last) {
        if (j.status === 'awaiting_review' && j.transcriptText != null) {
          setEditTranscript(j.transcriptText);
        }
        if (j.status === 'awaiting_translate_review' && j.translatedText != null) {
          setEditTranslated(j.translatedText);
        }
        if (j.status === 'awaiting_extract_review' && j.extractedText != null) {
          setEditExtracted(j.extractedText);
        }
        lastHydratedStatusRef.current = j.status;
      }

      // Stop polling once terminal — bulk_started or failed.
      if (j.status === 'bulk_started' || j.status === 'failed' || j.status === 'completed') {
        stopPoll();
        if (j.status === 'failed') {
          const failedStep = (j.steps || []).find((s: JobStep) => s.status === 'failed');
          setErrorMsg(failedStep?.message || 'Pipeline failed.');
        }
      }
    } catch (e: any) {
      console.warn('job poll error', e);
      setErrorMsg(e.message || 'Failed to load job');
    } finally {
      setJobLoading(false);
    }
  };

  useEffect(() => {
    if (mode !== 'job-view' || !selectedJobId) return;
    fetchJob(selectedJobId);
    stopPoll();
    pollRef.current = setInterval(() => fetchJob(selectedJobId), 3000);
    return () => stopPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedJobId, mode]);

  // ---------- Save & Next handlers ----------

  const saveTranscriptAndTranslate = async () => {
    if (!job) return;
    if (!editTranscript.trim()) { toast.error('Transcript is empty.'); return; }
    setSavingStage('transcript');
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.saveTranscriptAndTranslate(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ transcriptText: editTranscript }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Save & translate failed');
      toast.success('Translating — give it a minute.');
      // Resume polling so the new status pours in.
      stopPoll();
      pollRef.current = setInterval(() => fetchJob(job.jobId), 3000);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSavingStage('');
    }
  };

  const saveTranslationAndExtract = async () => {
    if (!job) return;
    if (!editTranslated.trim()) { toast.error('Translated text is empty.'); return; }
    setSavingStage('translated');
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.saveTranslationAndExtract(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ translatedText: editTranslated }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Save & extract failed');
      toast.success('Extracting — give it a minute.');
      stopPoll();
      pollRef.current = setInterval(() => fetchJob(job.jobId), 3000);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSavingStage('');
    }
  };

  const saveExtractedOnly = async () => {
    if (!job) return;
    if (!editExtracted.trim()) { toast.error('Extracted text is empty.'); return; }
    setSavingStage('extracted');
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.saveExtracted(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ extractedText: editExtracted }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Save failed');
      toast.success('Saved');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSavingStage('');
    }
  };

  const sendToBulk = async () => {
    if (!job) return;
    if (!editExtracted.trim()) { toast.error('Extracted text is empty.'); return; }
    if (!job.channelId || !job.date) {
      toast.error('Channel and date are required to send to Bulk Rationale.');
      return;
    }
    if (!confirm('Spawn a Bulk Rationale child job from this extracted analysis?')) return;
    setSavingStage('bulk');
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.sendToBulk(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ extractedText: editExtracted }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Send failed');
      toast.success('Bulk Rationale child job spawned.');
      stopPoll();
      pollRef.current = setInterval(() => fetchJob(job.jobId), 3000);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSavingStage('');
    }
  };

  const handleRestartStep = async (stepNumber: number) => {
    if (!job) return;
    if (!confirm(`Re-run from Step ${stepNumber}? Steps after this will be reset.`)) return;
    setIsRestarting(true);
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.restartStep(job.jobId, stepNumber), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to restart step');
      toast.success(`Restarting from Step ${stepNumber}`);
      // Force a re-hydration when status next changes.
      lastHydratedStatusRef.current = '';
      stopPoll();
      pollRef.current = setInterval(() => fetchJob(job.jobId), 3000);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setIsRestarting(false);
    }
  };

  // ===========================================================================
  // Media-presence mode (existing — unchanged)
  // ===========================================================================

  const loadItem = async () => {
    if (!mediaId) return;
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.get(mediaId), {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Load failed');
      setItem(j.item);
      setTranscript(j.item.transcript_text || '');
      if (j.item.transcribe_status === 'completed') {
        setMpRunning(false); stopPoll();
        setMpStatusMsg('Completed');
      } else if (j.item.transcribe_status === 'failed') {
        setMpRunning(false); stopPoll();
        setErrorMsg('Transcription failed. Check the entry notes for details.');
      } else if (j.item.transcribe_status === 'started') {
        setMpRunning(true);
        setMpStatusMsg('Transcribing… this can take 1–3 minutes for typical clips.');
        if (!pollRef.current) pollRef.current = setInterval(loadItem, 5000);
      }
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setMpLoading(false);
    }
  };

  useEffect(() => {
    if (mode !== 'media-presence') return;
    autoStartTriedRef.current = false;
    loadItem();
    return () => stopPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaId, mode]);

  // Auto-start AI transcription as soon as we arrive from Media Presence
  // on a fresh "pending" entry that has a YouTube URL. The Media Presence
  // "AI" button used to just navigate here and leave the user staring at
  // a manual Start button — now the job kicks off on its own.
  useEffect(() => {
    if (mode !== 'media-presence') return;
    if (autoStartTriedRef.current) return;
    if (!item) return;
    if (item.transcribe_status !== 'pending') return;
    if (!item.video_url) return;
    if (mpRunning) return;
    autoStartTriedRef.current = true;
    startMpTranscribe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, mode]);

  const startMpTranscribe = async () => {
    if (!mediaId) return;
    setErrorMsg(''); setMpStatusMsg('Starting…'); setMpRunning(true); setTranscript('');
    try {
      let response: Response;
      if (audioFile) {
        const fd = new FormData();
        fd.append('audio', audioFile);
        fd.append('language_code', language);
        response = await fetch(API_ENDPOINTS.mediaPresence.startAiTranscribe(mediaId), {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        });
      } else {
        response = await fetch(API_ENDPOINTS.mediaPresence.startAiTranscribe(mediaId), {
          method: 'POST',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ language_code: language }),
        });
      }
      const j = await response.json();
      if (!response.ok) throw new Error(j.error || 'Failed to start AI transcription');
      toast.success('Transcription started — fetching audio.');
      stopPoll();
      pollRef.current = setInterval(loadItem, 5000);
    } catch (e: any) {
      setMpRunning(false);
      setErrorMsg(e.message);
      toast.error(e.message);
    }
  };

  const saveMpTranscript = async () => {
    if (!mediaId) return;
    if (!transcript.trim()) { toast.error('Transcript is empty.'); return; }
    setMpSaving(true);
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.saveTranscript(mediaId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ transcript_text: transcript, transcribe_method: 'ai_transcribe' }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Save failed');
      toast.success('Transcript saved — rationale job started.');
      onNavigate('media-presence');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setMpSaving(false);
    }
  };

  // ===========================================================================
  // New-job mode — submit form, then navigate to job view
  // ===========================================================================

  const submitNewJob = async () => {
    setErrorMsg('');
    if (!standaloneUrl.trim() && !audioFile) {
      setErrorMsg('Provide a YouTube URL or upload an audio file.');
      return;
    }
    setSubmitting(true);
    try {
      let response: Response;
      const commonFields = {
        language_code: language,
        title: newTitle.trim() || undefined,
        channel_id: newChannelId || undefined,
        date: newDate || undefined,
        time: newTime ? `${newTime}:00` : undefined,
      };
      if (audioFile) {
        const fd = new FormData();
        fd.append('audio', audioFile);
        fd.append('language_code', language);
        if (commonFields.title) fd.append('title', commonFields.title);
        if (commonFields.channel_id) fd.append('channel_id', commonFields.channel_id);
        if (commonFields.date) fd.append('date', commonFields.date);
        if (commonFields.time) fd.append('time', commonFields.time);
        response = await fetch(API_ENDPOINTS.aiTranscribe.createJob, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        });
      } else {
        response = await fetch(API_ENDPOINTS.aiTranscribe.createJob, {
          method: 'POST',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({
            youtube_url: standaloneUrl.trim(),
            ...commonFields,
          }),
        });
      }
      const j = await response.json();
      if (!response.ok) throw new Error(j.error || 'Failed to start transcription');
      toast.success('Transcription job started');
      setShowNew(false);
      resetNewJobForm();
      onNavigate('ai-transcribe', j.jobId);
    } catch (e: any) {
      setErrorMsg(e.message);
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ===========================================================================
  // Common helpers
  // ===========================================================================

  const copyToClipboard = async (text: string) => {
    if (!text.trim()) { toast.error('Nothing to copy yet'); return; }
    try { await navigator.clipboard.writeText(text); toast.success('Copied'); }
    catch { toast.error('Copy failed'); }
  };

  const downloadText = (text: string, filename: string) => {
    if (!text.trim()) { toast.error('Nothing to download yet'); return; }
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  const deleteJob = async () => {
    if (!job) return;
    if (!confirm(`Delete job ${job.jobId}? This removes its files and history.`)) return;
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.deleteJob(job.jobId), {
        method: 'DELETE',
        headers: getAuthHeaders(token || undefined),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || 'Delete failed');
      }
      toast.success('Job deleted');
      onNavigate('ai-transcribe');
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  // ===========================================================================
  // Render
  // ===========================================================================

  if (mode === 'media-presence' && mpLoading) {
    return (
      <div className="p-8 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading…
      </div>
    );
  }
  if (mode === 'job-view' && jobLoading) {
    return (
      <div className="p-8 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading job…
      </div>
    );
  }

  // ===========================================================================
  // Reusable: the new-job form that lives inside the dialog popup AND is
  // referenced from media-presence mode (audio upload still needed there).
  // ===========================================================================
  const renderNewJobFormBody = () => (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>YouTube URL</Label>
        <div className="flex gap-2">
          <Input
            placeholder="https://www.youtube.com/watch?v=…"
            value={standaloneUrl}
            onChange={e => setStandaloneUrl(e.target.value)}
            onBlur={() => { if (standaloneUrl.trim() && !audioFile) handleFetchMetadata(); }}
            disabled={submitting}
          />
          <Button
            type="button"
            variant="outline"
            onClick={handleFetchMetadata}
            disabled={submitting || fetchingMeta || !standaloneUrl.trim()}
          >
            {fetchingMeta ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5 sm:col-span-2">
          <Label>Title</Label>
          <Input placeholder="Auto-filled from the YouTube video"
            value={newTitle} onChange={e => setNewTitle(e.target.value)} disabled={submitting} />
        </div>
        <div className="space-y-1.5">
          <Label>Channel</Label>
          <Select value={newChannelId} onValueChange={setNewChannelId} disabled={submitting}>
            <SelectTrigger><SelectValue placeholder="Select channel" /></SelectTrigger>
            <SelectContent>
              {channels.map(c => (
                <SelectItem key={c.id} value={String(c.id)}>{c.platform} · {c.channel_name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Audio language</Label>
          <Select value={language} onValueChange={setLanguage} disabled={submitting}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {LANGUAGES.map(l => (
                <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Date</Label>
          <Input type="date" value={newDate} onChange={e => setNewDate(e.target.value)} disabled={submitting} />
        </div>
        <div className="space-y-1.5">
          <Label>Time</Label>
          <Input type="time" value={newTime} onChange={e => setNewTime(e.target.value)} disabled={submitting} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Or upload audio (mp3 / wav / m4a)</Label>
        <Input type="file" accept="audio/*"
          onChange={e => setAudioFile(e.target.files?.[0] || null)} disabled={submitting} />
        {audioFile && <p className="text-xs text-muted-foreground">{audioFile.name}</p>}
      </div>
      {errorMsg && (
        <Alert variant="destructive">
          <AlertTriangle className="w-4 h-4" />
          <AlertDescription className="break-words">{errorMsg}</AlertDescription>
        </Alert>
      )}
    </div>
  );

  // ---------- Jobs-list render ----------
  if (mode === 'jobs-list') {
    const sortedJobs = [...jobs].sort((a, b) =>
      (b.createdAt || '').localeCompare(a.createdAt || ''));

    return (
      <div className="p-6 space-y-4 max-w-[1400px] mx-auto">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/30 flex items-center justify-center">
              <Sparkles className="w-6 h-6 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-foreground">AI Transcribe</h1>
              <p className="text-sm text-muted-foreground mt-0.5">
                Transcribe → translate → extract Pradip's analysis → send to Bulk Rationale, with review at every step.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={fetchJobs}>
              <RefreshCw className="w-4 h-4 mr-1" /> Refresh
            </Button>
            <Button onClick={() => { resetNewJobForm(); setShowNew(true); }} data-tour="ait-new">
              <Plus className="w-4 h-4 mr-1" /> New AI Transcribe
            </Button>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Your transcriptions</CardTitle>
            <CardDescription>
              Each row is one job, walked through five reviewable steps:
              <b> 1. Download</b> → <b>2. Transcribe</b> → <b>3. Translate</b> →
              <b> 4. Extract Pradip's analysis</b> → <b>5. Send to Bulk Rationale</b>.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {jobsLoading ? (
              <div className="py-10 text-center text-muted-foreground">
                <Loader2 className="w-5 h-5 inline animate-spin mr-2" /> Loading…
              </div>
            ) : sortedJobs.length === 0 ? (
              <div className="py-10 text-center text-muted-foreground space-y-2">
                <p>No AI Transcribe jobs yet.</p>
                <Button variant="outline" onClick={() => { resetNewJobForm(); setShowNew(true); }}>
                  <Plus className="w-4 h-4 mr-1" /> Start your first transcription
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs uppercase text-muted-foreground border-b border-border">
                    <tr>
                      <th className="text-left py-2 pr-3">Source</th>
                      <th className="text-left py-2 pr-3">Channel</th>
                      <th className="text-left py-2 pr-3">Date / time</th>
                      <th className="text-left py-2 pr-3">Status</th>
                      <th className="text-left py-2 pr-3">Progress</th>
                      <th className="text-left py-2 pr-3">Bulk Rationale</th>
                      <th className="text-right py-2 pl-3"> </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedJobs.map(j => {
                      const open = () => onNavigate('ai-transcribe', j.jobId);
                      return (
                        <tr key={j.jobId} className="border-b border-border/50 hover:bg-accent/40">
                          <td className="py-2 pr-3 align-top">
                            {j.youtubeUrl ? (
                              <a href={j.youtubeUrl} target="_blank" rel="noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                                <ExternalLink className="w-3.5 h-3.5" /> YouTube
                              </a>
                            ) : (
                              <span className="text-xs text-muted-foreground">Audio upload</span>
                            )}
                            <div className="text-[10px] font-mono text-muted-foreground mt-0.5">{j.jobId}</div>
                          </td>
                          <td className="py-2 pr-3 align-top">
                            <div className="flex items-center gap-2">
                              {platformIcon(j.platform)}
                              <div className="min-w-0">
                                <div className="text-foreground truncate max-w-[160px]" title={j.channelName || ''}>
                                  {j.channelName || '—'}
                                </div>
                                {j.platform && (
                                  <div className="text-[10px] uppercase text-muted-foreground tracking-wide">{j.platform}</div>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="py-2 pr-3 align-top whitespace-nowrap">
                            <div className="flex items-center gap-1 text-foreground">
                              <Calendar className="w-3 h-3 text-muted-foreground" />{j.date || '—'}
                            </div>
                            {j.time && (
                              <div className="flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                                <Clock className="w-3 h-3" />{String(j.time).slice(0, 5)}
                              </div>
                            )}
                          </td>
                          <td className="py-2 pr-3 align-top">
                            <div className="flex items-center gap-2 flex-wrap">
                              <StatusBadge status={j.status} />
                              <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={open}>
                                Open <ArrowRight className="w-3 h-3 ml-1" />
                              </Button>
                            </div>
                          </td>
                          <td className="py-2 pr-3 align-top text-muted-foreground whitespace-nowrap">
                            {(j.progress ?? 0)}%
                          </td>
                          <td className="py-2 pr-3 align-top">
                            {j.bulkJobId ? (
                              <button
                                className="font-mono text-xs text-primary hover:underline inline-flex items-center gap-1"
                                onClick={() => onNavigate('bulk-rationale', j.bulkJobId!)}
                                title="Open Bulk Rationale job">
                                {j.bulkJobId}<ExternalLink className="w-3 h-3" />
                              </button>
                            ) : <span className="text-xs text-muted-foreground">—</span>}
                          </td>
                          <td className="py-2 pl-3 align-top text-right">
                            <Button variant="ghost" size="sm"
                              onClick={() => deleteJobFromList(j.jobId)} title="Delete job">
                              <Trash2 className="w-4 h-4 text-red-400" />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* New-job dialog */}
        <Dialog open={showNew} onOpenChange={(o: boolean) => { setShowNew(o); if (!o) resetNewJobForm(); }}>
          <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Mic2 className="w-4 h-4 text-primary" /> Start a new AI Transcribe
              </DialogTitle>
              <DialogDescription>
                Paste a YouTube URL — we'll auto-fill title, channel, date and time.
                Or upload an audio file directly.
              </DialogDescription>
            </DialogHeader>
            {renderNewJobFormBody()}
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowNew(false)} disabled={submitting}>Cancel</Button>
              <Button
                onClick={submitNewJob}
                disabled={submitting || (!standaloneUrl.trim() && !audioFile)}
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Upload className="w-4 h-4 mr-1.5" />}
                {submitting ? 'Starting…' : 'Start AI Transcription'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  const headerSubtitle =
    mode === 'media-presence' && item
      ? <>For: <b>{item.platform.toUpperCase()}</b> · {item.channel_name || '—'} · {item.event_date} {item.event_time}</>
      : mode === 'job-view' && job
      ? <>{job.title}</>
      : <>AI Transcribe</>;

  // Helpers used by the job-view stage cards.
  const isStageBusy = (s: string) =>
    job?.status === s || savingStage !== '';

  return (
    <div className="p-6 space-y-5 max-w-[1400px] mx-auto">
      {/* ---------- Header ---------- */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/30 flex items-center justify-center">
            <Sparkles className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-foreground">AI Transcribe</h1>
            <p className="text-sm text-muted-foreground mt-0.5">{headerSubtitle}</p>
            {mode === 'job-view' && job && (
              <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                <span className="font-mono">{job.jobId}</span>
                <span>·</span>
                <StatusBadge status={job.status} />
                {job.channelName && (<><span>·</span><span>{job.channelName}</span></>)}
                {job.date && (<><span>·</span><span>{job.date}{job.time ? ` ${String(job.time).slice(0, 5)}` : ''}</span></>)}
                {job.bulkJobId && (
                  <>
                    <span>·</span>
                    <button
                      onClick={() => onNavigate('bulk-rationale', job.bulkJobId)}
                      className="text-purple-300 hover:underline font-mono"
                    >
                      → {job.bulkJobId}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          {mode === 'media-presence' && (
            <Button variant="outline" onClick={() => onNavigate('media-presence')}>
              <ArrowLeft className="w-4 h-4 mr-1" /> Back to list
            </Button>
          )}
          {mode === 'job-view' && (
            <>
              <Button variant="outline" onClick={() => onNavigate('dashboard')}>
                <ArrowLeft className="w-4 h-4 mr-1" /> Back to Jobs
              </Button>
              <Button variant="outline" onClick={() => onNavigate('ai-transcribe')}>
                <Sparkles className="w-4 h-4 mr-1" /> New Transcribe
              </Button>
              {job && (
                <Button variant="outline" className="border-red-500/40 text-red-300 hover:bg-red-500/10" onClick={deleteJob}>
                  <Trash2 className="w-4 h-4 mr-1" /> Delete
                </Button>
              )}
            </>
          )}
          {mode === 'media-presence' && (
            <Button onClick={saveMpTranscript} disabled={mpSaving || !transcript.trim()}>
              {mpSaving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}
              Save &amp; trigger rationale
            </Button>
          )}
        </div>
      </div>

      {/* ---------- Error ---------- */}
      {errorMsg && (
        <Alert variant="destructive">
          <AlertTriangle className="w-4 h-4" />
          <AlertTitle>Something went wrong</AlertTitle>
          <AlertDescription className="break-words">{errorMsg}</AlertDescription>
        </Alert>
      )}

      {/* ---------- Job-view (steps + per-stage editor) ---------- */}
      {mode === 'job-view' && job && (
        <>
          {/* Progress bar with restart-step selector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                Step {Math.min(job.currentStep, job.totalSteps)} of {job.totalSteps}
              </span>
              <span>{job.progress}%</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex-1"><Progress value={job.progress} className="h-2" /></div>
              <div className="flex items-center gap-2">
                <Select
                  value={selectedRestartStep.toString()}
                  onValueChange={(value) => setSelectedRestartStep(parseInt(value, 10))}
                  disabled={isRestarting}
                >
                  <SelectTrigger className="w-[110px] h-8 text-xs">
                    <SelectValue placeholder="Step" />
                  </SelectTrigger>
                  <SelectContent>
                    {(job.steps || []).map((step) => (
                      <SelectItem key={step.step_number} value={step.step_number.toString()}>
                        Step {step.step_number}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  onClick={() => handleRestartStep(selectedRestartStep)}
                  disabled={isRestarting}
                  variant="outline"
                  size="sm"
                  className="h-8 px-3"
                  title={`Re-run from step ${selectedRestartStep}`}
                >
                  {isRestarting
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <RotateCcw className="w-3.5 h-3.5" />}
                  <span className="ml-1.5 text-xs">Re-run</span>
                </Button>
              </div>
            </div>
          </div>

          {/* Steps + active editor grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Steps card */}
            <Card className="lg:col-span-1 border-border/60">
              <CardHeader className="border-b border-border/40 bg-card/40">
                <CardTitle className="text-base flex items-center gap-2">
                  <ListChecks className="w-4 h-4 text-primary" /> Pipeline Steps
                </CardTitle>
                <CardDescription>Live status updates every few seconds.</CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <ol className="space-y-3">
                  {job.steps.map((s) => (
                    <li
                      key={s.step_number}
                      className={`flex items-start gap-3 rounded-lg border p-3 ${
                        s.status === 'running'
                          ? 'border-blue-500/40 bg-blue-500/5'
                          : s.status === 'failed'
                          ? 'border-red-500/40 bg-red-500/5'
                          : s.status === 'success'
                          ? 'border-emerald-500/30 bg-emerald-500/5'
                          : 'border-border/50 bg-muted/10'
                      }`}
                    >
                      <StepIcon status={s.status} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm text-foreground">
                            <span className="text-muted-foreground mr-1">{s.step_number}.</span>
                            {s.step_name}
                          </div>
                          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                            {s.status}
                          </span>
                        </div>
                        {s.message && (
                          <div className={`text-xs mt-1 break-words ${
                            s.status === 'failed' ? 'text-red-300' : 'text-muted-foreground'
                          }`}>
                            {s.message}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
                {job.youtubeUrl && (
                  <div className="mt-4 text-xs text-muted-foreground border-t border-border/40 pt-3 break-all">
                    <span className="text-muted-foreground/70">Source: </span>
                    {job.youtubeUrl}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Active editor (transcript / translation / extracted) */}
            <Card className="lg:col-span-2 border-border/60">
              <CardHeader className="border-b border-border/40 bg-card/40">
                <CardTitle className="text-base flex items-center gap-2">
                  {job.status === 'awaiting_review' && <><Mic2 className="w-4 h-4 text-amber-400" /> Step 2 · Review Transcript</>}
                  {job.status === 'translating' && <><Languages className="w-4 h-4 text-blue-400 animate-pulse" /> Step 3 · Translating…</>}
                  {job.status === 'awaiting_translate_review' && <><Languages className="w-4 h-4 text-amber-400" /> Step 3 · Review Translation</>}
                  {job.status === 'extracting' && <><Filter className="w-4 h-4 text-blue-400 animate-pulse" /> Step 4 · Extracting…</>}
                  {job.status === 'awaiting_extract_review' && <><Filter className="w-4 h-4 text-amber-400" /> Step 4 · Review Extracted Analysis</>}
                  {job.status === 'bulk_started' && <><Send className="w-4 h-4 text-purple-300" /> Step 5 · Sent to Bulk Rationale</>}
                  {job.status === 'processing' && <><Loader2 className="w-4 h-4 animate-spin text-blue-400" /> Step 1-2 · Working…</>}
                  {(job.status === 'failed' || job.status === 'completed') && <>Transcript</>}
                </CardTitle>
                <CardDescription>
                  {job.status === 'processing' && 'Downloading and transcribing — this can take a few minutes.'}
                  {job.status === 'awaiting_review' && 'Edit any speaker labels or words AssemblyAI got wrong, then Save & Translate.'}
                  {job.status === 'translating' && 'GPT-4o is translating your edited transcript to English.'}
                  {job.status === 'awaiting_translate_review' && 'Review the English translation, then Save & Extract Pradip\'s analysis.'}
                  {job.status === 'extracting' && 'GPT-4o is filtering out everything except Pradip Halder\'s stock analysis.'}
                  {job.status === 'awaiting_extract_review' && 'Review the extracted stock-by-stock analysis, then send to Bulk Rationale.'}
                  {job.status === 'bulk_started' && 'A Bulk Rationale child job is running — open it from the link above.'}
                  {job.status === 'failed' && 'Pipeline failed before producing this output.'}
                  {job.status === 'completed' && 'Done.'}
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4 space-y-3">
                {/* Step 2 review */}
                {job.status === 'awaiting_review' && (
                  <>
                    <Textarea
                      value={editTranscript}
                      onChange={e => setEditTranscript(e.target.value)}
                      rows={20}
                      placeholder="Transcript will appear here when ready."
                      className="font-mono text-sm leading-relaxed"
                    />
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="text-xs text-muted-foreground">
                        {editTranscript.length.toLocaleString()} chars · {editTranscript.split(/\s+/).filter(Boolean).length.toLocaleString()} words
                      </div>
                      <div className="flex gap-2">
                        <Button variant="outline" onClick={() => copyToClipboard(editTranscript)}>
                          <Copy className="w-4 h-4 mr-1" /> Copy
                        </Button>
                        <Button variant="outline" onClick={() => downloadText(editTranscript, `transcript-${job.jobId}.txt`)}>
                          <Download className="w-4 h-4 mr-1" /> Download .txt
                        </Button>
                        <Button
                          onClick={saveTranscriptAndTranslate}
                          disabled={savingStage !== '' || !editTranscript.trim()}
                        >
                          {savingStage === 'transcript'
                            ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                            : <Languages className="w-4 h-4 mr-1.5" />}
                          Save &amp; Translate
                        </Button>
                      </div>
                    </div>
                  </>
                )}

                {/* Step 3 review */}
                {(job.status === 'translating' || job.status === 'awaiting_translate_review') && (
                  <>
                    <Textarea
                      value={job.status === 'translating' ? '' : editTranslated}
                      onChange={e => setEditTranslated(e.target.value)}
                      rows={20}
                      placeholder={job.status === 'translating' ? 'Translating with GPT-4o…' : 'English translation will appear here.'}
                      readOnly={job.status === 'translating'}
                      className="font-mono text-sm leading-relaxed"
                    />
                    {job.status === 'awaiting_translate_review' && (
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <div className="text-xs text-muted-foreground">
                          {editTranslated.length.toLocaleString()} chars
                        </div>
                        <div className="flex gap-2">
                          <Button variant="outline" onClick={() => copyToClipboard(editTranslated)}>
                            <Copy className="w-4 h-4 mr-1" /> Copy
                          </Button>
                          <Button variant="outline" onClick={() => downloadText(editTranslated, `translation-${job.jobId}.txt`)}>
                            <Download className="w-4 h-4 mr-1" /> Download .txt
                          </Button>
                          <Button
                            onClick={saveTranslationAndExtract}
                            disabled={isStageBusy('translating') || !editTranslated.trim()}
                          >
                            {savingStage === 'translated'
                              ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                              : <Filter className="w-4 h-4 mr-1.5" />}
                            Save &amp; Extract
                          </Button>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {/* Step 4 review */}
                {(job.status === 'extracting' || job.status === 'awaiting_extract_review') && (
                  <>
                    <Textarea
                      value={job.status === 'extracting' ? '' : editExtracted}
                      onChange={e => setEditExtracted(e.target.value)}
                      rows={20}
                      placeholder={job.status === 'extracting'
                        ? 'Extracting Pradip Halder\'s stock analysis…'
                        : 'Stock name on one line, analysis on the next, repeated.'}
                      readOnly={job.status === 'extracting'}
                      className="font-mono text-sm leading-relaxed"
                    />
                    {job.status === 'awaiting_extract_review' && (
                      <>
                        <div className="text-xs text-muted-foreground">
                          {editExtracted.length.toLocaleString()} chars · format: <code>STOCK_NAME</code> on one line, analysis on the next.
                        </div>
                        <div className="flex items-center justify-end gap-2 flex-wrap">
                          <Button variant="outline" onClick={() => copyToClipboard(editExtracted)}>
                            <Copy className="w-4 h-4 mr-1" /> Copy
                          </Button>
                          <Button variant="outline" onClick={() => downloadText(editExtracted, `extracted-${job.jobId}.txt`)}>
                            <Download className="w-4 h-4 mr-1" /> Download
                          </Button>
                          <Button
                            variant="outline"
                            onClick={saveExtractedOnly}
                            disabled={savingStage !== '' || !editExtracted.trim()}
                          >
                            {savingStage === 'extracted'
                              ? <Loader2 className="w-4 h-4 animate-spin mr-1" />
                              : <Save className="w-4 h-4 mr-1" />}
                            Save edits
                          </Button>
                          <Button
                            onClick={sendToBulk}
                            disabled={savingStage !== '' || !editExtracted.trim() || !job.channelId || !job.date}
                          >
                            {savingStage === 'bulk'
                              ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                              : <Send className="w-4 h-4 mr-1.5" />}
                            Send to Bulk Rationale
                          </Button>
                        </div>
                        {(!job.channelId || !job.date) && (
                          <Alert variant="destructive">
                            <AlertTriangle className="w-4 h-4" />
                            <AlertDescription>
                              This job is missing a channel or date — Bulk Rationale needs both. Re-create the job with those filled in to enable Send.
                            </AlertDescription>
                          </Alert>
                        )}
                      </>
                    )}
                  </>
                )}

                {/* bulk_started — show extracted text + link */}
                {job.status === 'bulk_started' && (
                  <>
                    <Textarea
                      value={job.extractedText || ''}
                      readOnly
                      rows={20}
                      className="font-mono text-sm leading-relaxed"
                    />
                    {job.bulkJobId && (
                      <Button onClick={() => onNavigate('bulk-rationale', job.bulkJobId)} className="w-full">
                        <Send className="w-4 h-4 mr-1.5" /> Open Bulk Rationale: {job.bulkJobId}
                      </Button>
                    )}
                  </>
                )}

                {/* processing / completed / failed fallback */}
                {(job.status === 'processing' || job.status === 'completed' || job.status === 'failed') && (
                  <Textarea
                    value={job.transcriptText || ''}
                    readOnly
                    rows={20}
                    placeholder={job.status === 'processing'
                      ? 'Working… transcript will appear here when ready.'
                      : 'No transcript available.'}
                    className="font-mono text-sm leading-relaxed"
                  />
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {/* ---------- Media-presence mode (existing flow — unchanged) ---------- */}
      {mode === 'media-presence' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-1 border-border/60">
            <CardHeader className="border-b border-border/40 bg-card/40">
              <CardTitle className="text-base flex items-center gap-2">
                <Mic2 className="w-4 h-4 text-primary" /> Source
              </CardTitle>
              <CardDescription>Use the entry's URL or upload audio.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div className="space-y-1.5">
                <Label>YouTube URL</Label>
                <Input value={item?.video_url || ''} readOnly placeholder="No video URL on this entry" />
              </div>
              <div className="space-y-1.5">
                <Label>Or upload audio (mp3 / wav / m4a)</Label>
                <Input
                  type="file" accept="audio/*"
                  onChange={e => setAudioFile(e.target.files?.[0] || null)}
                  disabled={mpRunning}
                />
                {audioFile && <p className="text-xs text-muted-foreground">{audioFile.name}</p>}
              </div>
              <div className="space-y-1.5">
                <Label>Audio language</Label>
                <Select value={language} onValueChange={setLanguage} disabled={mpRunning}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {LANGUAGES.map(l => (
                      <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={startMpTranscribe}
                disabled={mpRunning || (!item?.video_url && !audioFile)}
                className="w-full"
              >
                {mpRunning ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Upload className="w-4 h-4 mr-1.5" />}
                {mpRunning ? 'Transcribing…' : 'Start AI Transcription'}
              </Button>
              <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2 text-xs">
                <div className="flex items-center gap-2">
                  {mpRunning ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-400" />
                  ) : transcript ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <Info className="w-3.5 h-3.5 text-muted-foreground" />
                  )}
                  <span className="text-muted-foreground">
                    {mpStatusMsg || (transcript ? 'Done' : 'Idle')}
                  </span>
                </div>
                {item?.transcribe_method && (
                  <div className="text-[10px] text-muted-foreground mt-1">
                    via {item.transcribe_method.replace('_', ' ')}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="lg:col-span-2 border-border/60">
            <CardHeader className="border-b border-border/40 bg-card/40">
              <CardTitle className="text-base">Transcript</CardTitle>
              <CardDescription>
                Auto-fills when AssemblyAI finishes. Edit, then save to trigger your rationale.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4">
              <Textarea
                value={transcript}
                onChange={e => setTranscript(e.target.value)}
                rows={22}
                placeholder={mpRunning
                  ? 'Working… transcript will appear here when ready.'
                  : 'Click "Start AI Transcription" to fill this from the source audio.'}
                className="font-mono text-sm leading-relaxed"
              />
              {transcript && (
                <div className="mt-2 text-xs text-muted-foreground">
                  {transcript.length.toLocaleString()} characters
                  {' · '}
                  {transcript.split(/\s+/).filter(Boolean).length.toLocaleString()} words
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
