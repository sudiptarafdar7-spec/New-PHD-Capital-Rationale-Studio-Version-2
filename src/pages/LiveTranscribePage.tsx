import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '@/lib/api-config';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Wifi, Save, ArrowLeft, Loader2, ExternalLink, PlayCircle,
  Sparkles, CheckCircle2, Circle, Send, AlertTriangle, Square, Radio,
} from 'lucide-react';
import { getYouTubeEmbedUrl } from '@/lib/youtube-utils';

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
  liveUrl: string;
  liveTranscript: string;
  diarizedTranscript: string;
  arrangedText: string;
  bulkJobId: string | null;
  arrangeError?: string | null;
  transcribeError?: string | null;
  diarizeError?: string | null;
}

interface Props {
  onNavigate: (page: string, id?: string | number | null) => void;
  liveJobId?: string;
}

const STATUS_LABEL: Record<string, { label: string; classes: string }> = {
  live: { label: '2. Live · Recording', classes: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  awaiting_review: { label: '2. Review transcript', classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  extracting: { label: '3. Extracting Pradip\'s analysis…', classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  awaiting_extract_review: { label: '3. Review extraction', classes: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  bulk_started: { label: 'Sent to Bulk Rationale', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  failed: { label: 'Failed', classes: 'bg-red-500/15 text-red-300 border-red-500/30' },
  completed: { label: 'Completed', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
};
function statusBadge(status: string) {
  const meta = STATUS_LABEL[status] || { label: status, classes: 'bg-slate-500/15 text-slate-300 border-slate-500/30' };
  return <Badge variant="outline" className={`${meta.classes} border`}>{meta.label}</Badge>;
}

export default function LiveTranscribePage({ onNavigate, liveJobId }: Props) {
  const { token } = useAuth();
  const [job, setJob] = useState<LiveJob | null>(null);
  const [loading, setLoading] = useState(!!liveJobId);
  const [saving, setSaving] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [sending, setSending] = useState(false);
  const [videoOpen, setVideoOpen] = useState(false);

  const [diarizedBuffer, setDiarizedBuffer] = useState('');
  const diarizedDirty = useRef(false);
  const diarizedTimer = useRef<number | null>(null);

  const [arrangedBuffer, setArrangedBuffer] = useState('');
  const arrangedDirty = useRef(false);
  const arrangedTimer = useRef<number | null>(null);

  const [activeRightTab, setActiveRightTab] = useState<'live' | 'diarized' | 'arrangement'>('live');

  // ---- Load + poll the job ----
  const loadJob = async () => {
    if (!liveJobId) return;
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.get(liveJobId), {
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Failed to load');
      const fresh: LiveJob = j.job;
      setJob(prev => {
        // Preserve user's in-progress edits while polling.
        if (prev && diarizedDirty.current && prev.status === 'awaiting_review' && fresh.status === 'awaiting_review') {
          return { ...fresh, diarizedTranscript: prev.diarizedTranscript };
        }
        if (prev && arrangedDirty.current && prev.status === 'awaiting_extract_review' && fresh.status === 'awaiting_extract_review') {
          return { ...fresh, arrangedText: prev.arrangedText };
        }
        return fresh;
      });
      if (!diarizedDirty.current) {
        setDiarizedBuffer(fresh.diarizedTranscript || fresh.liveTranscript || '');
      }
      if (!arrangedDirty.current) {
        setArrangedBuffer(fresh.arrangedText || '');
      }
      // Auto-switch right pane to the relevant view as the job progresses.
      if (fresh.status === 'live') setActiveRightTab('live');
      else if (fresh.status === 'awaiting_review' || fresh.status === 'extracting') {
        if (activeRightTab === 'live') setActiveRightTab('diarized');
      } else if (fresh.status === 'awaiting_extract_review' || fresh.status === 'bulk_started') {
        if (activeRightTab !== 'arrangement') setActiveRightTab('arrangement');
      }
    } catch (e: any) {
      toast.error(e.message || 'Failed to load Live Transcribe job');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadJob();
    // State-based polling cadence: fast (2 s) while the server is actively
    // mutating the job (capture worker streaming partials, OpenAI extracting
    // chunks); slow (10 s) once it's parked at a review/terminal state so we
    // don't hammer the backend.
    const isHot = job?.status === 'live' || job?.status === 'extracting';
    const id = window.setInterval(loadJob, isHot ? 2000 : 10000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveJobId, job?.status]);

  // ---- Autosave: diarized review ----
  useEffect(() => {
    if (!job || job.status !== 'awaiting_review') return;
    if (!diarizedDirty.current) return;
    if (diarizedTimer.current) window.clearTimeout(diarizedTimer.current);
    diarizedTimer.current = window.setTimeout(async () => {
      try {
        const r = await fetch(API_ENDPOINTS.liveTranscribe.update(job.jobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ diarizedTranscript: diarizedBuffer }),
        });
        if (r.ok) diarizedDirty.current = false;
      } catch { /* swallow — next typing tick retries */ }
    }, 1200);
    return () => { if (diarizedTimer.current) window.clearTimeout(diarizedTimer.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diarizedBuffer]);

  // ---- Autosave: arranged review ----
  useEffect(() => {
    if (!job || job.status !== 'awaiting_extract_review') return;
    if (!arrangedDirty.current) return;
    if (arrangedTimer.current) window.clearTimeout(arrangedTimer.current);
    arrangedTimer.current = window.setTimeout(async () => {
      try {
        const r = await fetch(API_ENDPOINTS.liveTranscribe.update(job.jobId), {
          method: 'PATCH',
          headers: getAuthHeaders(token || undefined),
          body: JSON.stringify({ arrangedText: arrangedBuffer }),
        });
        if (r.ok) arrangedDirty.current = false;
      } catch { /* swallow */ }
    }, 1200);
    return () => { if (arrangedTimer.current) window.clearTimeout(arrangedTimer.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arrangedBuffer]);

  // ---- Actions ----
  const handleStop = async () => {
    if (!job) return;
    if (!confirm('Stop the live capture now? The diarized re-transcription will start immediately on whatever was captured so far.')) return;
    setStopping(true);
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.stop(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Stop failed');
      toast.success('Live capture stopped — finalising diarized transcript.');
      loadJob();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setStopping(false);
    }
  };

  const handleSaveDiarized = async () => {
    if (!job) return;
    setSaving(true);
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.update(job.jobId), {
        method: 'PATCH',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ diarizedTranscript: diarizedBuffer }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || 'Save failed');
      }
      diarizedDirty.current = false;
      toast.success('Saved');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleExtract = async () => {
    if (!job) return;
    setExtracting(true);
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.extract(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ diarizedTranscript: diarizedBuffer }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Extract failed');
      diarizedDirty.current = false;
      toast.success('Extraction started — review the result when it appears.');
      loadJob();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setExtracting(false);
    }
  };

  const handleSendToBulk = async () => {
    if (!job) return;
    if (!arrangedBuffer.trim()) { toast.error('Arranged text is empty.'); return; }
    setSending(true);
    try {
      const r = await fetch(API_ENDPOINTS.liveTranscribe.sendToBulk(job.jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || undefined),
        body: JSON.stringify({ arrangedText: arrangedBuffer }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Send failed');
      arrangedDirty.current = false;
      toast.success('Sent to Bulk Rationale.');
      loadJob();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSending(false);
    }
  };

  const ytEmbed = useMemo(
    () => job ? getYouTubeEmbedUrl(job.liveUrl, { autoplay: false }) : '',
    [job],
  );

  if (loading) {
    return (
      <div className="p-12 text-center text-muted-foreground">
        <Loader2 className="w-6 h-6 animate-spin inline mr-2" /> Loading…
      </div>
    );
  }
  if (!job) {
    return (
      <div className="p-12 text-center text-muted-foreground">Job not found.</div>
    );
  }

  const errorMsg = job.arrangeError || job.transcribeError || job.diarizeError || '';
  const wordCount = (job.diarizedTranscript || job.liveTranscript || '').trim()
    ? (job.diarizedTranscript || job.liveTranscript || '').trim().split(/\s+/).length : 0;

  return (
    <div className="p-6 space-y-4 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => onNavigate('live-transcribe', null)}>
            <ArrowLeft className="w-4 h-4 mr-1" /> Back to all
          </Button>
          <div>
            <h1 className="text-xl text-foreground flex items-center gap-2">
              <Wifi className="w-5 h-5 text-primary" /> {job.title}
            </h1>
            <div className="text-xs text-muted-foreground mt-0.5">
              {job.channelName} · {job.date} · {job.time}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {statusBadge(job.status)}
          {job.status === 'live' && <Radio className="w-4 h-4 text-rose-300 animate-pulse" />}
        </div>
      </div>

      {/* Step indicator */}
      <Card className="border-border/60">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground flex-wrap">
            <Step n={1} label="Fetch metadata" done />
            <Sep />
            <Step n={2} label="Live capture & review"
              active={job.status === 'live' || job.status === 'awaiting_review'}
              done={job.status !== 'live' && job.status !== 'awaiting_review'} />
            <Sep />
            <Step n={3} label="Extract Pradip's analysis"
              active={job.status === 'extracting' || job.status === 'awaiting_extract_review'}
              done={job.status === 'bulk_started' || job.status === 'completed'} />
            <Sep />
            <Step n={4} label="Send to Bulk Rationale"
              active={job.status === 'bulk_started'} done={job.status === 'completed'} />
          </div>
        </CardContent>
      </Card>

      {errorMsg && job.status === 'failed' && (
        <Alert variant="destructive">
          <AlertTriangle className="w-4 h-4" />
          <AlertTitle>Live Transcribe failed</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap text-xs">{errorMsg}</AlertDescription>
        </Alert>
      )}

      {/* Split view: live YouTube player on left, transcript / extraction on right */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* LEFT — sticky video card. The non-sticky wrapper div lets the
            grid cell stretch so the inner sticky element actually sticks. */}
        <div>
          <div className="lg:sticky lg:top-4 space-y-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <PlayCircle className="w-4 h-4 text-rose-400" /> Live YouTube stream
                </CardTitle>
                <CardDescription className="text-xs">
                  {job.status === 'live'
                    ? 'Server is recording this stream — closing this tab will not stop it.'
                    : 'Stream capture has ended. Review the transcript on the right.'}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {ytEmbed ? (
                  <div className="aspect-video rounded-lg overflow-hidden bg-black">
                    <iframe
                      src={ytEmbed}
                      className="w-full h-full"
                      allow="autoplay; encrypted-media; picture-in-picture"
                      allowFullScreen
                      title={job.title}
                    />
                  </div>
                ) : (
                  <a href={job.liveUrl} target="_blank" rel="noreferrer"
                     className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                    <ExternalLink className="w-4 h-4" /> Open video in new tab
                  </a>
                )}
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs text-muted-foreground">
                    Words captured: {wordCount.toLocaleString()}
                  </div>
                  {job.status === 'live' && (
                    <Button size="sm" variant="destructive" onClick={handleStop} disabled={stopping}>
                      {stopping ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Square className="w-3.5 h-3.5 mr-1" />}
                      Stop capture
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* RIGHT — tabbed views: live, diarized review, extraction review */}
        <div>
          <Card>
            <CardHeader className="pb-2">
              <Tabs value={activeRightTab} onValueChange={(v) => {
                if (v === 'live' || v === 'diarized' || v === 'arrangement') setActiveRightTab(v);
              }}>
                <TabsList>
                  <TabsTrigger value="live">Live transcript</TabsTrigger>
                  <TabsTrigger value="diarized" disabled={!job.diarizedTranscript && job.status === 'live'}>
                    Diarized review
                  </TabsTrigger>
                  <TabsTrigger value="arrangement" disabled={!job.arrangedText && job.status !== 'extracting'}>
                    Pradip's analysis
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="live" className="mt-3 space-y-2">
                  <div className="text-xs text-muted-foreground">
                    Streaming partial captions. The diarized re-transcription
                    runs after the stream ends and replaces this view.
                  </div>
                  <Textarea
                    readOnly
                    value={job.liveTranscript || (job.status === 'live' ? '[Connecting…]' : '')}
                    className="min-h-[420px] font-mono text-sm"
                  />
                </TabsContent>

                <TabsContent value="diarized" className="mt-3 space-y-2">
                  {job.status === 'awaiting_review' && !job.diarizedTranscript && (
                    <div className="text-xs text-amber-300 inline-flex items-center gap-1.5">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Generating speaker-attributed transcript… ETA depends on stream length.
                    </div>
                  )}
                  {job.diarizeError && (
                    <Alert variant="destructive">
                      <AlertTriangle className="w-4 h-4" />
                      <AlertTitle>Diarized transcription failed</AlertTitle>
                      <AlertDescription className="whitespace-pre-wrap text-xs">
                        {job.diarizeError} (You can still extract using the realtime transcript.)
                      </AlertDescription>
                    </Alert>
                  )}
                  <div className="text-xs text-muted-foreground">
                    Edit freely, then click <b>Extract Pradip's analysis</b>. Format: <code>[HH:MM:SS] Speaker A: text</code>.
                  </div>
                  <Textarea
                    value={diarizedBuffer}
                    onChange={(e) => { diarizedDirty.current = true; setDiarizedBuffer(e.target.value); }}
                    className="min-h-[420px] font-mono text-sm"
                    readOnly={job.status !== 'awaiting_review'}
                    placeholder="Diarized transcript will appear here once the stream ends."
                  />
                  {job.status === 'awaiting_review' && (
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="outline" size="sm" onClick={handleSaveDiarized} disabled={saving}>
                        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Save className="w-3.5 h-3.5 mr-1" />}
                        Save
                      </Button>
                      <Button size="sm" onClick={handleExtract} disabled={extracting || !diarizedBuffer.trim()}>
                        {extracting ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Sparkles className="w-3.5 h-3.5 mr-1" />}
                        Extract Pradip's analysis
                      </Button>
                    </div>
                  )}
                </TabsContent>

                <TabsContent value="arrangement" className="mt-3 space-y-2">
                  {job.status === 'extracting' && (
                    <div className="text-xs text-sky-300 inline-flex items-center gap-1.5">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      OpenAI is filtering down to Pradip Halder's analyses (chunked, may take ~1 min per chunk)…
                    </div>
                  )}
                  {job.arrangeError && (
                    <Alert variant="destructive">
                      <AlertTriangle className="w-4 h-4" />
                      <AlertTitle>Extraction failed</AlertTitle>
                      <AlertDescription className="whitespace-pre-wrap text-xs">{job.arrangeError}</AlertDescription>
                    </Alert>
                  )}
                  <div className="text-xs text-muted-foreground">
                    Strict line-pair format for Bulk Rationale: <code>STOCK_NAME ↵ analysis</code>.
                  </div>
                  <Textarea
                    value={arrangedBuffer}
                    onChange={(e) => { arrangedDirty.current = true; setArrangedBuffer(e.target.value); }}
                    className="min-h-[420px] font-mono text-sm"
                    readOnly={job.status !== 'awaiting_extract_review'}
                    placeholder="Pradip's filtered analyses will appear here after extraction."
                  />
                  {job.status === 'awaiting_extract_review' && (
                    <div className="flex items-center justify-end">
                      <Button size="sm" onClick={handleSendToBulk} disabled={sending}>
                        {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Send className="w-3.5 h-3.5 mr-1" />}
                        Send to Bulk Rationale
                      </Button>
                    </div>
                  )}
                  {(job.status === 'bulk_started' || job.bulkJobId) && job.bulkJobId && (
                    <Alert>
                      <CheckCircle2 className="w-4 h-4" />
                      <AlertTitle>Bulk Rationale spawned</AlertTitle>
                      <AlertDescription>
                        <button
                          className="font-mono text-primary hover:underline inline-flex items-center gap-1"
                          onClick={() => onNavigate('bulk-rationale', job.bulkJobId!)}
                        >
                          {job.bulkJobId} <ExternalLink className="w-3 h-3" />
                        </button>
                      </AlertDescription>
                    </Alert>
                  )}
                </TabsContent>
              </Tabs>
            </CardHeader>
            <CardContent />
          </Card>
        </div>
      </div>
    </div>
  );
}

function Step({ n, label, active, done }: { n: number; label: string; active?: boolean; done?: boolean }) {
  const cls = done
    ? 'text-emerald-300'
    : active
      ? 'text-sky-300'
      : 'text-muted-foreground';
  return (
    <div className={`inline-flex items-center gap-1.5 ${cls}`}>
      {done ? <CheckCircle2 className="w-4 h-4" /> : <Circle className={`w-4 h-4 ${active ? 'animate-pulse' : ''}`} />}
      <span className="text-xs"><b>{n}.</b> {label}</span>
    </div>
  );
}
function Sep() { return <span className="text-muted-foreground/40">›</span>; }
