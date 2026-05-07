import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '@/lib/api-config';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { toast } from 'sonner';
import {
  Radio, Plus, Mic, Sparkles, Wifi, Wand2, Download, RefreshCw, Trash2,
  Play, Loader2, CheckCircle2, AlertTriangle, Clock, Youtube, Tv,
  Facebook, Instagram, Send, MessageCircle, Calendar, Search as SearchIcon,
  ExternalLink, Filter, X, History, Upload,
} from 'lucide-react';
import { getYouTubeEmbedUrl } from '@/lib/youtube-utils';

interface Channel { id: number; channel_name: string; platform: string; logoPath?: string; }

interface MediaPresenceItem {
  id: number;
  platform: string;
  channel_id: number | null;
  channel_name?: string | null;
  event_date: string;
  event_time: string;
  video_url: string | null;
  video_title: string | null;
  rationale_tool: 'bulk_rationale' | 'media_rationale';
  transcribe_method: 'voice_typing' | 'ai_transcribe' | 'auto' | 'live_transcribe' | null;
  transcribe_status: 'pending' | 'started' | 'completed' | 'failed';
  rationale_status: 'pending' | 'started' | 'done' | 'failed';
  rationale_job_id: string | null;
  linked_transcribe_job_id?: string | null;
  output_pdf_path: string | null;
  unsigned_pdf_path?: string | null;
  signed_pdf_path?: string | null;
  sign_status?: string | null;
  notes?: string | null;
}

interface Props {
  onNavigate: (page: string, mediaIdOrJobId?: string | number | null) => void;
}

const RATIONALE_TOOL_LABEL: Record<string, string> = {
  bulk_rationale: 'Bulk Rationale',
  media_rationale: 'Media Rationale (Auto)',
};

const TODAY = () => new Date().toISOString().split('T')[0];
const NOW_TIME = () => new Date().toTimeString().slice(0, 5);

export default function MediaPresencePage({ onNavigate }: Props) {
  const { token } = useAuth();
  const [items, setItems] = useState<MediaPresenceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [channels, setChannels] = useState<Channel[]>([]);

  // Create-entry dialog
  const [openCreate, setOpenCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [fetchingMeta, setFetchingMeta] = useState(false);
  const [fetchedVideoId, setFetchedVideoId] = useState<string | null>(null);
  const [fetchedChannelName, setFetchedChannelName] = useState<string | null>(null);
  const [channelMatchStatus, setChannelMatchStatus] = useState<'matched' | 'unmatched' | null>(null);
  const [form, setForm] = useState({
    platform: 'youtube',
    channel_id: '' as string,
    event_date: TODAY(),
    event_time: NOW_TIME(),
    video_url: '',
    video_title: '',
    rationale_tool: 'bulk_rationale' as MediaPresenceItem['rationale_tool'],
  });

  // Distinct platforms from the channels database (your "Manage Platforms" list)
  const platformOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of channels) {
      const raw = (c.platform || '').trim();
      if (!raw) continue;
      const key = raw.toLowerCase();
      if (!seen.has(key)) seen.set(key, raw);
    }
    const list = Array.from(seen.entries()).map(([value, label]) => ({ value, label }));
    // Always make YouTube the default if available; otherwise sort alphabetically
    list.sort((a, b) => {
      if (a.value === 'youtube') return -1;
      if (b.value === 'youtube') return 1;
      return a.label.localeCompare(b.label);
    });
    return list;
  }, [channels]);

  const isYoutubeSelected = (form.platform || '').trim().toLowerCase() === 'youtube';
  const platformIsValid = platformOptions.some(p => p.value === (form.platform || '').trim().toLowerCase());

  const resetForm = () => {
    const defaultPlatform = platformOptions.find(p => p.value === 'youtube')?.value
      || platformOptions[0]?.value
      || 'youtube';
    setForm({
      platform: defaultPlatform, channel_id: '', event_date: TODAY(), event_time: NOW_TIME(),
      video_url: '', video_title: '', rationale_tool: 'bulk_rationale',
    });
    setFetchedVideoId(null);
    setFetchedChannelName(null);
    setChannelMatchStatus(null);
  };

  const extractVideoId = (url: string): string | null => {
    if (!url) return null;
    if (/^[a-zA-Z0-9_-]{11}$/.test(url)) return url;
    const m = url.match(/(?:v=|youtu\.be\/|embed\/|shorts\/|live\/)([a-zA-Z0-9_-]{11})/);
    return m ? m[1] : null;
  };

  const fetchYoutubeMetadata = async () => {
    if (!isYoutubeSelected) {
      toast.error('Auto-fetch only works for YouTube. For other platforms, fill the fields manually.');
      return;
    }
    const url = form.video_url.trim();
    if (!url) { toast.error('Paste a YouTube video URL first.'); return; }
    if (!extractVideoId(url)) { toast.error('That does not look like a valid YouTube URL.'); return; }
    setFetchingMeta(true);
    try {
      const r = await fetch(API_ENDPOINTS.mediaRationale.fetchVideo, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ youtubeUrl: url }),
      });
      const j = await r.json();
      if (!r.ok || !j.success) throw new Error(j.error || 'Failed to fetch video metadata');
      const d = j.data;

      // Try to match a channel from the YouTube channels list (case-insensitive, trimmed)
      const ytChannels = channels.filter(c => (c.platform || '').trim().toLowerCase() === 'youtube');
      const match = ytChannels.find(
        c => c.channel_name.trim().toLowerCase() === (d.channelName || '').trim().toLowerCase(),
      );

      setForm(f => ({
        ...f,
        video_title: d.title || f.video_title,
        event_date: d.uploadDate || f.event_date,
        event_time: (d.uploadTime || '').slice(0, 5) || f.event_time,
        channel_id: match ? String(match.id) : '',
      }));
      setFetchedVideoId(d.videoId);
      setFetchedChannelName(d.channelName || null);
      setChannelMatchStatus(match ? 'matched' : 'unmatched');

      if (match) {
        toast.success(`Fetched — channel matched: ${match.channel_name}`);
      } else {
        toast.warning(
          `Fetched — but no channel in your database matches "${d.channelName}". Pick one manually or add it under Channels.`,
        );
      }
    } catch (e: any) {
      toast.error(e.message || 'Could not fetch video metadata');
    } finally {
      setFetchingMeta(false);
    }
  };

  // Track which row is currently triggering an action
  const [actingId, setActingId] = useState<number | null>(null);
  const [signingId, setSigningId] = useState<string | null>(null);

  // Open native file picker, POST the chosen PDF to the unified saved-rationale
  // upload-signed endpoint, then refresh MP rows so the row flips to "signed".
  const uploadSignedPdf = (rationaleJobId: string) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf';
    input.onchange = async (e: Event) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        setSigningId(rationaleJobId);
        const formData = new FormData();
        formData.append('file', file);
        formData.append('jobId', rationaleJobId);
        const res = await fetch('/api/v1/saved-rationale/upload-signed', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        });
        if (res.ok) {
          toast.success('Signed PDF uploaded — Media Presence updated');
          loadItems();
        } else {
          let detail = '';
          try {
            const d = await res.json();
            detail = d?.error || d?.message || '';
          } catch { /* ignore */ }
          toast.error(detail || `Upload failed (HTTP ${res.status})`);
        }
      } catch (err: any) {
        toast.error(err?.message || 'Failed to upload signed PDF');
      } finally {
        setSigningId(null);
      }
    };
    input.click();
  };
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // Video player popup state
  const [videoOpen, setVideoOpen] = useState(false);
  const [videoItem, setVideoItem] = useState<MediaPresenceItem | null>(null);

  // Strict YouTube-only embed. Returns '' for anything we can't safely
  // embed — callers must render a fallback (open in new tab) instead of an
  // iframe with `src=''`, which silently loads the parent document inside
  // the player. See src/lib/youtube-utils.ts for full rationale.
  const ytEmbedUrl = (url?: string | null) =>
    getYouTubeEmbedUrl(url, { autoplay: true });

  const platformIcon = (platform: string) => {
    const p = platform?.toLowerCase();
    if (p === 'youtube') return <Youtube className="w-4 h-4 text-red-500" />;
    if (p === 'tv') return <Tv className="w-4 h-4 text-blue-400" />;
    if (p === 'facebook') return <Facebook className="w-4 h-4 text-blue-500" />;
    if (p === 'instagram') return <Instagram className="w-4 h-4 text-pink-400" />;
    if (p === 'telegram') return <Send className="w-4 h-4 text-sky-400" />;
    if (p === 'whatsapp') return <MessageCircle className="w-4 h-4 text-green-400" />;
    return <Radio className="w-4 h-4 text-muted-foreground" />;
  };

  const loadItems = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.list, {
        headers: getAuthHeaders(token || undefined),
      });
      if (!r.ok) throw new Error('Failed to load entries');
      const j = await r.json();
      setItems(j.items || []);
    } catch (e: any) {
      toast.error(e.message || 'Failed to load Media Presence entries');
    } finally {
      setLoading(false);
    }
  };

  const loadChannels = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.channels.getAll, {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      setChannels(Array.isArray(j) ? j : (j.channels || j.items || []));
    } catch {
      // silent
    }
  };

  useEffect(() => {
    loadItems();
    loadChannels();
    // Poll list every 12s so running jobs reflect their latest state
    pollRef.current = setInterval(loadItems, 12000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // If channels load *after* the dialog is opened and the current platform
  // isn't in the managed list, snap to a valid one (YouTube > first available).
  useEffect(() => {
    if (!openCreate) return;
    if (platformOptions.length === 0) return;
    const current = (form.platform || '').trim().toLowerCase();
    if (platformOptions.some(p => p.value === current)) return;
    const fallback = platformOptions.find(p => p.value === 'youtube')?.value
      || platformOptions[0].value;
    setForm(f => ({ ...f, platform: fallback, channel_id: '' }));
  }, [openCreate, platformOptions]); // eslint-disable-line react-hooks/exhaustive-deps

  const createEntry = async () => {
    if (!form.platform || !form.event_date || !form.event_time || !form.rationale_tool) {
      toast.error('Platform, date, time and rationale tool are required.');
      return;
    }
    if (platformOptions.length === 0) {
      toast.error('No platforms available. Add a channel under Channel Logos first.');
      return;
    }
    if (!platformIsValid) {
      toast.error('Selected platform is not in your managed channels. Pick one from the list.');
      return;
    }
    if (form.rationale_tool === 'media_rationale' && !form.video_url.trim()) {
      toast.error('Video URL is required when using Media Rationale (Auto).');
      return;
    }
    setCreating(true);
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.create, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({
          ...form,
          channel_id: form.channel_id ? parseInt(form.channel_id, 10) : null,
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Create failed');
      toast.success('Media Presence entry added');
      setOpenCreate(false);
      resetForm();
      loadItems();
    } catch (e: any) {
      toast.error(e.message || 'Could not create entry');
    } finally {
      setCreating(false);
    }
  };

  const triggerAuto = async (item: MediaPresenceItem) => {
    setActingId(item.id);
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.startAuto(item.id), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Auto pipeline failed to start');
      toast.success('Auto pipeline started — watch the Rationale Status column.');
      loadItems();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setActingId(null);
    }
  };

  // Kick off a *real* server-side Voice Typing job (Vosk → review →
  // arrange → Bulk Rationale child) for this MP entry, then jump straight
  // to the live transcription editor. This replaces the old browser-mic
  // legacy view that the Voice button used to open.
  // Kick off the server-side Live Transcribe flow (AssemblyAI Realtime →
  // review → OpenAI extract → Bulk Rationale child) for this MP entry.
  // Mirrors startVoiceTyping but for the Live Transcribe tool.
  const startLiveTranscribe = async (item: MediaPresenceItem) => {
    if (!confirm('Start a server-side LIVE transcription for this entry? It captures the YouTube live stream and runs even after you close this tab.')) return;
    setActingId(item.id);
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.startLiveTranscribe(item.id), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to start Live Transcribe');
      toast.success('Live Transcribe job started — opening the editor.');
      if (j.item) {
        setItems(prev => prev.map(it => it.id === item.id ? j.item : it));
      } else {
        loadItems();
      }
      if (j.live_job_id) onNavigate('live-transcribe', j.live_job_id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setActingId(null);
    }
  };

  // Spawn a real standalone AI Transcribe job (`aitr-…`) from a Media
  // Presence row and jump straight into its 5-step review pipeline.
  // Mirrors startVoiceTyping / startLiveTranscribe — but for AI Transcribe,
  // there is no media-presence-specific endpoint, so we POST directly to
  // /ai-transcribe/create-job with the row's video URL + channel/date/time.
  const startAITranscribe = async (item: MediaPresenceItem) => {
    if (!item.video_url) {
      toast.error('This entry has no video URL — AI Transcribe needs a YouTube link.');
      return;
    }
    setActingId(item.id);
    try {
      const r = await fetch(API_ENDPOINTS.aiTranscribe.createJob, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({
          youtube_url: item.video_url,
          language_code: 'hi',
          title: item.video_title || undefined,
          channel_id: item.channel_id || undefined,
          date: item.event_date || undefined,
          time: item.event_time || undefined,
          // Tells the backend to flip this MP row's transcribe_status to
          // 'started' and stamp linked_transcribe_job_id so the table's
          // Transcribe pill becomes a clickable shortcut into the new job.
          media_presence_id: item.id,
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to start AI Transcribe');
      toast.success('AI Transcribe job started — opening the editor.');
      // Optimistic: reflect the new started state on the row immediately so
      // the user sees the pill flip even if the next list-poll is delayed.
      if (j.jobId) {
        setItems(prev => prev.map(it => it.id === item.id ? {
          ...it,
          transcribe_status: 'started',
          transcribe_method: 'ai_transcribe',
          linked_transcribe_job_id: j.jobId,
        } : it));
        onNavigate('ai-transcribe', j.jobId);
      }
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setActingId(null);
    }
  };

  const startVoiceTyping = async (item: MediaPresenceItem) => {
    if (!item.video_url) {
      toast.error('This entry has no video URL — Vosk has nothing to download.');
      return;
    }
    setActingId(item.id);
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.startVoiceTyping(item.id), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to start Voice Typing');
      toast.success('Voice Typing job started — opening the editor.');
      // Optimistically reflect the new transcribe status on the list.
      if (j.item) {
        setItems(prev => prev.map(it => it.id === item.id ? j.item : it));
      }
      // Navigate straight to the new voice job's live editor.
      if (j.voice_job_id) {
        onNavigate('voice-typing', j.voice_job_id);
      }
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setActingId(null);
    }
  };

  const deleteEntry = async (id: number) => {
    if (!confirm('Delete this Media Presence entry? Linked rationale jobs are not deleted.')) return;
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.delete(id), {
        method: 'DELETE',
        headers: getAuthHeaders(token || undefined),
      });
      if (!r.ok) throw new Error('Delete failed');
      toast.success('Entry removed');
      setItems(prev => prev.filter(i => i.id !== id));
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const downloadPdf = (item: MediaPresenceItem) => {
    if (!item.output_pdf_path) return;
    const url = API_ENDPOINTS.savedRationale.downloadPdf(item.output_pdf_path);
    window.open(url, '_blank');
  };

  const StatusPill = ({
    label, kind,
  }: { label: string; kind: 'pending' | 'started' | 'done' | 'completed' | 'failed' | string }) => {
    const map: Record<string, string> = {
      pending: 'bg-slate-700/40 text-slate-300 border-slate-600/60',
      started: 'bg-blue-600/15 text-blue-300 border-blue-500/40',
      transcribing: 'bg-blue-600/15 text-blue-300 border-blue-500/40',
      translating: 'bg-blue-600/15 text-blue-300 border-blue-500/40',
      extracting: 'bg-blue-600/15 text-blue-300 border-blue-500/40',
      review_transcript: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
      review_translation: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
      review_extract: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
      completed: 'bg-emerald-600/15 text-emerald-300 border-emerald-500/40',
      done: 'bg-emerald-600/15 text-emerald-300 border-emerald-500/40',
      signed: 'bg-emerald-600/15 text-emerald-300 border-emerald-500/40',
      failed: 'bg-rose-600/15 text-rose-300 border-rose-500/40',
    };
    const labelMap: Record<string, string> = {
      transcribing: 'Transcribing',
      translating: 'Translating',
      extracting: 'Extracting',
      review_transcript: 'Review Transcript',
      review_translation: 'Review Translation',
      review_extract: 'Review Extract',
    };
    const spinning = ['started', 'transcribing', 'translating', 'extracting'].includes(kind);
    const isReview = kind.startsWith('review_');
    const isDone = kind === 'completed' || kind === 'done' || kind === 'signed';
    const Icon = spinning ? Loader2
      : kind === 'failed' ? AlertTriangle
      : isDone ? CheckCircle2
      : isReview ? Clock
      : Clock;
    const displayLabel = labelMap[kind] || label;
    return (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${map[kind] || map.pending}`}>
        <Icon className={`w-3 h-3 ${spinning ? 'animate-spin' : ''}`} />
        <span className="capitalize">{displayLabel}</span>
      </span>
    );
  };

  const openVideo = (item: MediaPresenceItem) => {
    if (!item.video_url) return;
    setVideoItem(item);
    setVideoOpen(true);
  };

  // ── Filter state ──────────────────────────────────────────────────────────
  const [filterOpen, setFilterOpen] = useState(false);
  const [fSearch, setFSearch] = useState('');         // free-text search w/ history
  const [fChannelId, setFChannelId] = useState<string>('all'); // channel dropdown
  const [fDate, setFDate] = useState<string>('');
  const [fTime, setFTime] = useState<string>('');
  const [fTranscribe, setFTranscribe] = useState<string>('all');
  const [fRationale, setFRationale] = useState<string>('all');
  // Track logo URLs that failed to load so we can render the initials fallback.
  const [brokenLogos, setBrokenLogos] = useState<Set<string>>(new Set());

  // Search history (mirrors Dashboard pattern — last 5 distinct queries per user).
  const [searchHistory, setSearchHistory] = useState<{ query: string; last_used: string | null }[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const lastPersistedRef = useRef<string>('');

  const loadSearchHistory = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.mediaPresence.searchHistory, {
        headers: getAuthHeaders(token || undefined),
      });
      if (r.ok) {
        const j = await r.json();
        setSearchHistory(j.history || []);
      }
    } catch { /* silent */ }
  };
  const persistSearchQuery = async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed || lastPersistedRef.current === trimmed) return;
    lastPersistedRef.current = trimmed;
    try {
      await fetch(API_ENDPOINTS.mediaPresence.searchHistory, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ query: trimmed }),
      });
      loadSearchHistory();
    } catch { /* silent */ }
  };
  const removeHistoryItem = async (q: string) => {
    try {
      await fetch(`${API_ENDPOINTS.mediaPresence.searchHistory}?query=${encodeURIComponent(q)}`, {
        method: 'DELETE', headers: getAuthHeaders(token || undefined),
      });
      loadSearchHistory();
    } catch { /* silent */ }
  };
  const clearAllHistory = async () => {
    try {
      await fetch(API_ENDPOINTS.mediaPresence.searchHistory, {
        method: 'DELETE', headers: getAuthHeaders(token || undefined),
      });
      loadSearchHistory();
    } catch { /* silent */ }
  };
  useEffect(() => { loadSearchHistory(); /* eslint-disable-next-line */ }, []);

  const clearFilters = () => {
    setFSearch(''); setFChannelId('all'); setFDate(''); setFTime('');
    setFTranscribe('all'); setFRationale('all');
  };
  const activeFilterCount = [
    fSearch.trim(),
    fChannelId !== 'all' ? fChannelId : '',
    fDate, fTime,
    fTranscribe !== 'all' ? fTranscribe : '',
    fRationale !== 'all' ? fRationale : '',
  ].filter(Boolean).length;

  // Channels list for the dropdown — sorted by name. Shows ALL managed channels
  // (no platform narrowing) since the platform filter has been removed.
  const channelOptions = useMemo(() => {
    return channels.slice().sort((a, b) =>
      (a.channel_name || '').localeCompare(b.channel_name || '')
    );
  }, [channels]);

  // Lookup: channel_id → channel record (for logo & name)
  const channelById = useMemo(() => {
    const m = new Map<number, Channel>();
    channels.forEach(c => m.set(c.id, c));
    return m;
  }, [channels]);

  // Apply filters before rendering table. Search uses the SAME resolved channel
  // name we render in the UI (item.channel_name → channels lookup fallback) so
  // a row can never appear with a name the user can't find via search.
  const filteredItems = useMemo(() => {
    return items.filter(it => {
      if (fChannelId !== 'all' && String(it.channel_id || '') !== fChannelId) return false;
      if (fDate && it.event_date !== fDate) return false;
      if (fTime && (it.event_time || '').slice(0, 5) !== fTime) return false;
      if (fTranscribe !== 'all' && it.transcribe_status !== fTranscribe) return false;
      if (fRationale !== 'all' && it.rationale_status !== fRationale) return false;
      const q = fSearch.trim().toLowerCase();
      if (q) {
        const resolvedChannel = it.channel_name
          || (it.channel_id ? channelById.get(it.channel_id)?.channel_name : '')
          || '';
        const hay = `${resolvedChannel} ${it.platform || ''} ${it.video_title || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [items, fSearch, fChannelId, fDate, fTime, fTranscribe, fRationale, channelById]);

  // Stats summary
  const stats = useMemo(() => {
    const today = TODAY();
    return {
      total: items.length,
      today: items.filter(i => i.event_date === today).length,
      running: items.filter(i => {
        const t = i.transcribe_status;
        const transcribeBusy = t !== 'pending' && t !== 'completed' && t !== 'failed';
        return transcribeBusy || i.rationale_status === 'started';
      }).length,
      done: items.filter(i => i.rationale_status === 'done').length,
    };
  }, [items]);

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/30 flex items-center justify-center">
            <Radio className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Media Presence</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Track every TV / YouTube appearance and process it into a SEBI rationale.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={loadItems} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Button
            data-tour="mp-new-entry"
            onClick={() => {
              // Make sure the form starts on a platform that actually exists in
              // managed channels. resetForm() picks YouTube > first available > 'youtube'.
              resetForm();
              setOpenCreate(true);
            }}
          >
            <Plus className="w-4 h-4 mr-1.5" /> New Entry
          </Button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Total entries', value: stats.total, icon: Radio, accent: 'text-primary', bg: 'from-primary/15 to-primary/5 border-primary/20' },
          { label: 'Today', value: stats.today, icon: Calendar, accent: 'text-amber-400', bg: 'from-amber-500/10 to-amber-500/0 border-amber-500/20' },
          { label: 'Running', value: stats.running, icon: Loader2, accent: 'text-blue-400', bg: 'from-blue-500/10 to-blue-500/0 border-blue-500/20' },
          { label: 'Completed', value: stats.done, icon: CheckCircle2, accent: 'text-emerald-400', bg: 'from-emerald-500/10 to-emerald-500/0 border-emerald-500/20' },
        ].map(s => (
          <div key={s.label} className={`rounded-xl border bg-gradient-to-br ${s.bg} px-4 py-3 flex items-center gap-3`}>
            <div className={`w-9 h-9 rounded-lg bg-background/40 border border-border/40 flex items-center justify-center ${s.accent}`}>
              <s.icon className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-muted-foreground">{s.label}</div>
              <div className="text-xl font-semibold text-foreground leading-tight">{s.value}</div>
            </div>
          </div>
        ))}
      </div>

      <Card className="border-border/60 shadow-lg shadow-black/10 overflow-hidden">
        <CardHeader className="border-b border-border/50 bg-card/40">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <CardTitle className="text-base">Media Presence Entries</CardTitle>
              <CardDescription>
                Manage all your media presence &amp; rationale at one place. Record Schedules,
                Generate Transcriptions &amp; Generate Rationale using various AI tools.
              </CardDescription>
            </div>
            <Button
              size="sm" variant={filterOpen || activeFilterCount > 0 ? 'default' : 'outline'}
              onClick={() => setFilterOpen(o => !o)}
              className="gap-1.5">
              <Filter className="w-3.5 h-3.5" />
              Filters
              {activeFilterCount > 0 && (
                <span className="ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-background/30 text-[10px] font-semibold">
                  {activeFilterCount}
                </span>
              )}
            </Button>
          </div>

          {filterOpen && (
            <div className="mt-3 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
              {/* Free-text search with history popover (mirrors Dashboard) */}
              <div className="col-span-2 lg:col-span-2">
                <Popover open={historyOpen} onOpenChange={setHistoryOpen}>
                  <div className="relative">
                    <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
                    <PopoverAnchor asChild>
                      <Input
                        ref={searchInputRef}
                        placeholder="Search channel, platform or title…"
                        value={fSearch}
                        onChange={(e) => setFSearch(e.target.value)}
                        onFocus={() => { if (searchHistory.length) setHistoryOpen(true); }}
                        onClick={() => { if (searchHistory.length) setHistoryOpen(true); }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && fSearch.trim()) {
                            persistSearchQuery(fSearch);
                            setHistoryOpen(false);
                          } else if (e.key === 'Escape') {
                            setHistoryOpen(false);
                          }
                        }}
                        onBlur={() => { if (fSearch.trim()) persistSearchQuery(fSearch); }}
                        className="h-9 pl-8 pr-8 text-sm"
                      />
                    </PopoverAnchor>
                    {fSearch && (
                      <button
                        type="button"
                        onClick={() => setFSearch('')}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-accent text-muted-foreground"
                        aria-label="Clear search">
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                  <PopoverContent
                    align="start"
                    className="w-[--radix-popover-trigger-width] p-0"
                    onOpenAutoFocus={(e: Event) => e.preventDefault()}
                    onPointerDownOutside={(e: { target: EventTarget | null; preventDefault: () => void }) => {
                      if (searchInputRef.current && e.target instanceof Node && searchInputRef.current.contains(e.target)) {
                        e.preventDefault();
                      }
                    }}
                    onFocusOutside={(e: { target: EventTarget | null; preventDefault: () => void }) => {
                      if (searchInputRef.current && e.target instanceof Node && searchInputRef.current.contains(e.target)) {
                        e.preventDefault();
                      }
                    }}
                  >
                    <div className="px-3 py-2 border-b border-border flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                        <History className="w-3.5 h-3.5" /> Recent searches
                      </div>
                      {searchHistory.length > 0 && (
                        <button type="button"
                          onMouseDown={(e) => { e.preventDefault(); clearAllHistory(); }}
                          className="text-xs text-muted-foreground hover:text-foreground">
                          Clear all
                        </button>
                      )}
                    </div>
                    {searchHistory.length === 0 ? (
                      <div className="px-3 py-4 text-xs text-muted-foreground text-center">
                        No recent searches yet — your last 5 will show here.
                      </div>
                    ) : (
                      <ul className="py-1 max-h-72 overflow-auto">
                        {searchHistory.map((h) => (
                          <li key={h.query} className="group flex items-center justify-between gap-2 px-3 py-2 hover:bg-accent text-sm">
                            <button type="button"
                              onMouseDown={(e) => {
                                e.preventDefault();
                                setFSearch(h.query);
                                persistSearchQuery(h.query);
                                setHistoryOpen(false);
                              }}
                              className="flex-1 text-left flex items-center gap-2 truncate">
                              <SearchIcon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                              <span className="truncate text-foreground">{h.query}</span>
                            </button>
                            <button type="button"
                              onMouseDown={(e) => { e.preventDefault(); removeHistoryItem(h.query); }}
                              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-background text-muted-foreground"
                              aria-label="Remove from history">
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </PopoverContent>
                </Popover>
              </div>

              {/* Channel dropdown — populated from the channels database */}
              <div className="col-span-2 lg:col-span-2">
                <Select value={fChannelId} onValueChange={setFChannelId}>
                  <SelectTrigger className="h-9"><SelectValue placeholder="Channel" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All channels</SelectItem>
                    {channelOptions.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-muted-foreground">
                        No channels found.
                      </div>
                    ) : channelOptions.map(c => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        <span className="flex items-center gap-2">
                          {c.logoPath && !brokenLogos.has(c.logoPath) ? (
                            <img src={c.logoPath} alt="" className="w-4 h-4 rounded-sm object-cover"
                              onError={() => setBrokenLogos(prev => {
                                if (prev.has(c.logoPath!)) return prev;
                                const next = new Set(prev); next.add(c.logoPath!); return next;
                              })} />
                          ) : (
                            <span className="inline-flex">{platformIcon(c.platform)}</span>
                          )}
                          <span className="truncate max-w-[180px]">{c.channel_name}</span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Input type="date" value={fDate} onChange={e => setFDate(e.target.value)} className="h-9 text-sm" />
              <Input type="time" value={fTime} onChange={e => setFTime(e.target.value)} className="h-9 text-sm" />
              <Select value={fTranscribe} onValueChange={setFTranscribe}>
                <SelectTrigger className="h-9"><SelectValue placeholder="Transcribe" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all"><span className="flex items-center gap-2"><Filter className="w-3.5 h-3.5 text-muted-foreground" /> Any transcribe</span></SelectItem>
                  <SelectItem value="pending"><span className="flex items-center gap-2"><Clock className="w-3.5 h-3.5 text-muted-foreground" /> Pending</span></SelectItem>
                  <SelectItem value="started"><span className="flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 text-blue-400" /> Started</span></SelectItem>
                  <SelectItem value="completed"><span className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Completed</span></SelectItem>
                  <SelectItem value="failed"><span className="flex items-center gap-2"><AlertTriangle className="w-3.5 h-3.5 text-rose-400" /> Failed</span></SelectItem>
                </SelectContent>
              </Select>
              <Select value={fRationale} onValueChange={setFRationale}>
                <SelectTrigger className="h-9"><SelectValue placeholder="Rationale" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all"><span className="flex items-center gap-2"><Filter className="w-3.5 h-3.5 text-muted-foreground" /> Any rationale</span></SelectItem>
                  <SelectItem value="pending"><span className="flex items-center gap-2"><Clock className="w-3.5 h-3.5 text-muted-foreground" /> Pending</span></SelectItem>
                  <SelectItem value="started"><span className="flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 text-blue-400" /> Started</span></SelectItem>
                  <SelectItem value="done"><span className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Done</span></SelectItem>
                  <SelectItem value="failed"><span className="flex items-center gap-2"><AlertTriangle className="w-3.5 h-3.5 text-rose-400" /> Failed</span></SelectItem>
                </SelectContent>
              </Select>
              {activeFilterCount > 0 && (
                <Button size="sm" variant="ghost" onClick={clearFilters} className="h-9 col-span-2 lg:col-span-6 justify-self-end gap-1 text-muted-foreground hover:text-foreground">
                  <X className="w-3.5 h-3.5" /> Clear filters
                </Button>
              )}
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0 overflow-x-auto">
          {loading ? (
            <div className="py-16 text-center text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Loading…
            </div>
          ) : items.length === 0 ? (
            <div className="py-16 text-center">
              <div className="w-14 h-14 rounded-full bg-muted/30 mx-auto flex items-center justify-center mb-3">
                <Radio className="w-6 h-6 text-muted-foreground" />
              </div>
              <p className="text-foreground font-medium">No entries yet</p>
              <p className="text-sm text-muted-foreground mt-1">
                Click <b>New Entry</b> to add today&apos;s media appearance.
              </p>
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="py-16 text-center">
              <div className="w-14 h-14 rounded-full bg-muted/30 mx-auto flex items-center justify-center mb-3">
                <Filter className="w-6 h-6 text-muted-foreground" />
              </div>
              <p className="text-foreground font-medium">No entries match your filters</p>
              <Button size="sm" variant="ghost" onClick={clearFilters} className="mt-3">
                <X className="w-3.5 h-3.5 mr-1" /> Clear filters
              </Button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground bg-muted/20 border-b border-border/50">
                <tr>
                  <th className="py-3 px-4 font-medium">Platform</th>
                  <th className="py-3 px-3 font-medium">Channel</th>
                  <th className="py-3 px-3 font-medium">Date · Time</th>
                  <th className="py-3 px-2 font-medium w-[110px]">Video</th>
                  <th className="py-3 px-3 font-medium">Method</th>
                  <th className="py-3 px-3 font-medium">Transcribe</th>
                  <th className="py-3 px-3 font-medium">Rationale</th>
                  <th className="py-3 px-3 font-medium">Output</th>
                  <th className="py-3 px-4 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map(item => {
                  const acting = actingId === item.id;
                  // Voice/AI Transcribe buttons only appear when no transcribe
                  // job is in flight at all. Anything other than pending/failed
                  // (started, transcribing, review_*, translating, extracting,
                  // completed) means we already have a transcribe job — don't
                  // let the user spawn a duplicate one mid-pipeline.
                  const canVoiceOrAI =
                    item.rationale_tool !== 'media_rationale' &&
                    (item.transcribe_status === 'pending' || item.transcribe_status === 'failed');
                  // Voice Typing's only downstream is Bulk Rationale, so we
                  // gate the button to bulk_rationale entries.
                  const canVoice = canVoiceOrAI && item.rationale_tool === 'bulk_rationale';
                  const canAuto =
                    item.rationale_tool === 'media_rationale' &&
                    item.transcribe_status === 'pending';

                  const ch = item.channel_id ? channelById.get(item.channel_id) : undefined;
                  const channelLogoUrl = ch?.logoPath || '';
                  const channelDisplayName = item.channel_name || ch?.channel_name || '—';
                  return (
                    <tr key={item.id}
                        className="border-b border-border/30 align-middle hover:bg-muted/10 transition-colors">
                      {/* Platform: icon + name */}
                      <td className="py-4 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className="w-9 h-9 rounded-lg bg-muted/30 border border-border/40 flex items-center justify-center shrink-0">
                            {platformIcon(item.platform)}
                          </div>
                          <div className="font-medium text-foreground capitalize leading-tight">
                            {item.platform}
                          </div>
                        </div>
                      </td>
                      {/* Channel: uploaded logo + name */}
                      <td className="py-4 px-3">
                        <div className="flex items-center gap-2.5 min-w-[160px]">
                          {channelLogoUrl && !brokenLogos.has(channelLogoUrl) ? (
                            <img
                              src={channelLogoUrl}
                              alt={channelDisplayName}
                              className="w-9 h-9 rounded-lg border border-border/40 bg-muted/30 object-cover shrink-0"
                              onError={() => setBrokenLogos(prev => {
                                if (prev.has(channelLogoUrl)) return prev;
                                const next = new Set(prev);
                                next.add(channelLogoUrl);
                                return next;
                              })}
                            />
                          ) : (
                            <div className="w-9 h-9 rounded-lg bg-muted/30 border border-border/40 flex items-center justify-center shrink-0 text-xs font-semibold text-muted-foreground">
                              {(channelDisplayName || '?').slice(0, 2).toUpperCase()}
                            </div>
                          )}
                          <div className="font-medium text-foreground leading-tight truncate max-w-[180px]">
                            {channelDisplayName}
                          </div>
                        </div>
                      </td>
                      <td className="py-4 px-3 whitespace-nowrap">
                        <div className="font-medium text-foreground">{item.event_date}</div>
                        <div className="text-xs text-muted-foreground">{item.event_time}</div>
                      </td>
                      {/* Video: just a Play button, no title */}
                      <td className="py-4 px-2 w-[110px]">
                        {item.video_url ? (
                          <Button size="sm" variant="outline"
                                  onClick={() => openVideo(item)}
                                  title={item.video_title || 'Play video'}
                                  className="h-8 gap-1.5 border-primary/30 text-primary hover:bg-primary/10 hover:text-primary">
                            <Play className="w-3.5 h-3.5 fill-current" /> Play
                          </Button>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </td>
                      <td className="py-4 px-3">
                        <Badge variant="outline" className="font-normal bg-card/60">
                          {RATIONALE_TOOL_LABEL[item.rationale_tool]}
                        </Badge>
                      </td>
                      <td className="py-4 px-3">
                        {item.linked_transcribe_job_id ? (
                          <button
                            type="button"
                            onClick={() => {
                              const jid = item.linked_transcribe_job_id!;
                              const page = jid.startsWith('voice-') ? 'voice-typing'
                                : jid.startsWith('live-') ? 'live-transcribe'
                                : 'ai-transcribe';
                              onNavigate(page, jid);
                            }}
                            title={`Open ${item.transcribe_method?.replace('_', ' ') || 'transcribe'} job`}
                            className="text-left hover:opacity-80 transition-opacity cursor-pointer py-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <StatusPill label={item.transcribe_status} kind={item.transcribe_status} />
                              {item.transcribe_method && (
                                <span className="text-[11px] text-primary capitalize underline-offset-2 hover:underline">
                                  via {item.transcribe_method.replace('_', ' ')} →
                                </span>
                              )}
                            </div>
                          </button>
                        ) : (
                          <div className="flex items-center gap-2 flex-wrap py-1">
                            <StatusPill label={item.transcribe_status} kind={item.transcribe_status} />
                            {item.transcribe_method && (
                              <span className="text-[11px] text-muted-foreground capitalize">
                                via {item.transcribe_method.replace('_', ' ')}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-4 px-3">
                        <StatusPill label={item.rationale_status} kind={item.rationale_status} />
                        {item.rationale_job_id && (
                          <div className="text-[10px] text-muted-foreground mt-1.5 truncate max-w-[140px] font-mono">
                            {item.rationale_job_id}
                          </div>
                        )}
                      </td>
                      <td className="py-4 px-3">
                        {(item.unsigned_pdf_path || item.signed_pdf_path || item.output_pdf_path) ? (
                          <div className="flex flex-col gap-1.5">
                            {item.unsigned_pdf_path && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => downloadPdf({ ...item, output_pdf_path: item.unsigned_pdf_path! })}
                                className="h-7 px-2 text-[11px] justify-start"
                                title="Download unsigned PDF"
                              >
                                <Download className="w-3 h-3 mr-1" /> Unsigned
                              </Button>
                            )}
                            {item.signed_pdf_path && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => downloadPdf({ ...item, output_pdf_path: item.signed_pdf_path! })}
                                className="h-7 px-2 text-[11px] justify-start border-emerald-500/40 text-emerald-600 hover:bg-emerald-50"
                                title="Download signed PDF"
                              >
                                <Download className="w-3 h-3 mr-1" /> Signed
                              </Button>
                            )}
                            {item.unsigned_pdf_path && !item.signed_pdf_path && item.rationale_job_id && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => uploadSignedPdf(item.rationale_job_id!)}
                                disabled={signingId === item.rationale_job_id}
                                className="h-7 px-2 text-[11px] justify-start border-amber-500/40 text-amber-600 hover:bg-amber-50 disabled:opacity-50"
                                title="Upload signed PDF for this rationale"
                              >
                                {signingId === item.rationale_job_id ? (
                                  <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                                ) : (
                                  <Upload className="w-3 h-3 mr-1" />
                                )}
                                Upload Signed
                              </Button>
                            )}
                            {!item.unsigned_pdf_path && !item.signed_pdf_path && item.output_pdf_path && (
                              <Button size="sm" variant="outline" onClick={() => downloadPdf(item)} className="h-7 px-2 text-[11px] justify-start">
                                <Download className="w-3 h-3 mr-1" /> PDF
                              </Button>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </td>
                      <td className="py-4 px-4">
                        <div className="flex flex-wrap gap-1.5 justify-end">
                          {canVoiceOrAI && (
                            <>
                              {canVoice && (
                                <Button size="sm" variant="secondary" className="h-8"
                                  onClick={() => startVoiceTyping(item)} disabled={acting}
                                  title="Server-side transcribe (Vosk) → review → ChatGPT arrange → Bulk Rationale">
                                  {acting
                                    ? <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                                    : <Mic className="w-3 h-3 mr-1" />}
                                  Voice
                                </Button>
                              )}
                              <Button size="sm" variant="secondary" className="h-8"
                                onClick={() => startAITranscribe(item)} disabled={acting}
                                title="Spawn a standalone AI Transcribe job and open its 5-step review">
                                {acting
                                  ? <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                                  : <Sparkles className="w-3 h-3 mr-1" />}
                                AI
                              </Button>
                            </>
                          )}
                          {canAuto && (
                            <Button size="sm" variant="secondary" className="h-8"
                              onClick={() => triggerAuto(item)} disabled={acting}>
                              {acting ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Wand2 className="w-3 h-3 mr-1" />}
                              Auto
                            </Button>
                          )}
                          <Button size="sm" variant="ghost" className="h-8 w-8 p-0"
                            onClick={() => deleteEntry(item.id)}
                            title="Delete entry">
                            <Trash2 className="w-3.5 h-3.5 text-rose-400" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Video player popup — 16:9, fits within viewport */}
      <Dialog open={videoOpen} onOpenChange={(o) => { setVideoOpen(o); if (!o) setVideoItem(null); }}>
        <DialogContent className="max-w-4xl w-[95vw] max-h-[90vh] p-0 overflow-hidden bg-card border-border/50 flex flex-col">
          <DialogHeader className="px-5 py-3 bg-card border-b border-border/50 shrink-0 pr-12">
            <DialogTitle className="flex items-center gap-2 text-base">
              {videoItem && platformIcon(videoItem.platform)}
              <span className="truncate">
                {videoItem?.video_title || videoItem?.channel_name || 'Video preview'}
              </span>
            </DialogTitle>
            {videoItem && (
              <DialogDescription className="text-xs">
                {videoItem.event_date} · {videoItem.event_time}
                {videoItem.channel_name && <> · {videoItem.channel_name}</>}
              </DialogDescription>
            )}
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-hidden bg-black flex items-center justify-center">
            {videoItem?.video_url && (() => {
              const embedSrc = ytEmbedUrl(videoItem.video_url);
              if (embedSrc) {
                return (
                  <div className="w-full h-full max-h-full" style={{ aspectRatio: '16 / 9' }}>
                    <iframe
                      src={embedSrc}
                      title="Video player"
                      className="w-full h-full block"
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                      allowFullScreen
                    />
                  </div>
                );
              }
              return (
                <div className="w-full bg-slate-900 p-8 flex flex-col items-center justify-center gap-3 text-center">
                  <ExternalLink className="w-6 h-6 text-amber-400" />
                  <div className="text-sm text-muted-foreground max-w-md">
                    This video can't be embedded inline (only YouTube videos can be played here). Open it in a new tab to watch.
                  </div>
                  <a
                    href={videoItem.video_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 text-sm text-primary hover:underline break-all"
                  >
                    <ExternalLink className="w-4 h-4" /> Open video
                  </a>
                </div>
              );
            })()}
          </div>
          <div className="px-5 py-2.5 bg-card border-t border-border/50 flex items-center justify-between gap-2 shrink-0">
            <a href={videoItem?.video_url || '#'} target="_blank" rel="noreferrer"
               className="text-xs text-muted-foreground hover:text-primary truncate">
              {videoItem?.video_url}
            </a>
            <Button size="sm" variant="ghost" onClick={() => setVideoOpen(false)}>Close</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Create Entry dialog */}
      <Dialog
        open={openCreate}
        onOpenChange={(o) => { setOpenCreate(o); if (!o) resetForm(); }}
      >
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>New Media Presence entry</DialogTitle>
            <DialogDescription>
              For YouTube, paste the video URL and click <b>Fetch</b> to auto-fill channel, date, time and title from the YouTube.
              For other platforms, fill the fields manually.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 mt-2">
            {/* Row 1: Platform + Video URL + Fetch */}
            <div className="grid grid-cols-12 gap-3 items-end">
              <div className="col-span-4">
                <Label>Platform</Label>
                <Select
                  value={form.platform}
                  onValueChange={(v) => {
                    setForm({ ...form, platform: v, channel_id: '' });
                    setFetchedVideoId(null);
                    setFetchedChannelName(null);
                    setChannelMatchStatus(null);
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select platform" />
                  </SelectTrigger>
                  <SelectContent>
                    {platformOptions.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-muted-foreground">
                        No platforms found. Add channels under Channel Logos first.
                      </div>
                    ) : platformOptions.map(p => (
                      <SelectItem key={p.value} value={p.value}>
                        <span className="flex items-center gap-2">
                          {platformIcon(p.value)}
                          <span className="capitalize">{p.label}</span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="col-span-8">
                <Label>Video URL{form.rationale_tool === 'media_rationale' ? ' *' : ''}</Label>
                <div className="flex gap-2">
                  <Input
                    placeholder={isYoutubeSelected
                      ? 'https://www.youtube.com/watch?v=…'
                      : 'Paste the video / post URL (optional)'}
                    value={form.video_url}
                    onChange={e => {
                      setForm({ ...form, video_url: e.target.value });
                      if (fetchedVideoId) {
                        setFetchedVideoId(null);
                        setFetchedChannelName(null);
                        setChannelMatchStatus(null);
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && isYoutubeSelected) {
                        e.preventDefault();
                        fetchYoutubeMetadata();
                      }
                    }}
                    className="flex-1"
                  />
                  {isYoutubeSelected && (
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={fetchYoutubeMetadata}
                      disabled={fetchingMeta || !form.video_url.trim()}
                      className="shrink-0"
                      title="Fetch title, channel, date and time from YouTube"
                    >
                      {fetchingMeta
                        ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
                        : <SearchIcon className="w-4 h-4 mr-1.5" />}
                      Fetch
                    </Button>
                  )}
                </div>
                {!isYoutubeSelected && (
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Auto-fetch is only available for YouTube. Fill the fields below manually for other platforms.
                  </p>
                )}
              </div>
            </div>

            {/* Embedded YouTube player after a successful fetch */}
            {fetchedVideoId && (
              <div className="rounded-lg overflow-hidden border border-border/60 bg-black">
                <div className="relative w-full" style={{ paddingTop: '56.25%' }}>
                  <iframe
                    src={`https://www.youtube.com/embed/${fetchedVideoId}`}
                    title="Video preview"
                    className="absolute inset-0 w-full h-full"
                    allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              </div>
            )}

            {/* Row 2: Channel */}
            <div>
              <div className="flex items-center justify-between">
                <Label>Channel</Label>
                {channelMatchStatus === 'matched' && (
                  <span className="text-[11px] text-emerald-400 inline-flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Auto-matched from fetched channel
                  </span>
                )}
                {channelMatchStatus === 'unmatched' && fetchedChannelName && (
                  <span className="text-[11px] text-amber-400 inline-flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> No match for &ldquo;{fetchedChannelName}&rdquo; — pick manually
                  </span>
                )}
              </div>
              <Select
                value={form.channel_id}
                onValueChange={v => setForm({ ...form, channel_id: v })}
              >
                <SelectTrigger><SelectValue placeholder="Select a channel" /></SelectTrigger>
                <SelectContent>
                  {(() => {
                    const sel = (form.platform || '').trim().toLowerCase();
                    const filtered = channels.filter(
                      c => (c.platform || '').trim().toLowerCase() === sel,
                    );
                    if (filtered.length === 0) {
                      return (
                        <div className="px-3 py-2 text-xs text-muted-foreground">
                          No channels for this platform yet. Add one under Channel Logos.
                        </div>
                      );
                    }
                    return filtered.map(c => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.channel_name}
                      </SelectItem>
                    ));
                  })()}
                </SelectContent>
              </Select>
            </div>

            {/* Row 3: Date + Time */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Date</Label>
                <Input type="date" value={form.event_date}
                       onChange={e => setForm({ ...form, event_date: e.target.value })} />
              </div>
              <div>
                <Label>Time</Label>
                <Input type="time" value={form.event_time}
                       onChange={e => setForm({ ...form, event_time: e.target.value })} />
              </div>
            </div>

            {/* Row 4: Title */}
            <div>
              <Label>Video Title</Label>
              <Input placeholder="Auto-filled after Fetch"
                     value={form.video_title}
                     onChange={e => setForm({ ...form, video_title: e.target.value })} />
            </div>

            {/* Tool selector */}
            <div>
              <Label>Which rationale tool should process this?</Label>
              <Select value={form.rationale_tool}
                      onValueChange={v => setForm({ ...form, rationale_tool: v as any })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="bulk_rationale">Bulk Rationale (Voice or AI Transcribe)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground mt-1">
                Bulk Rationale requires you to provide the transcript via Voice Typing or AI Transcribe first.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => { setOpenCreate(false); resetForm(); }} disabled={creating}>
              Cancel
            </Button>
            <Button onClick={createEntry} disabled={creating}>
              {creating && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              Add Entry
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
