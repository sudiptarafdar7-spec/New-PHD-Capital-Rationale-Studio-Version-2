import { useState, useEffect, useCallback, useRef } from 'react';
import { FileText, CheckCircle2, XCircle, Eye, Download, Plus, Search, Calendar, Video, FileSpreadsheet, PenTool, ExternalLink, Clock, X, ChevronLeft, ChevronRight, FileSignature, Loader2, Layers, Youtube, Facebook, Instagram, Send, MessageCircle, Globe, History, Mic, Wifi, FileAudio } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Label } from '../components/ui/label';
import { Calendar as CalendarComponent } from '../components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger, PopoverAnchor } from '../components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import type { Job, DashboardStats } from '../types';
import { formatIST } from '../lib/datetime';
import JobTitle from '../components/JobTitle';

interface DashboardPageProps {
  onNavigate: (page: string, jobId?: string) => void;
}

const JOBS_PER_PAGE = 100;

interface SearchHistoryEntry {
  query: string;
  last_used: string | null;
}

export default function DashboardPage({ onNavigate }: DashboardPageProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [toolFilter, setToolFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dateFrom, setDateFrom] = useState<Date | undefined>(undefined);
  const [dateTo, setDateTo] = useState<Date | undefined>(undefined);
  const [calendarMonth, setCalendarMonth] = useState<Date>(new Date());
  const [jobs, setJobs] = useState<Job[]>([]);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalJobs, setTotalJobs] = useState(0);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryEntry[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [stats, setStats] = useState<DashboardStats>({
    total_jobs: 0,
    completed_jobs: 0,
    failed_jobs: 0,
    total_change: '+ 0% from last month',
    completed_change: '+ 0% from last month',
    failed_change: '+ 0% from last month'
  });

  const totalPages = Math.max(1, Math.ceil(totalJobs / JOBS_PER_PAGE));

  const fetchDashboardData = useCallback(async () => {
    try {
      const token = localStorage.getItem('token');
      setIsInitialLoading(true);

      const params = new URLSearchParams();
      if (searchQuery) params.append('search', searchQuery);
      if (toolFilter !== 'all') params.append('tool', toolFilter);
      if (statusFilter !== 'all') params.append('status', statusFilter);
      if (dateFrom) params.append('date_from', dateFrom.toISOString().split('T')[0]);
      if (dateTo) params.append('date_to', dateTo.toISOString().split('T')[0]);
      params.append('limit', JOBS_PER_PAGE.toString());
      params.append('offset', String((page - 1) * JOBS_PER_PAGE));

      const response = await fetch(`/api/v1/dashboard?${params.toString()}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setJobs(data.jobs || []);
        setTotalJobs(data.total || 0);
        setStats(data.stats || {
          total_jobs: 0,
          completed_jobs: 0,
          failed_jobs: 0,
          total_change: '+ 0% from last month',
          completed_change: '+ 0% from last month',
          failed_change: '+ 0% from last month'
        });
      } else {
        console.error('Failed to fetch dashboard data');
      }
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
    } finally {
      setIsInitialLoading(false);
    }
  }, [searchQuery, toolFilter, statusFilter, dateFrom, dateTo, page]);

  // Combined effect: reset to page 1 on filter change, otherwise fetch.
  // Avoids the double-fetch race where the old `page` would be used before reset.
  const prevFilterKeyRef = useRef<string>('');
  useEffect(() => {
    const filterKey = `${searchQuery}|${toolFilter}|${statusFilter}|${dateFrom?.toISOString() ?? ''}|${dateTo?.toISOString() ?? ''}`;
    const filtersChanged = prevFilterKeyRef.current !== filterKey;
    prevFilterKeyRef.current = filterKey;

    if (filtersChanged && page !== 1) {
      setPage(1); // re-runs this effect with page=1; skip fetch this pass
      return;
    }
    fetchDashboardData();
  }, [searchQuery, toolFilter, statusFilter, dateFrom, dateTo, page, fetchDashboardData]);

  // Load search history once on mount
  const loadSearchHistory = useCallback(async () => {
    try {
      const token = localStorage.getItem('token');
      const r = await fetch('/api/v1/dashboard/search-history', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const j = await r.json();
        setSearchHistory(j.history || []);
      }
    } catch (e) {
      console.error('Failed to load search history', e);
    }
  }, []);

  useEffect(() => { loadSearchHistory(); }, [loadSearchHistory]);

  // Track last-persisted query to dedupe Enter→blur double-fire.
  const lastPersistedRef = useRef<string>('');
  const persistSearchQuery = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    if (lastPersistedRef.current === trimmed) return; // already saved
    lastPersistedRef.current = trimmed;
    try {
      const token = localStorage.getItem('token');
      await fetch('/api/v1/dashboard/search-history', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ query: trimmed }),
      });
      loadSearchHistory();
    } catch (e) {
      console.error('Failed to save search query', e);
    }
  }, [loadSearchHistory]);

  const removeHistoryItem = async (q: string) => {
    try {
      const token = localStorage.getItem('token');
      await fetch(`/api/v1/dashboard/search-history?query=${encodeURIComponent(q)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      loadSearchHistory();
    } catch (e) {
      console.error('Failed to remove history item', e);
    }
  };

  const clearHistory = async () => {
    try {
      const token = localStorage.getItem('token');
      await fetch('/api/v1/dashboard/search-history', {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      loadSearchHistory();
    } catch (e) {
      console.error('Failed to clear history', e);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'signed':
        return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'completed':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      case 'pdf_ready':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'processing':
      case 'running':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'failed':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      default:
        return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'signed':
        return <CheckCircle2 className="w-4 h-4" />;
      case 'completed':
        return <FileText className="w-4 h-4" />;
      case 'pdf_ready':
        return <FileText className="w-4 h-4" />;
      case 'failed':
        return <XCircle className="w-4 h-4" />;
      case 'processing':
      case 'running':
        return <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />;
      default:
        return <Clock className="w-4 h-4" />;
    }
  };

  const getToolIcon = (tool: string) => {
    switch (tool) {
      case 'Media Rationale':
        return <Video className="w-4 h-4" />;
      case 'Premium Rationale':
        return <FileSpreadsheet className="w-4 h-4" />;
      case 'Manual Rationale':
        return <PenTool className="w-4 h-4" />;
      case 'Bulk Rationale':
        return <Layers className="w-4 h-4" />;
      case 'Voice Typing':
        return <Mic className="w-4 h-4" />;
      case 'AI Transcribe':
        return <FileAudio className="w-4 h-4" />;
      case 'Live Transcribe':
        return <Wifi className="w-4 h-4" />;
      default:
        return <FileText className="w-4 h-4" />;
    }
  };

  const getToolColor = (tool: string) => {
    switch (tool) {
      case 'Media Rationale':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'Premium Rationale':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      case 'Manual Rationale':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'Bulk Rationale':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'Voice Typing':
        return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30';
      case 'AI Transcribe':
        return 'bg-teal-500/20 text-teal-400 border-teal-500/30';
      case 'Live Transcribe':
        return 'bg-rose-500/20 text-rose-400 border-rose-500/30';
      default:
        return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  };

  const formatDateTime = (dateString: string) => formatIST(dateString);

  const getPlatformIcon = (platform?: string) => {
    const p = (platform || 'youtube').toLowerCase();
    switch (p) {
      case 'youtube':
        return <Youtube className="w-5 h-5 text-red-500" />;
      case 'facebook':
        return <Facebook className="w-5 h-5 text-blue-500" />;
      case 'instagram':
        return <Instagram className="w-5 h-5 text-pink-500" />;
      case 'telegram':
        return <Send className="w-5 h-5 text-sky-500" />;
      case 'whatsapp':
        return <MessageCircle className="w-5 h-5 text-emerald-500" />;
      default:
        return <Globe className="w-5 h-5 text-slate-400" />;
    }
  };

  const getPlatformLabel = (platform?: string) => {
    const p = (platform || 'youtube').toLowerCase();
    return p.charAt(0).toUpperCase() + p.slice(1);
  };

  // Jobs are already filtered by backend API
  const filteredJobs = jobs;

  const handleResetFilters = () => {
    setSearchQuery('');
    setToolFilter('all');
    setStatusFilter('all');
    setDateFrom(undefined);
    setDateTo(undefined);
  };

  const hasActiveFilters = searchQuery || toolFilter !== 'all' || statusFilter !== 'all' || dateFrom || dateTo;

  const handleViewDetails = (jobId: string, toolUsed?: string) => {
    // Normalize tool_used to handle both snake_case and Title Case
    const normalizedTool = toolUsed?.toLowerCase().replace(/\s+/g, '_');
    
    // Navigate to the correct tool page based on tool_used or job ID prefix
    if (normalizedTool === 'premium_rationale' || jobId.startsWith('premium-')) {
      onNavigate('premium-rationale', jobId);
    } else if (normalizedTool === 'manual_rationale' || jobId.startsWith('manual-')) {
      onNavigate('manual-rationale', jobId);
    } else if (normalizedTool === 'bulk_rationale' || jobId.startsWith('bulk-')) {
      onNavigate('bulk-rationale', jobId);
    } else if (normalizedTool === 'ai_transcribe' || jobId.startsWith('aitr-')) {
      onNavigate('ai-transcribe', jobId);
    } else if (normalizedTool === 'voice_typing' || jobId.startsWith('voice-')) {
      onNavigate('voice-typing', jobId);
    } else if (normalizedTool === 'live_transcribe' || jobId.startsWith('live-')) {
      onNavigate('live-transcribe', jobId);
    } else {
      // Default to media-rationale
      onNavigate('media-rationale', jobId);
    }
  };

  const handleDownloadPDF = async (jobId: string, signed: boolean = false) => {
    try {
      setDownloadingId(jobId);
      const token = localStorage.getItem('token');
      
      // Determine API endpoint based on job ID prefix
      const apiEndpoint = jobId.startsWith('premium-') 
        ? `/api/v1/premium-rationale/jobs/${jobId}`
        : `/api/v1/media-rationale/job/${jobId}`;
      
      // Fetch job data to get PDF path from saved_rationale table
      const jobResponse = await fetch(apiEndpoint, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      
      if (!jobResponse.ok) {
        console.error('Failed to fetch job data');
        return;
      }
      
      const jobData = await jobResponse.json();
      let pdfPath = null;
      
      if (signed) {
        // Try both camelCase and snake_case
        pdfPath = jobData.job?.signedPdfPath || jobData.job?.signed_pdf_path;
      } else {
        // For unsigned, try saved_rationale first, then fallback to Step 14
        pdfPath = jobData.job?.unsignedPdfPath || jobData.job?.unsigned_pdf_path;
        if (!pdfPath) {
          // Fallback to Step 14 output for pdf_ready status
          const step14 = jobData.job?.steps?.find((s: any) => s.step_number === 14);
          const outputFiles = step14?.outputFiles || step14?.output_files || [];
          if (outputFiles.length > 0) {
            pdfPath = outputFiles.find((f: string) => f.endsWith('.pdf'));
          }
        }
      }
      
      if (!pdfPath) {
        console.error('PDF path not found');
        return;
      }
      
      const response = await fetch(`/api/v1/saved-rationale/download/${encodeURIComponent(pdfPath)}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `rationale_${jobId}_${signed ? 'signed' : 'unsigned'}.pdf`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      } else {
        console.error('Failed to download PDF');
      }
    } catch (error) {
      console.error('Error downloading PDF:', error);
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl text-foreground mb-1">Dashboard</h1>
          <p className="text-sm sm:text-base text-muted-foreground">Overview of your rationale generation jobs</p>
        </div>
        <Button
          onClick={() => onNavigate('bulk-rationale')}
          className="gradient-primary shadow-lg glow-primary w-full sm:w-auto h-11"
        >
          <Plus className="w-4 h-4 mr-2" />
          New Rationale
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <Card className="premium-card group">
          <div className="p-5 sm:p-6">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <p className="text-muted-foreground text-sm mb-2">Total Jobs</p>
                <p className="text-3xl sm:text-4xl text-foreground mb-1.5">{stats.total_jobs}</p>
                <p className="text-sm text-green-500 flex items-center gap-1">
                  {stats.total_change}
                </p>
              </div>
              <div className="p-3 icon-bg-primary rounded-xl transition-all group-hover:scale-110">
                <FileText className="w-6 h-6 text-blue-500" />
              </div>
            </div>
          </div>
        </Card>

        <Card className="premium-card group">
          <div className="p-5 sm:p-6">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <p className="text-muted-foreground text-sm mb-2">Completed</p>
                <p className="text-3xl sm:text-4xl text-foreground mb-1.5">{stats.completed_jobs}</p>
                <p className="text-sm text-green-500 flex items-center gap-1">
                  {stats.completed_change}
                </p>
              </div>
              <div className="p-3 icon-bg-success rounded-xl transition-all group-hover:scale-110">
                <CheckCircle2 className="w-6 h-6 text-green-500" />
              </div>
            </div>
          </div>
        </Card>

        <Card className="premium-card group">
          <div className="p-5 sm:p-6">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <p className="text-muted-foreground text-sm mb-2">Failed</p>
                <p className="text-3xl sm:text-4xl text-foreground mb-1.5">{stats.failed_jobs}</p>
                <p className="text-sm text-red-500 flex items-center gap-1">
                  {stats.failed_change}
                </p>
              </div>
              <div className="p-3 icon-bg-danger rounded-xl transition-all group-hover:scale-110">
                <XCircle className="w-6 h-6 text-red-500" />
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Recent Jobs */}
      <Card className="premium-card overflow-hidden">
        <div className="p-5 sm:p-6 border-b border-border bg-gradient-to-r from-blue-500/5 to-transparent">
          <h2 className="text-xl text-foreground flex items-center gap-2">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <FileText className="w-5 h-5 text-blue-500" />
            </div>
            Recent Jobs
          </h2>
        </div>

        {/* Advanced Filters */}
        <div className="p-4 sm:p-6 border-b border-border space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3 sm:gap-4">
            {/* Search with history */}
            <div className="md:col-span-2 xl:col-span-2 space-y-1.5">
              <Label className="text-xs text-muted-foreground">Search</Label>
              <Popover open={historyOpen} onOpenChange={setHistoryOpen}>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <PopoverAnchor asChild>
                    <Input
                      ref={searchInputRef}
                      placeholder="Search by video title, URL, or Job ID..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onFocus={() => { if (searchHistory.length) setHistoryOpen(true); }}
                      onClick={() => { if (searchHistory.length) setHistoryOpen(true); }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && searchQuery.trim()) {
                          persistSearchQuery(searchQuery);
                          setHistoryOpen(false);
                        } else if (e.key === 'Escape') {
                          setHistoryOpen(false);
                        }
                      }}
                      onBlur={() => {
                        if (searchQuery.trim()) persistSearchQuery(searchQuery);
                      }}
                      className="pl-10 pr-9 bg-background border-input text-foreground text-sm"
                    />
                  </PopoverAnchor>
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-accent text-muted-foreground"
                      aria-label="Clear search"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
                <PopoverContent
                  align="start"
                  className="w-[--radix-popover-trigger-width] p-0"
                  onOpenAutoFocus={(e: Event) => e.preventDefault()}
                  onPointerDownOutside={(e) => {
                    if (searchInputRef.current && e.target instanceof Node && searchInputRef.current.contains(e.target)) {
                      e.preventDefault();
                    }
                  }}
                  onFocusOutside={(e) => {
                    if (searchInputRef.current && e.target instanceof Node && searchInputRef.current.contains(e.target)) {
                      e.preventDefault();
                    }
                  }}
                >
                  <div className="px-3 py-2 border-b border-border flex items-center justify-between">
                    <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                      <History className="w-3.5 h-3.5" />
                      Recent searches
                    </div>
                    {searchHistory.length > 0 && (
                      <button
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); clearHistory(); }}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
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
                          <button
                            type="button"
                            onMouseDown={(e) => {
                              e.preventDefault();
                              setSearchQuery(h.query);
                              persistSearchQuery(h.query);
                              setHistoryOpen(false);
                            }}
                            className="flex-1 text-left flex items-center gap-2 truncate"
                          >
                            <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                            <span className="truncate text-foreground">{h.query}</span>
                          </button>
                          <button
                            type="button"
                            onMouseDown={(e) => { e.preventDefault(); removeHistoryItem(h.query); }}
                            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-background text-muted-foreground"
                            aria-label="Remove from history"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </PopoverContent>
              </Popover>
            </div>

            {/* Tool Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Filter by Tool</Label>
              <Select value={toolFilter} onValueChange={setToolFilter}>
                <SelectTrigger className="bg-background border-input text-foreground">
                  <SelectValue placeholder="All Tools" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    All Tools
                  </SelectItem>
                  <SelectItem value="premium" className="text-foreground focus:bg-accent focus:text-accent-foreground">
                    <div className="flex items-center gap-2">
                      <FileSpreadsheet className="w-4 h-4 text-purple-500" />
                      Premium Rationale
                    </div>
                  </SelectItem>
                  <SelectItem value="manual" className="text-foreground focus:bg-accent focus:text-accent-foreground">
                    <div className="flex items-center gap-2">
                      <PenTool className="w-4 h-4 text-green-500" />
                      Manual Rationale
                    </div>
                  </SelectItem>
                  <SelectItem value="bulk" className="text-foreground focus:bg-accent focus:text-accent-foreground">
                    <div className="flex items-center gap-2">
                      <Layers className="w-4 h-4 text-orange-500" />
                      Bulk Rationale
                    </div>
                  </SelectItem>
                  <SelectItem value="voice_typing" className="text-foreground focus:bg-accent focus:text-accent-foreground">
                    <div className="flex items-center gap-2">
                      <Mic className="w-4 h-4 text-cyan-500" />
                      Voice Typing
                    </div>
                  </SelectItem>
                  <SelectItem value="ai_transcribe" className="text-foreground focus:bg-accent focus:text-accent-foreground">
                    <div className="flex items-center gap-2">
                      <FileAudio className="w-4 h-4 text-teal-500" />
                      AI Transcribe
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Status Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Filter by Status</Label>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="bg-background border-input text-foreground">
                  <SelectValue placeholder="All Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    All Status
                  </SelectItem>
                  <SelectItem value="running">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4 text-blue-500" />
                      Running
                    </div>
                  </SelectItem>
                  <SelectItem value="pdf_ready">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-green-500" />
                      PDF Ready
                    </div>
                  </SelectItem>
                  <SelectItem value="completed">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-amber-500" />
                      Completed
                    </div>
                  </SelectItem>
                  <SelectItem value="signed">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      Signed
                    </div>
                  </SelectItem>
                  <SelectItem value="failed">
                    <div className="flex items-center gap-2">
                      <XCircle className="w-4 h-4 text-red-500" />
                      Failed
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Date Range Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Date Range</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    className="w-full justify-start text-left bg-background border-input text-foreground hover:bg-accent hover:text-accent-foreground"
                  >
                    <Calendar className="mr-2 h-4 w-4 text-muted-foreground" />
                    {dateFrom ? (
                      dateTo ? (
                        <span className="text-foreground">
                          {dateFrom.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - {dateTo.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                        </span>
                      ) : (
                        <span className="text-foreground">{dateFrom.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                      )
                    ) : (
                      <span className="text-muted-foreground">Pick a date</span>
                    )}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <div className="p-3">
                    {(dateFrom || dateTo) && (
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setDateFrom(undefined);
                          setDateTo(undefined);
                        }}
                        className="w-full mb-2"
                      >
                        <X className="w-4 h-4 mr-2" />
                        Clear dates
                      </Button>
                    )}

                    {/* Month and Year Navigation */}
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const newDate = new Date(calendarMonth);
                          newDate.setMonth(newDate.getMonth() - 1);
                          setCalendarMonth(newDate);
                        }}
                        className="h-8 w-8 p-0"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>

                      <div className="flex gap-2">
                        <Select
                          value={calendarMonth.getMonth().toString()}
                          onValueChange={(value) => {
                            const newDate = new Date(calendarMonth);
                            newDate.setMonth(parseInt(value));
                            setCalendarMonth(newDate);
                          }}
                        >
                          <SelectTrigger className="h-8 w-[110px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {[
                              'January', 'February', 'March', 'April', 'May', 'June',
                              'July', 'August', 'September', 'October', 'November', 'December'
                            ].map((month, index) => (
                              <SelectItem 
                                key={index} 
                                value={index.toString()}
                              >
                                {month}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>

                        <Select
                          value={calendarMonth.getFullYear().toString()}
                          onValueChange={(value) => {
                            const newDate = new Date(calendarMonth);
                            newDate.setFullYear(parseInt(value));
                            setCalendarMonth(newDate);
                          }}
                        >
                          <SelectTrigger className="h-8 w-[80px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {Array.from({ length: 10 }, (_, i) => new Date().getFullYear() - i).map((year) => (
                              <SelectItem 
                                key={year} 
                                value={year.toString()}
                              >
                                {year}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const newDate = new Date(calendarMonth);
                          newDate.setMonth(newDate.getMonth() + 1);
                          setCalendarMonth(newDate);
                        }}
                        className="h-8 w-8 p-0"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>

                    <CalendarComponent
                      mode="range"
                      selected={{ from: dateFrom, to: dateTo }}
                      onSelect={(range) => {
                        setDateFrom(range?.from);
                        setDateTo(range?.to);
                      }}
                      month={calendarMonth}
                      onMonthChange={setCalendarMonth}
                      numberOfMonths={1}
                      hideNavigation={true}
                      className="rounded-md"
                    />
                  </div>
                </PopoverContent>
              </Popover>
            </div>
          </div>

          {/* Active Filters & Clear Button */}
          {hasActiveFilters && (
            <div className="flex items-center justify-between pt-2 border-t border-border">
              <div className="flex items-center gap-2 text-sm text-muted-foreground flex-wrap">
                <span>Active filters:</span>
                {searchQuery && (
                  <Badge variant="outline">
                    Search: "{searchQuery}"
                  </Badge>
                )}
                {toolFilter !== 'all' && (
                  <Badge variant="outline">
                    Tool: {toolFilter === 'media' ? 'Media Rationale' : toolFilter === 'premium' ? 'Premium Rationale' : 'Manual Rationale'}
                  </Badge>
                )}
                {statusFilter !== 'all' && (
                  <Badge variant="outline">
                    Status: {statusFilter}
                  </Badge>
                )}
                {(dateFrom || dateTo) && (
                  <Badge variant="outline">
                    Date: {dateFrom?.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                    {dateTo && ` - ${dateTo.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`}
                  </Badge>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleResetFilters}
              >
                <X className="w-4 h-4 mr-1" />
                Clear All
              </Button>
            </div>
          )}
        </div>

        {/* Jobs List */}
        <div className="divide-y divide-border">
          {isInitialLoading ? (
            <div className="p-12 text-center text-muted-foreground">
              <Loader2 className="w-12 h-12 mx-auto mb-4 animate-spin text-blue-500" />
              <p>Loading jobs...</p>
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className="p-12 text-center text-muted-foreground">
              <FileText className="w-16 h-16 mx-auto mb-4 opacity-50" />
              <p>No jobs found</p>
              <p className="text-sm mt-2">Try adjusting your search or filter criteria</p>
            </div>
          ) : (
            filteredJobs.map((job) => (
              <div key={job.id} className="p-4 sm:p-6 hover:bg-gradient-to-r hover:from-blue-500/5 hover:to-transparent transition-all duration-300 border-l-2 border-transparent hover:border-blue-500">
                <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
                  {/* Left Side: Job Info */}
                  <div className="flex gap-3 sm:gap-4 flex-1 min-w-0">
                    {/* Tool icon (Media / Premium / Manual / Bulk / Transcript / Voice Typing).
                        The platform brand icon now lives inside <JobTitle> below, so the
                        big left badge represents WHICH TOOL produced the job instead of
                        duplicating the platform icon. */}
                    <div
                      className={`p-2.5 rounded-xl h-fit shrink-0 border ${getToolColor(job.tool_used || '')}`}
                      title={job.tool_used || 'Job'}
                    >
                      {getToolIcon(job.tool_used || '')}
                    </div>
                    <div className="flex-1 min-w-0 space-y-2 sm:space-y-3">
                      {/* Status only (no Job ID) */}
                      <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
                        <Badge className={getStatusColor(job.status)}>
                          <span className="flex items-center gap-1 sm:gap-1.5 text-xs sm:text-sm">
                            {getStatusIcon(job.status)}
                            {job.status.charAt(0).toUpperCase() + job.status.slice(1)}
                          </span>
                        </Badge>
                        <Badge className={getToolColor(job.tool_used)}>
                          <span className="flex items-center gap-1.5">
                            {getToolIcon(job.tool_used)}
                            {job.tool_used}
                          </span>
                        </Badge>
                      </div>

                      {/* Unified job title: [icon] Channel - DD-MM-YYYY - HH:MM */}
                      <div>
                        <a
                          href={job.youtube_url || '#'}
                          target={job.youtube_url ? '_blank' : undefined}
                          rel="noopener noreferrer"
                          onClick={(e) => { if (!job.youtube_url) e.preventDefault(); }}
                          className="text-foreground hover:text-blue-500 transition-colors inline-flex items-center gap-2 group"
                        >
                          <JobTitle
                            platform={job.platform}
                            channelName={job.channel_name}
                            date={job.date}
                            time={job.time}
                            fallback={job.title}
                          />
                          {job.youtube_url && (
                            <ExternalLink className="w-4 h-4 text-muted-foreground group-hover:text-blue-500" />
                          )}
                        </a>
                      </div>

                      {/* Created-at timestamp (in IST) */}
                      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Clock className="w-3.5 h-3.5" />
                          <span className="text-foreground">{formatDateTime(job.created_at)}</span>
                        </div>
                      </div>

                      {/* Progress Bar for Running/Processing Jobs */}
                      {(job.status === 'running' || job.status === 'processing') && (
                        <div>
                          <div className="flex items-center justify-between text-sm mb-1.5">
                            <span className="text-muted-foreground">Progress</span>
                            <span className="text-blue-500">{job.progress}%</span>
                          </div>
                          <div className="w-full bg-muted rounded-full h-2">
                            <div
                              className="bg-gradient-to-r from-blue-500 to-blue-600 h-2 rounded-full transition-all duration-300"
                              style={{ width: `${job.progress}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Right Side: Action Buttons */}
                  <div className="flex flex-row gap-2 w-full lg:w-auto lg:flex-col shrink-0">
                    <Button
                      size="sm"
                      onClick={() => handleViewDetails(job.id, job.tool_used)}
                      data-tour={`job-view-${job.id}`}
                      className="gradient-primary active:scale-95 transition-all duration-200 hover:shadow-lg flex-1 sm:flex-initial lg:min-w-[140px] h-9"
                    >
                      <Eye className="w-4 h-4 mr-1.5" />
                      <span className="hidden sm:inline">View Details</span>
                      <span className="sm:hidden">View</span>
                    </Button>
                    
                    {/* Signed: Download Signed PDF */}
                    {job.status === 'signed' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleDownloadPDF(job.id, true)}
                        disabled={downloadingId === job.id}
                        className="border-purple-500/50 text-purple-500 hover:bg-purple-500 hover:text-white hover:border-purple-500 active:scale-95 transition-all duration-200 hover:shadow-lg flex-1 sm:flex-initial lg:min-w-[140px] h-9 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {downloadingId === job.id ? (
                          <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                        ) : (
                          <Download className="w-4 h-4 mr-1.5" />
                        )}
                        <span>Signed</span>
                      </Button>
                    )}
                    
                    {/* Completed: Download Unsigned PDF + Sign Now */}
                    {job.status === 'completed' && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleDownloadPDF(job.id, false)}
                          disabled={downloadingId === job.id}
                          className="border-blue-500/50 text-blue-500 hover:bg-blue-500 hover:text-white hover:border-blue-500 active:scale-95 transition-all duration-200 hover:shadow-lg flex-1 sm:flex-initial lg:min-w-[140px] h-9 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {downloadingId === job.id ? (
                            <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                          ) : (
                            <Download className="w-4 h-4 mr-1.5" />
                          )}
                          <span>Unsigned</span>
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleViewDetails(job.id, job.tool_used)}
                          data-tour={`job-view-${job.id}`}
                          className="border-green-500/50 text-green-500 hover:bg-green-500 hover:text-white hover:border-green-500 active:scale-95 transition-all duration-200 hover:shadow-lg flex-1 sm:flex-initial lg:min-w-[140px] h-9"
                        >
                          <FileSignature className="w-4 h-4 mr-1.5" />
                          <span className="hidden sm:inline">Sign Now</span>
                          <span className="sm:hidden">Sign</span>
                        </Button>
                      </>
                    )}
                    
                    {/* PDF Ready: Download PDF */}
                    {job.status === 'pdf_ready' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleDownloadPDF(job.id, false)}
                        disabled={downloadingId === job.id}
                        className="border-blue-500/50 text-blue-500 hover:bg-blue-500 hover:text-white hover:border-blue-500 active:scale-95 transition-all duration-200 hover:shadow-lg flex-1 sm:flex-initial lg:min-w-[140px] h-9 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {downloadingId === job.id ? (
                          <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                        ) : (
                          <Download className="w-4 h-4 mr-1.5" />
                        )}
                        <span>Unsigned</span>
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
          
          {/* Pagination — 100 jobs per page */}
          {!isInitialLoading && totalJobs > 0 && (
            <div className="p-4 sm:p-6 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-border">
              <p className="text-sm text-muted-foreground">
                Showing{' '}
                <span className="text-foreground">
                  {(page - 1) * JOBS_PER_PAGE + 1}
                  {'–'}
                  {Math.min(page * JOBS_PER_PAGE, totalJobs)}
                </span>{' '}
                of <span className="text-foreground">{totalJobs}</span> jobs
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="w-4 h-4 mr-1" />
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground px-2">
                  Page <span className="text-foreground">{page}</span> of {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Next
                  <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
