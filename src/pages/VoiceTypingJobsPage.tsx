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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Mic, Plus, Loader2, Trash2, RefreshCw, AlertTriangle,
  Youtube, Calendar, Clock, Tv, Radio, Upload, FileAudio,
  Facebook, Instagram, Send as TgIcon, MessageCircle, Globe,
  PlayCircle, ExternalLink, ArrowRight,
} from 'lucide-react';
import { getYouTubeEmbedUrl } from '@/lib/youtube-utils';
import { toast } from 'sonner';

interface VoiceJob {
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
  transcriptText: string;
  arrangedText: string;
  language: string;
  videoUrl: string;
  bulkJobId: string | null;
  bulkJobStatus?: string | null;
  bulkJobProgress?: number | null;
  arrangeError?: string | null;
  transcribeError?: string | null;
}

// Render the platform's brand icon next to the channel name. Used in the
// channel column so users can spot at a glance which feed each row came
// from (matches the Dashboard's icon convention).
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

// Status badge for the spawned Bulk Rationale child. Same colour scheme
// as the Voice Typing badges so the two cells line up visually.
const BULK_STATUS_LABEL: Record<string, { label: string; classes: string }> = {
  started:   { label: 'Running',   classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  completed: { label: 'Completed', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  failed:    { label: 'Failed',    classes: 'bg-red-500/15 text-red-300 border-red-500/30' },
  pending:   { label: 'Pending',   classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
};
function bulkStatusBadge(status?: string | null) {
  if (!status) return null;
  const meta = BULK_STATUS_LABEL[status] || { label: status, classes: 'bg-slate-500/15 text-slate-300 border-slate-500/30' };
  return <Badge variant="outline" className={`${meta.classes} border text-[10px] px-1.5 py-0`}>{meta.label}</Badge>;
}

interface ChannelRow {
  id: number;
  channel_name: string;
  platform: string;
}

interface FetchedVideoMeta {
  videoId: string;
  title: string;
  channelName: string;
  uploadDate: string;   // YYYY-MM-DD
  uploadTime: string;   // HH:MM:SS
  duration: string;
  thumbnail?: string;
}

interface Props {
  onNavigate: (page: string, id?: string | number | null) => void;
}

const STATUS_LABEL: Record<string, { label: string; classes: string }> = {
  recording: { label: 'Transcribing', classes: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  awaiting_review: { label: 'Review transcript', classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  arranging: { label: 'Arranging…', classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  awaiting_arrange_review: { label: 'Review arrangement', classes: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  bulk_started: { label: 'Sent to Bulk Rationale', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  failed: { label: 'Failed', classes: 'bg-red-500/15 text-red-300 border-red-500/30' },
  completed: { label: 'Completed', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
};

function statusBadge(status: string) {
  const meta = STATUS_LABEL[status] || { label: status, classes: 'bg-slate-500/15 text-slate-300 border-slate-500/30' };
  return (
    <Badge variant="outline" className={`${meta.classes} border`}>{meta.label}</Badge>
  );
}

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export default function VoiceTypingJobsPage({ onNavigate }: Props) {
  const { token } = useAuth();
  const [jobs, setJobs] = useState<VoiceJob[]>([]);
  const [channels, setChannels] = useState<ChannelRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [creating, setCreating] = useState(false);

  // Video popup — clicking a row's "Play video" button opens the YouTube
  // embed in a dialog instead of navigating away. Stored as the whole job
  // (not just the URL) so the dialog header can also show the title.
  const [videoOpenJob, setVideoOpenJob] = useState<VoiceJob | null>(null);

  // Error popup — failed jobs have an `arrangeError` / `transcribeError`
  // string that can be a multi-paragraph 429 body. Rendering it inline in
  // the status cell broke the table layout, so we show a small icon
  // button that opens the full message in a dialog.
  const [errorOpenJob, setErrorOpenJob] = useState<VoiceJob | null>(null);

  // form
  const [createMode, setCreateMode] = useState<'youtube' | 'upload'>('youtube');
  const [fTitle, setFTitle] = useState('');
  const [fChannel, setFChannel] = useState<string>('');
  const [fDate, setFDate] = useState(todayISO());
  const [fTime, setFTime] = useState('10:00');
  const [fLanguage, setFLanguage] = useState('hi-IN');
  const [fVideoUrl, setFVideoUrl] = useState('');
  const [fAudioFile, setFAudioFile] = useState<File | null>(null);
  const [fetchingMeta, setFetchingMeta] = useState(false);
  const [videoMeta, setVideoMeta] = useState<FetchedVideoMeta | null>(null);

  const fetchJobs = async () => {
    try {
      const r = await fetch(API_ENDPOINTS.voiceTyping.list, {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to load jobs');
      setJobs(j.jobs || []);
    } catch (e: any) {
      toast.error(e.message || 'Could not load voice typing jobs');
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
    setCreateMode('youtube');
    setFTitle('');
    setFChannel('');
    setFDate(todayISO());
    setFTime('10:00');
    setFLanguage('hi-IN');
    setFVideoUrl('');
    setFAudioFile(null);
    setVideoMeta(null);
  };

  // Auto-fetch video metadata via the same YouTube Data API endpoint
  // that Media Rationale uses, then prefill the form fields.
  const handleFetchVideo = async () => {
    const url = fVideoUrl.trim();
    if (!url) { toast.error('Paste a YouTube video URL first.'); return; }
    setFetchingMeta(true);
    try {
      const r = await fetch(API_ENDPOINTS.mediaRationale.fetchVideo, {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ youtubeUrl: url }),
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

      // Prefill form fields from fetched metadata.
      if (meta.title && !fTitle.trim()) setFTitle(meta.title);
      if (meta.uploadDate) setFDate(meta.uploadDate);
      if (meta.uploadTime) setFTime(meta.uploadTime.slice(0, 5)); // HH:MM
      if (meta.channelName) {
        const target = meta.channelName.toLowerCase().trim();
        const matched = channels.find(
          c => c.channel_name.toLowerCase().trim() === target,
        );
        if (matched) {
          setFChannel(String(matched.id));
        } else {
          toast.message(`Channel "${meta.channelName}" not in your channel list — pick one manually.`);
        }
      }
      toast.success('Video info fetched.');
    } catch (e: any) {
      toast.error(e.message || 'Failed to fetch video metadata');
    } finally {
      setFetchingMeta(false);
    }
  };

  const handleCreate = async () => {
    if (!fChannel) { toast.error('Pick a channel'); return; }
    if (!fDate) { toast.error('Pick a date'); return; }

    if (createMode === 'youtube') {
      if (!fVideoUrl.trim()) { toast.error('YouTube video URL is required'); return; }
    } else {
      if (!fAudioFile) { toast.error('Pick an audio file to upload'); return; }
      const MAX = 500 * 1024 * 1024;
      if (fAudioFile.size > MAX) {
        toast.error(`File too large (${(fAudioFile.size / 1024 / 1024).toFixed(0)} MB). Max 500 MB.`);
        return;
      }
    }

    setCreating(true);
    try {
      let jobId: string;

      if (createMode === 'youtube') {
        const r = await fetch(API_ENDPOINTS.voiceTyping.create, {
          method: 'POST',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({
            title: fTitle.trim() || null,
            channelId: parseInt(fChannel, 10),
            callDate: fDate,
            callTime: fTime ? `${fTime}:00` : null,
            language: fLanguage,
            videoUrl: fVideoUrl.trim(),
          }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || 'Could not create job');
        jobId = j.job.jobId;
        toast.success('Job created — server is downloading audio and transcribing it now.');
      } else {
        const fd = new FormData();
        fd.append('file', fAudioFile!);
        if (fTitle.trim()) fd.append('title', fTitle.trim());
        fd.append('channelId', fChannel);
        fd.append('callDate', fDate);
        if (fTime) fd.append('callTime', `${fTime}:00`);
        fd.append('language', fLanguage);
        const r = await fetch(API_ENDPOINTS.voiceTyping.createFromUpload, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: fd,
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || 'Upload failed');
        jobId = j.job.jobId;
        toast.success('Audio uploaded — server is transcribing it now.');
      }

      setShowNew(false);
      resetForm();
      onNavigate('voice-typing', jobId);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!confirm('Delete this voice typing job? Transcript will be lost.')) return;
    try {
      const r = await fetch(API_ENDPOINTS.voiceTyping.delete(jobId), {
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
            <Mic className="w-6 h-6 text-primary" /> Voice Typing
          </h1>
          <p className="text-muted-foreground">
            Server-side transcribes a YouTube video (or your uploaded audio
            file). Then ChatGPT arranges the transcript stock-by-stock for
            your review, and finally pushes it into Bulk Rationale.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchJobs}>
            <RefreshCw className="w-4 h-4 mr-1" /> Refresh
          </Button>
          <Button onClick={() => setShowNew(true)} data-tour="vt-new">
            <Plus className="w-4 h-4 mr-1" /> New voice typing
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your jobs</CardTitle>
          <CardDescription>
            Each row is one transcription session, walked through three
            reviewable steps: <b>1. Transcribe</b> → <b>2. Review transcript &amp; arrange via ChatGPT</b> →
            <b> 3. Review arrangement &amp; send to Bulk Rationale</b>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="py-10 text-center text-muted-foreground">
              <Loader2 className="w-5 h-5 inline animate-spin mr-2" /> Loading…
            </div>
          ) : sortedJobs.length === 0 ? (
            <div className="py-10 text-center text-muted-foreground space-y-2">
              <p>No voice typing jobs yet.</p>
              <Button variant="outline" onClick={() => setShowNew(true)}>
                <Plus className="w-4 h-4 mr-1" /> Start your first session
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b border-border">
                  <tr>
                    <th className="text-left py-2 pr-3">Video</th>
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
                    const wordCount = j.transcriptText.trim()
                      ? j.transcriptText.trim().split(/\s+/).length
                      : 0;
                    const openJob = () => onNavigate('voice-typing', j.jobId);
                    // Any user-visible failure message we have for this
                    // job. Arrange errors take priority over transcribe
                    // errors (the user already saw and acted on the
                    // transcribe step before we got to arrange).
                    const errorMsg = j.arrangeError || j.transcribeError || '';
                    const hasVideo = !!getYouTubeEmbedUrl(j.videoUrl);
                    return (
                      <tr key={j.jobId} className="border-b border-border/50 hover:bg-accent/40">
                        {/* Play video — popup the YouTube embed. Falls
                            back to an "Open in new tab" link for non-
                            embeddable URLs (LinkedIn, FB, etc), and
                            shows a dash when the job has no video at
                            all (uploaded-audio jobs). */}
                        <td className="py-2 pr-3 align-top">
                          {j.videoUrl ? (
                            hasVideo ? (
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 px-2 text-xs"
                                onClick={() => setVideoOpenJob(j)}
                              >
                                <PlayCircle className="w-3.5 h-3.5 mr-1 text-rose-400" />
                                Play video
                              </Button>
                            ) : (
                              <a
                                href={j.videoUrl}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                              >
                                <ExternalLink className="w-3.5 h-3.5" /> Open
                              </a>
                            )
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>

                        {/* Channel + platform icon (matches the
                            Dashboard's icon convention). */}
                        <td className="py-2 pr-3 align-top">
                          <div className="flex items-center gap-2">
                            {platformIcon(j.platform)}
                            <div className="min-w-0">
                              <div className="text-foreground truncate max-w-[160px]" title={j.channelName || ''}>
                                {j.channelName || '—'}
                              </div>
                              {j.platform && (
                                <div className="text-[10px] uppercase text-muted-foreground tracking-wide">
                                  {j.platform}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Date & time stacked. */}
                        <td className="py-2 pr-3 align-top whitespace-nowrap">
                          <div className="flex items-center gap-1 text-foreground">
                            <Calendar className="w-3 h-3 text-muted-foreground" />
                            {j.date || '—'}
                          </div>
                          {j.time && (
                            <div className="flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                              <Clock className="w-3 h-3" />
                              {j.time}
                            </div>
                          )}
                        </td>

                        {/* Status badge + Open-current-job button right
                            beside it (per user request). Errors are
                            represented by a small alert button that
                            opens the full message in a popup — keeps
                            the row height stable even for multi-line
                            error bodies (e.g. raw OpenAI 429 dumps). */}
                        <td className="py-2 pr-3 align-top">
                          <div className="flex items-center gap-2 flex-wrap">
                            {statusBadge(j.status)}
                            {j.status === 'recording' && (
                              <Radio className="w-3 h-3 text-rose-300 animate-pulse" />
                            )}
                            {j.status === 'failed' && errorMsg && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 px-1.5 text-xs text-red-300 hover:text-red-200"
                                onClick={() => setErrorOpenJob(j)}
                                title="View error details"
                              >
                                <AlertTriangle className="w-3.5 h-3.5 mr-1" />
                                Error
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-6 px-2 text-xs"
                              onClick={openJob}
                            >
                              Open <ArrowRight className="w-3 h-3 ml-1" />
                            </Button>
                          </div>
                        </td>

                        {/* Words count from current transcript. */}
                        <td className="py-2 pr-3 align-top text-muted-foreground whitespace-nowrap">
                          {wordCount.toLocaleString()}
                        </td>

                        {/* Bulk Rationale child — id + live status. */}
                        <td className="py-2 pr-3 align-top">
                          {j.bulkJobId ? (
                            <div className="flex flex-col items-start gap-1">
                              <button
                                className="font-mono text-xs text-primary hover:underline inline-flex items-center gap-1"
                                onClick={() => onNavigate('bulk-rationale', j.bulkJobId!)}
                                title="Open Bulk Rationale job"
                              >
                                {j.bulkJobId}
                                <ExternalLink className="w-3 h-3" />
                              </button>
                              {bulkStatusBadge(j.bulkJobStatus)}
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>

                        {/* Trailing actions — only delete now (Open
                            moved up beside the status). */}
                        <td className="py-2 pl-3 align-top text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(j.jobId)}
                            title="Delete job"
                          >
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

      <Dialog
        open={showNew}
        onOpenChange={(open: boolean) => {
          setShowNew(open);
          if (!open) resetForm();
        }}
      >
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>New voice typing session</DialogTitle>
            <DialogDescription>
              Two ways to start: paste a YouTube URL (server downloads and
              transcribes the audio) or upload an audio file directly. Either
              way, the server runs Vosk transcription and you review the
              result before it goes into Bulk Rationale.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <Tabs value={createMode} onValueChange={(v: string) => setCreateMode(v as 'youtube' | 'upload')}>
              <TabsList className="grid grid-cols-2 w-full">
                <TabsTrigger value="youtube">
                  <Youtube className="w-4 h-4 mr-1" /> YouTube URL
                </TabsTrigger>
                <TabsTrigger value="upload">
                  <Upload className="w-4 h-4 mr-1" /> Upload audio
                </TabsTrigger>
              </TabsList>

              <TabsContent value="youtube" className="space-y-4 pt-3">
                <div className="space-y-2">
                  <Label className="flex items-center gap-1">
                    <Youtube className="w-4 h-4 text-rose-400" /> YouTube video URL *
                  </Label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <Input
                      value={fVideoUrl}
                      onChange={e => { setFVideoUrl(e.target.value); setVideoMeta(null); }}
                      placeholder="https://www.youtube.com/watch?v=..."
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={handleFetchVideo}
                      disabled={fetchingMeta || !fVideoUrl.trim()}
                      className="shrink-0"
                    >
                      {fetchingMeta ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Youtube className="w-4 h-4 mr-1" />}
                      Fetch video
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Server will download this video&apos;s audio and run Vosk on it.
                  </p>
                </div>

                {videoMeta && (
                  <Card className="bg-muted/30 border-border">
                    <CardContent className="p-3 flex gap-3">
                      {videoMeta.thumbnail && (
                        <img
                          src={videoMeta.thumbnail}
                          alt=""
                          className="w-32 h-20 object-cover rounded border border-border shrink-0"
                        />
                      )}
                      <div className="text-xs space-y-1 min-w-0 flex-1">
                        <div className="font-medium text-foreground line-clamp-2 break-words" title={videoMeta.title}>
                          {videoMeta.title}
                        </div>
                        <div className="flex items-center gap-1 text-muted-foreground truncate">
                          <Tv className="w-3 h-3 shrink-0" /> <span className="truncate">{videoMeta.channelName}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
                          <span className="flex items-center gap-1"><Calendar className="w-3 h-3" /> {videoMeta.uploadDate}</span>
                          <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {videoMeta.uploadTime}</span>
                          {videoMeta.duration && <span>· {videoMeta.duration}</span>}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </TabsContent>

              <TabsContent value="upload" className="space-y-4 pt-3">
                <div className="space-y-2">
                  <Label className="flex items-center gap-1">
                    <FileAudio className="w-4 h-4 text-emerald-400" /> Audio file *
                  </Label>
                  <Input
                    type="file"
                    accept=".mp3,.m4a,.wav,.ogg,.opus,.webm,.mp4,.aac,.flac,.wma,audio/*"
                    onChange={(e) => setFAudioFile(e.target.files?.[0] || null)}
                  />
                  {fAudioFile && (
                    <div className="text-xs text-muted-foreground flex items-center gap-2">
                      <FileAudio className="w-3 h-3" />
                      <span className="truncate">{fAudioFile.name}</span>
                      <span>· {(fAudioFile.size / 1024 / 1024).toFixed(1)} MB</span>
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">
                    MP3 / M4A / WAV / OGG / Opus / MP4 / FLAC / AAC / WMA, up to 500 MB.
                    Server will run Vosk on this directly — no YouTube download.
                  </p>
                </div>
              </TabsContent>
            </Tabs>

            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                value={fTitle}
                onChange={e => setFTitle(e.target.value)}
                placeholder={createMode === 'youtube'
                  ? 'Auto-filled from YouTube; you can override'
                  : 'Optional — defaults to the file name'}
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>Channel *</Label>
                <Select value={fChannel} onValueChange={setFChannel}>
                  <SelectTrigger><SelectValue placeholder="Pick a channel" /></SelectTrigger>
                  <SelectContent>
                    {channels.map(c => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.platform.toUpperCase()} — {c.channel_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Recognition language</Label>
                <Select value={fLanguage} onValueChange={setFLanguage}>
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>Call date *</Label>
                <Input type="date" value={fDate} onChange={e => setFDate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>Call time</Label>
                <Input type="time" value={fTime} onChange={e => setFTime(e.target.value)} />
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setShowNew(false)} disabled={creating}>Cancel</Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <ArrowRight className="w-4 h-4 mr-1" />}
              Create &amp; open editor
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Video player popup — opened from each row's "Play" button.
          We re-resolve the embed URL inside the dialog so an invalid /
          non-YouTube URL falls back to a clear "Open in new tab" link
          instead of an empty iframe (which would silently render the
          parent SPA — the bug `getYouTubeEmbedUrl` was created to
          prevent). */}
      <Dialog open={!!videoOpenJob} onOpenChange={(open: boolean) => { if (!open) setVideoOpenJob(null); }}>
        <DialogContent className="w-[95vw] max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader className="min-w-0">
            <DialogTitle className="flex items-center gap-2 min-w-0 pr-8">
              <PlayCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span className="truncate min-w-0">{videoOpenJob?.title || videoOpenJob?.jobId}</span>
            </DialogTitle>
            {videoOpenJob?.channelName && (
              <DialogDescription className="flex items-center gap-2 min-w-0 flex-wrap">
                {platformIcon(videoOpenJob.platform)}
                <span className="truncate">{videoOpenJob.channelName}</span>
                {videoOpenJob.date && <span className="shrink-0">· {videoOpenJob.date} {videoOpenJob.time || ''}</span>}
              </DialogDescription>
            )}
          </DialogHeader>
          {videoOpenJob && (() => {
            const embed = getYouTubeEmbedUrl(videoOpenJob.videoUrl, { autoplay: true });
            return embed ? (
              <div className="aspect-video w-full bg-black rounded overflow-hidden">
                <iframe
                  src={embed}
                  title={videoOpenJob.title || videoOpenJob.jobId}
                  className="w-full h-full"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                />
              </div>
            ) : (
              <a
                href={videoOpenJob.videoUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                <ExternalLink className="w-4 h-4" /> Open video in new tab
              </a>
            );
          })()}
          <DialogFooter className="flex-wrap gap-2">
            {videoOpenJob && (
              <Button
                variant="outline"
                onClick={() => { const j = videoOpenJob; setVideoOpenJob(null); onNavigate('voice-typing', j.jobId); }}
              >
                Open job <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            )}
            <Button onClick={() => setVideoOpenJob(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Error details popup — used in place of the old inline truncated
          red text that broke the table layout when OpenAI / Vosk dumped
          a multi-paragraph error body into `arrange_error`. */}
      <Dialog open={!!errorOpenJob} onOpenChange={(open: boolean) => { if (!open) setErrorOpenJob(null); }}>
        <DialogContent className="w-[95vw] max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-300">
              <AlertTriangle className="w-4 h-4" />
              Error details
            </DialogTitle>
            <DialogDescription>
              {errorOpenJob?.jobId}{errorOpenJob?.title ? ` — ${errorOpenJob.title}` : ''}
            </DialogDescription>
          </DialogHeader>
          <pre className="text-xs whitespace-pre-wrap break-words bg-muted/30 border border-border rounded p-3 max-h-[60vh] overflow-y-auto text-red-200">
            {errorOpenJob?.arrangeError || errorOpenJob?.transcribeError || 'No error message recorded.'}
          </pre>
          <DialogFooter>
            {errorOpenJob && (
              <Button
                variant="outline"
                onClick={() => { const j = errorOpenJob; setErrorOpenJob(null); onNavigate('voice-typing', j.jobId); }}
              >
                Open job <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            )}
            <Button onClick={() => setErrorOpenJob(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
