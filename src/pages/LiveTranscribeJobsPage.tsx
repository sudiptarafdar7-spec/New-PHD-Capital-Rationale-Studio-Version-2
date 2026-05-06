import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '@/lib/api-config';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Wifi, Plus, Loader2, Trash2, RefreshCw, AlertTriangle,
  Youtube, Calendar, Clock, Radio,
  Facebook, Instagram, Send as TgIcon, MessageCircle, Globe,
  PlayCircle, ExternalLink, ArrowRight, Search,
} from 'lucide-react';
import { getYouTubeEmbedUrl } from '@/lib/youtube-utils';
import { toast } from 'sonner';

interface LiveJob {
  jobId: string;
  title: string;
  status: string;
  progress?: number;
  channelId: number | null;
  channelName?: string | null;
  platform?: string | null;
  date: string | null;
  time: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  liveUrl: string;
  liveTranscript: string;
  diarizedTranscript: string;
  arrangedText: string;
  bulkJobId: string | null;
  bulkJobStatus?: string | null;
  bulkJobProgress?: number | null;
  arrangeError?: string | null;
  transcribeError?: string | null;
  diarizeError?: string | null;
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

const STATUS_LABEL: Record<string, { label: string; classes: string }> = {
  live: { label: 'Live · Recording', classes: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  awaiting_review: { label: 'Review transcript', classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  extracting: { label: 'Extracting…', classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  awaiting_extract_review: { label: 'Review extraction', classes: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  bulk_started: { label: 'Sent to Bulk Rationale', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  failed: { label: 'Failed', classes: 'bg-red-500/15 text-red-300 border-red-500/30' },
  completed: { label: 'Completed', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
};
function statusBadge(status: string) {
  const meta = STATUS_LABEL[status] || { label: status, classes: 'bg-slate-500/15 text-slate-300 border-slate-500/30' };
  return <Badge variant="outline" className={`${meta.classes} border`}>{meta.label}</Badge>;
}

const BULK_STATUS_LABEL: Record<string, { label: string; classes: string }> = {
  started:   { label: 'Running',   classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  processing:{ label: 'Running',   classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  completed: { label: 'Completed', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  failed:    { label: 'Failed',    classes: 'bg-red-500/15 text-red-300 border-red-500/30' },
  pending:   { label: 'Pending',   classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
};
function bulkStatusBadge(status?: string | null) {
  if (!status) return null;
  const meta = BULK_STATUS_LABEL[status] || { label: status, classes: 'bg-slate-500/15 text-slate-300 border-slate-500/30' };
  return <Badge variant="outline" className={`${meta.classes} border text-[10px] px-1.5 py-0`}>{meta.label}</Badge>;
}

interface ChannelRow { id: number; channel_name: string; platform: string; }
interface FetchedVideoMeta {
  videoId: string; title: string; channelName: string;
  uploadDate: string; uploadTime: string; duration: string; thumbnail?: string;
}
interface Props {
  onNavigate: (page: string, id?: string | number | null) => void;
  mediaId?: number;
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

export default function LiveTranscribeJobsPage({ onNavigate }: Props) {
  const { token } = useAuth();
  const [jobs, setJobs] = useState<LiveJob[]>([]);
  const [channels, setChannels] = useState<ChannelRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [creating, setCreating] = useState(false);
  const [videoOpenJob, setVideoOpenJob] = useState<LiveJob | null>(null);
  const [errorOpenJob, setErrorOpenJob] = useState<LiveJob | null>(null);

  // Form state — Step 1 of the tool flow lives in this dialog. The user
  // pastes a YouTube live URL, presses "Fetch", and the form auto-fills
  // title / channel / date / time from YouTube Data API metadata.
  const [fTitle, setFTitle] = useState('');
  const [fChannel, setFChannel] = useState<string>('');
  const [fDate, setFDate] = useState(todayISO());
  const [fTime, setFTime] = useState('10:00');
  const [fLiveUrl, setFLiveUrl] = useState('');
  const [fetchingMeta, setFetchingMeta] = useState(false);
  const [videoMeta, setVideoMeta] = useState<FetchedVideoMeta | null>(null);

  const fetchJobs = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.list, {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to load jobs');
      setJobs(j.jobs || []);
    } catch (e: any) {
      toast.error(e.message || 'Could not load Live Transcribe jobs');
    } finally {
      setLoading(false);
    }
  };

  const fetchChannels = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.channels.getAll, {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (r.ok) setChannels(j.channels || j || []);
    } catch (e) {
      console.warn(e);
    }
  };

  useEffect(() => {
    fetchJobs();
    fetchChannels();
    const id = window.setInterval(fetchJobs, 6000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sortedJobs = useMemo(() =>
    [...jobs].sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || '')),
  [jobs]);

  const resetForm = () => {
    setFTitle(''); setFChannel(''); setFDate(todayISO()); setFTime('10:00');
    setFLiveUrl(''); setVideoMeta(null);
  };

  // Step 1: fetch live-stream metadata via the same YouTube Data API
  // endpoint Voice Typing / Media Rationale already use, then prefill.
  // Triggered automatically (debounced) on URL paste/blur, with the manual
  // Fetch button kept as a fallback.
  const handleFetchVideo = async (urlOverride?: string) => {
    const url = (urlOverride ?? fLiveUrl).trim();
    if (!url) { if (!urlOverride) toast.error('Paste a YouTube live URL first.'); return; }
    setFetchingMeta(true);
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.fetchMetadata, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ liveUrl: url, youtubeUrl: url }),
      });
      const j = await r.json();
      if (!r.ok || !j.success) throw new Error(j.error || j.message || 'Could not fetch video');
      const data = j.data || {};
      const meta: FetchedVideoMeta = {
        videoId: data.videoId || data.video_id,
        title: data.title || '',
        channelName: data.channelName || data.channel_name || '',
        uploadDate: data.uploadDate || data.date || '',
        uploadTime: data.uploadTime || data.time || '',
        duration: data.duration || '',
        thumbnail: data.thumbnail,
      };
      setVideoMeta(meta);
      if (meta.title && !fTitle.trim()) setFTitle(meta.title);
      if (meta.uploadDate) setFDate(meta.uploadDate);
      if (meta.uploadTime) setFTime(meta.uploadTime.slice(0, 5));
      if (meta.channelName) {
        const target = meta.channelName.toLowerCase().trim();
        const matched = channels.find(c => c.channel_name.toLowerCase().trim() === target);
        if (matched) setFChannel(String(matched.id));
        else toast.message(`Channel "${meta.channelName}" not in your channel list — pick one manually.`);
      }
      toast.success('Live stream info fetched.');
    } catch (e: any) {
      toast.error(e.message || 'Failed to fetch live stream metadata');
    } finally {
      setFetchingMeta(false);
    }
  };

  const handleCreate = async () => {
    if (!fChannel) { toast.error('Pick a channel'); return; }
    if (!fDate) { toast.error('Pick a date'); return; }
    if (!fLiveUrl.trim()) { toast.error('YouTube live URL is required'); return; }

    setCreating(true);
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.create, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({
          title: fTitle.trim() || null,
          channelId: parseInt(fChannel, 10),
          callDate: fDate,
          callTime: fTime ? `${fTime}:00` : null,
          liveUrl: fLiveUrl.trim(),
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not create job');
      const jobId: string = j.job.jobId;
      toast.success('Live capture started — opening the live transcript.');
      setShowNew(false);
      resetForm();
      onNavigate('live-transcribe', jobId);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!confirm('Delete this Live Transcribe job? Captured audio + transcripts will be lost.')) return;
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.delete(jobId), {
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

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl text-foreground flex items-center gap-2">
            <Wifi className="w-6 h-6 text-primary" /> Live Transcribe
          </h1>
          <p className="text-muted-foreground">
            Capture a YouTube live stream on the server, transcribe it in
            real-time, then extract Pradip Halder's stock analyses and push
            them into Bulk Rationale.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchJobs}>
            <RefreshCw className="w-4 h-4 mr-1" /> Refresh
          </Button>
          <Button onClick={() => setShowNew(true)} data-tour="lt-new">
            <Plus className="w-4 h-4 mr-1" /> New live transcribe
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your live sessions</CardTitle>
          <CardDescription>
            Each row is one live capture session, walked through four
            reviewable steps: <b>1. Fetch metadata</b> → <b>2. Live capture &amp; review</b> →
            <b> 3. Extract Pradip's analysis</b> → <b>4. Send to Bulk Rationale</b>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="py-10 text-center text-muted-foreground">
              <Loader2 className="w-5 h-5 inline animate-spin mr-2" /> Loading…
            </div>
          ) : sortedJobs.length === 0 ? (
            <div className="py-10 text-center text-muted-foreground space-y-2">
              <p>No live transcribe sessions yet.</p>
              <Button variant="outline" onClick={() => setShowNew(true)}>
                <Plus className="w-4 h-4 mr-1" /> Start your first session
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b border-border">
                  <tr>
                    <th className="text-left py-2 pr-3">Live</th>
                    <th className="text-left py-2 pr-3">Channel</th>
                    <th className="text-left py-2 pr-3">Date / time</th>
                    <th className="text-left py-2 pr-3">Status</th>
                    <th className="text-left py-2 pr-3">Words</th>
                    <th className="text-left py-2 pr-3">Bulk Rationale</th>
                    <th className="text-right py-2 pl-3"> </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedJobs.map((j) => {
                    const transcriptForCount = j.diarizedTranscript || j.liveTranscript || '';
                    const wordCount = transcriptForCount.trim()
                      ? transcriptForCount.trim().split(/\s+/).length
                      : 0;
                    const openJob = () => onNavigate('live-transcribe', j.jobId);
                    const errorMsg = j.arrangeError || j.transcribeError || j.diarizeError || '';
                    const hasVideo = !!getYouTubeEmbedUrl(j.liveUrl);
                    return (
                      <tr key={j.jobId} className="border-b border-border/50 hover:bg-accent/40">
                        <td className="py-2 pr-3 align-top">
                          {j.liveUrl ? (
                            hasVideo ? (
                              <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                                onClick={() => setVideoOpenJob(j)}>
                                <PlayCircle className="w-3.5 h-3.5 mr-1 text-rose-400" /> Open live
                              </Button>
                            ) : (
                              <a href={j.liveUrl} target="_blank" rel="noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                                <ExternalLink className="w-3.5 h-3.5" /> Open
                              </a>
                            )
                          ) : <span className="text-xs text-muted-foreground">—</span>}
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
                              <Clock className="w-3 h-3" />{j.time}
                            </div>
                          )}
                        </td>
                        <td className="py-2 pr-3 align-top">
                          <div className="flex items-center gap-2 flex-wrap">
                            {statusBadge(j.status)}
                            {j.status === 'live' && (
                              <Radio className="w-3 h-3 text-rose-300 animate-pulse" />
                            )}
                            {j.status === 'failed' && errorMsg && (
                              <Button variant="ghost" size="sm"
                                className="h-6 px-1.5 text-xs text-red-300 hover:text-red-200"
                                onClick={() => setErrorOpenJob(j)} title="View error details">
                                <AlertTriangle className="w-3.5 h-3.5 mr-1" /> Error
                              </Button>
                            )}
                            <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={openJob}>
                              Open <ArrowRight className="w-3 h-3 ml-1" />
                            </Button>
                          </div>
                        </td>
                        <td className="py-2 pr-3 align-top text-muted-foreground whitespace-nowrap">
                          {wordCount.toLocaleString()}
                        </td>
                        <td className="py-2 pr-3 align-top">
                          {j.bulkJobId ? (
                            <div className="flex flex-col items-start gap-1">
                              <button
                                className="font-mono text-xs text-primary hover:underline inline-flex items-center gap-1"
                                onClick={() => onNavigate('bulk-rationale', j.bulkJobId!)}
                                title="Open Bulk Rationale job">
                                {j.bulkJobId}<ExternalLink className="w-3 h-3" />
                              </button>
                              {bulkStatusBadge(j.bulkJobStatus)}
                            </div>
                          ) : <span className="text-xs text-muted-foreground">—</span>}
                        </td>
                        <td className="py-2 pl-3 align-top text-right">
                          <Button variant="ghost" size="sm" onClick={() => handleDelete(j.jobId)} title="Delete job">
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

      {/* New job dialog (Step 1 of the tool flow) */}
      <Dialog open={showNew} onOpenChange={setShowNew}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Start a new live transcription</DialogTitle>
            <DialogDescription>
              Step 1 — paste the YouTube live URL and click <b>Fetch</b> to
              auto-fill the rest. The server starts capturing and
              transcribing the moment you click <b>Start</b>.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div>
              <Label className="text-xs">YouTube live URL</Label>
              <div className="flex gap-2 mt-1">
                <Input
                  placeholder="https://www.youtube.com/live/…"
                  value={fLiveUrl}
                  onChange={e => {
                    const v = e.target.value;
                    setFLiveUrl(v);
                    // Auto-fetch on paste of a YouTube URL — avoids the user
                    // needing to click Fetch when the URL was pasted whole.
                    const trimmed = v.trim();
                    const looksLikeUrl = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(trimmed);
                    const wasPaste = trimmed.length - fLiveUrl.trim().length > 5;
                    if (looksLikeUrl && wasPaste && !fetchingMeta) {
                      handleFetchVideo(trimmed);
                    }
                  }}
                  onBlur={() => {
                    const trimmed = fLiveUrl.trim();
                    const looksLikeUrl = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(trimmed);
                    if (looksLikeUrl && !videoMeta && !fetchingMeta) {
                      handleFetchVideo(trimmed);
                    }
                  }}
                />
                <Button type="button" variant="outline" onClick={() => handleFetchVideo()} disabled={fetchingMeta}>
                  {fetchingMeta ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                  <span className="ml-1">Fetch</span>
                </Button>
              </div>
              {videoMeta && videoMeta.title && (
                <div className="text-xs text-muted-foreground mt-1.5 truncate" title={videoMeta.title}>
                  ↳ {videoMeta.title}
                </div>
              )}
            </div>

            <div>
              <Label className="text-xs">Title (optional — auto-built from platform/channel/date if empty)</Label>
              <Input className="mt-1" value={fTitle} onChange={e => setFTitle(e.target.value)} placeholder="Auto-build" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Channel</Label>
                <Select value={fChannel} onValueChange={setFChannel}>
                  <SelectTrigger className="mt-1"><SelectValue placeholder="Pick channel" /></SelectTrigger>
                  <SelectContent>
                    {channels.map(c => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.channel_name} <span className="text-xs text-muted-foreground">({c.platform})</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-xs">Date</Label>
                  <Input className="mt-1" type="date" value={fDate} onChange={e => setFDate(e.target.value)} />
                </div>
                <div>
                  <Label className="text-xs">Time</Label>
                  <Input className="mt-1" type="time" value={fTime} onChange={e => setFTime(e.target.value)} />
                </div>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNew(false)} disabled={creating}>Cancel</Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Wifi className="w-4 h-4 mr-1" />}
              Start live capture
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Video popup */}
      <Dialog open={!!videoOpenJob} onOpenChange={() => setVideoOpenJob(null)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="truncate">{videoOpenJob?.title || 'Live stream'}</DialogTitle>
          </DialogHeader>
          {videoOpenJob && getYouTubeEmbedUrl(videoOpenJob.liveUrl) ? (
            <div className="aspect-video rounded-lg overflow-hidden bg-black">
              <iframe
                src={getYouTubeEmbedUrl(videoOpenJob.liveUrl, { autoplay: true })}
                className="w-full h-full"
                allow="autoplay; encrypted-media; picture-in-picture"
                allowFullScreen
                title={videoOpenJob.title}
              />
            </div>
          ) : (
            <a href={videoOpenJob?.liveUrl || '#'} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-primary hover:underline">
              <ExternalLink className="w-4 h-4" /> Open video in new tab
            </a>
          )}
        </DialogContent>
      </Dialog>

      {/* Error popup */}
      <Dialog open={!!errorOpenJob} onOpenChange={() => setErrorOpenJob(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-red-300 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" /> Live Transcribe error
            </DialogTitle>
          </DialogHeader>
          <pre className="whitespace-pre-wrap text-xs text-red-200 bg-red-950/40 border border-red-900/40 p-3 rounded max-h-[60vh] overflow-auto">
            {errorOpenJob?.arrangeError || errorOpenJob?.transcribeError || errorOpenJob?.diarizeError || ''}
          </pre>
        </DialogContent>
      </Dialog>
    </div>
  );
}
