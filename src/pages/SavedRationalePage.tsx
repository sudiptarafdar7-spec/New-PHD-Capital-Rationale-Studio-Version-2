import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { formatDateIST } from '@/lib/datetime';
import { FileText, Download, Upload, Eye, Search, Calendar, Filter, ExternalLink, PlayCircle, ChevronLeft, ChevronRight, X, Video, FileSpreadsheet, PenTool, CheckCircle, Loader2 } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Label } from '../components/ui/label';
import { Calendar as CalendarComponent } from '../components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '../components/ui/popover';
import { PlatformIcon } from '../components/JobTitle';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';

interface SavedRationale {
  id: string;
  job_id: string;
  title: string;
  date: string;
  youtube_url: string | null;
  channel_name: string;
  channel_url: string;
  platform: string;
  tool_used: string;
  unsigned_pdf_path: string;
  signed_pdf_path: string | null;
  signed_uploaded_at: string | null;
  created_at: string;
}

interface SavedRationalePageProps {
  onNavigate?: (page: string, jobId?: string) => void;
}

export default function SavedRationalePage({ onNavigate }: SavedRationalePageProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterTool, setFilterTool] = useState<string>('all');
  const [filterChannel, setFilterChannel] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [dateFrom, setDateFrom] = useState<Date | undefined>(undefined);
  const [dateTo, setDateTo] = useState<Date | undefined>(undefined);
  const [calendarMonth, setCalendarMonth] = useState<Date>(new Date());
  const [rationales, setRationales] = useState<SavedRationale[]>([]);
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [uploadingId, setUploadingId] = useState<string | null>(null);

  // Fetch saved rationales from backend
  const fetchRationales = useCallback(async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      const response = await fetch('/api/v1/saved-rationale', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setRationales(data.rationales || []);
      } else {
        console.error('Failed to fetch saved rationales');
        toast.error('Failed to load saved rationales');
      }
    } catch (error) {
      console.error('Error fetching saved rationales:', error);
      toast.error('Error loading saved rationales');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRationales();
  }, [fetchRationales]);

  // Get unique channels for filters
  const uniqueChannels = useMemo(() => {
    const channels = new Set(rationales.map(r => r.channel_name).filter(Boolean));
    return Array.from(channels);
  }, [rationales]);

  // Filter rationales
  const filteredRationales = useMemo(() => {
    return rationales.filter(rationale => {
      const matchesSearch = 
        (rationale.title || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (rationale.channel_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (rationale.job_id || '').toLowerCase().includes(searchQuery.toLowerCase());
      
      const matchesTool = filterTool === 'all' || rationale.tool_used === filterTool;
      const matchesChannel = filterChannel === 'all' || rationale.channel_name === filterChannel;
      
      // Status filter
      const matchesStatus = filterStatus === 'all' || 
        (filterStatus === 'signed' && rationale.signed_pdf_path) ||
        (filterStatus === 'unsigned' && !rationale.signed_pdf_path);
      
      // Date range filter
      const rationaleDate = rationale.date ? new Date(rationale.date) : new Date();
      const matchesDateFrom = !dateFrom || rationaleDate >= dateFrom;
      const matchesDateTo = !dateTo || rationaleDate <= new Date(dateTo.getTime() + 86400000); // Add 1 day to include the end date

      return matchesSearch && matchesTool && matchesChannel && matchesStatus && matchesDateFrom && matchesDateTo;
    });
  }, [searchQuery, filterTool, filterChannel, filterStatus, dateFrom, dateTo, rationales]);

  const handleUploadSigned = async (jobId: string) => {
    // Create a file input element
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf';
    input.onchange = async (e: Event) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        try {
          setUploadingId(jobId);
          const token = localStorage.getItem('token');
          const formData = new FormData();
          formData.append('signed_pdf', file);
          formData.append('job_id', jobId);

          const response = await fetch('/api/v1/saved-rationale/upload-signed', {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${token}`,
            },
            body: formData,
          });

          if (response.ok) {
            toast.success('Signed PDF uploaded successfully', {
              description: `${file.name} has been saved.`,
            });
            // Refresh the list to show updated status
            fetchRationales();
          } else {
            toast.error('Failed to upload signed PDF');
          }
        } catch (error) {
          console.error('Error uploading signed PDF:', error);
          toast.error('Error uploading signed PDF');
        } finally {
          setUploadingId(null);
        }
      }
    };
    input.click();
  };

  const handleDownload = async (path: string, type: 'unsigned' | 'signed', id: string) => {
    try {
      setDownloadingId(`${id}-${type}`);
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/v1/saved-rationale/download/${encodeURIComponent(path)}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${type}_rationale_report.pdf`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        toast.success(`${type.charAt(0).toUpperCase() + type.slice(1)} PDF downloaded successfully`);
      } else {
        toast.error(`Failed to download ${type} PDF`);
      }
    } catch (error) {
      console.error(`Error downloading ${type} PDF:`, error);
      toast.error(`Error downloading ${type} PDF`);
    } finally {
      setDownloadingId(null);
    }
  };

  const handleViewJob = (jobId: string, toolUsed: string) => {
    // Navigate to the appropriate page based on tool used
    if (!onNavigate) return;
    
    // Normalize tool_used to handle both snake_case and Title Case formats
    const normalizedTool = toolUsed.toLowerCase().replace(/ /g, '_');
    
    if (normalizedTool === 'media_rationale') {
      onNavigate('media-rationale', jobId);
    } else if (normalizedTool === 'premium_rationale') {
      onNavigate('premium-rationale', jobId);
    } else if (normalizedTool === 'manual_rationale') {
      onNavigate('manual-rationale', jobId);
    }
  };

  const formatDate = (dateString: string) => {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) return 'Invalid Date';
      return formatDateIST(date);
    } catch (error) {
      return 'Invalid Date';
    }
  };

  const formatVideoDate = (dateString: string) => {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) return 'N/A';
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    } catch (error) {
      return 'N/A';
    }
  };

  const getToolBadgeColor = (tool: string) => {
    switch (tool) {
      case 'Media Rationale':
        return 'bg-blue-500/20 text-blue-500 border-blue-500/30';
      case 'Premium Rationale':
        return 'bg-purple-500/20 text-purple-500 border-purple-500/30';
      case 'Manual Rationale':
        return 'bg-green-500/20 text-green-500 border-green-500/30';
      default:
        return 'bg-muted text-muted-foreground border-border';
    }
  };

  const handleResetFilters = () => {
    setSearchQuery('');
    setFilterTool('all');
    setFilterChannel('all');
    setFilterStatus('all');
    setDateFrom(undefined);
    setDateTo(undefined);
  };

  return (
    <div className="p-3 md:p-6 space-y-4 md:space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-xl md:text-2xl text-foreground mb-1">Saved Rationale</h1>
        <p className="text-sm md:text-base text-muted-foreground">View and manage all generated rationale reports</p>
      </div>

      {/* Search and Filters */}
      <Card className="bg-card border-border p-3 md:p-4 shadow-sm">
        <div className="space-y-3 md:space-y-4">
          {/* Search Bar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search videos, stocks, channels..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-background border-input text-foreground placeholder:text-muted-foreground text-sm md:text-base"
            />
          </div>

          {/* Filters Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5 md:gap-3">
            {/* Tool Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Filter by Tool</Label>
              <Select value={filterTool} onValueChange={setFilterTool}>
                <SelectTrigger className="bg-background border-input text-foreground">
                  <SelectValue placeholder="All Tools" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    <div className="flex items-center gap-2">
                      <Filter className="w-4 h-4 text-muted-foreground" />
                      <span>All Tools</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="Media Rationale">
                    <div className="flex items-center gap-2">
                      <Video className="w-4 h-4 text-blue-500" />
                      <span>Media Rationale</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="Premium Rationale">
                    <div className="flex items-center gap-2">
                      <FileSpreadsheet className="w-4 h-4 text-purple-500" />
                      <span>Premium Rationale</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="Manual Rationale">
                    <div className="flex items-center gap-2">
                      <PenTool className="w-4 h-4 text-green-500" />
                      <span>Manual Rationale</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Channel Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Filter by Channel</Label>
              <Select value={filterChannel} onValueChange={setFilterChannel}>
                <SelectTrigger className="bg-background border-input text-foreground">
                  <SelectValue placeholder="All Channels" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    All Channels
                  </SelectItem>
                  {uniqueChannels.map(channel => (
                    <SelectItem 
                      key={channel} 
                      value={channel}
                    >
                      {channel}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Status Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Filter by Status</Label>
              <Select value={filterStatus} onValueChange={setFilterStatus}>
                <SelectTrigger className="bg-background border-input text-foreground">
                  <SelectValue placeholder="All Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    <div className="flex items-center gap-2">
                      <Filter className="w-4 h-4 text-muted-foreground" />
                      <span>All Status</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="signed">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="w-4 h-4 text-emerald-500" />
                      <span>Signed</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="unsigned">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-amber-500" />
                      <span>Unsigned</span>
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
                    {dateFrom || dateTo ? (
                      <span className="text-foreground">
                        {dateFrom?.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                        {dateTo && ` - ${dateTo.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">Select date range</span>
                    )}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <div className="p-4 space-y-3">
                    <div className="flex items-center justify-between mb-2">
                      <Label className="text-sm text-foreground">Select Date Range</Label>
                      {(dateFrom || dateTo) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setDateFrom(undefined);
                            setDateTo(undefined);
                          }}
                          className="h-7 text-xs text-muted-foreground hover:text-foreground"
                        >
                          Clear
                        </Button>
                      )}
                    </div>

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
                          <SelectTrigger className="h-8 w-[90px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent className="max-h-[200px]">
                            {Array.from({ length: 20 }, (_, i) => new Date().getFullYear() - i).map((year) => (
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
                      className="rounded-lg"
                    />
                  </div>
                </PopoverContent>
              </Popover>
            </div>

            {/* Reset Filters Button */}
            <div className="space-y-1.5">
              <Label className="text-xs text-transparent select-none">Actions</Label>
              <Button
                variant="outline"
                onClick={handleResetFilters}
                className="w-full border-primary/50 text-primary hover:bg-primary hover:text-white hover:border-primary"
              >
                <X className="w-4 h-4 mr-2" />
                Clear Filters
              </Button>
            </div>
          </div>

          {/* Active Filters Display */}
          {(filterTool !== 'all' || filterChannel !== 'all' || filterStatus !== 'all' || dateFrom || dateTo || searchQuery) && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground flex-wrap">
              <span>Active filters:</span>
              {searchQuery && (
                <Badge variant="outline" className="border-border text-foreground">
                  Search: "{searchQuery}"
                </Badge>
              )}
              {filterTool !== 'all' && (
                <Badge variant="outline" className="border-border text-foreground">
                  Tool: {filterTool}
                </Badge>
              )}
              {filterChannel !== 'all' && (
                <Badge variant="outline" className="border-border text-foreground">
                  Channel: {filterChannel}
                </Badge>
              )}
              {filterStatus !== 'all' && (
                <Badge variant="outline" className="border-border text-foreground">
                  Status: {filterStatus}
                </Badge>
              )}
              {(dateFrom || dateTo) && (
                <Badge variant="outline" className="border-border text-foreground">
                  Date: {dateFrom?.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                  {dateTo && ` - ${dateTo.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`}
                </Badge>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg md:text-xl text-foreground">
          All Rationale Reports 
          <span className="text-muted-foreground ml-2 text-sm md:text-base">({filteredRationales.length})</span>
        </h2>
      </div>

      {/* Rationale List */}
      {loading ? (
        <div className="border-2 border-dashed border-border rounded-xl p-12 text-center bg-muted/50">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-foreground mb-1.5">Loading saved rationales...</p>
          <p className="text-sm text-muted-foreground">Please wait while we fetch your reports</p>
        </div>
      ) : filteredRationales.length === 0 ? (
        <div className="border-2 border-dashed border-border rounded-xl p-12 text-center bg-muted/50">
          <FileText className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <p className="text-foreground mb-1.5">No rationale reports found</p>
          <p className="text-sm text-muted-foreground">Try adjusting your search or filter criteria</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredRationales.map((rationale) => (
            <Card key={rationale.id} className="premium-card p-4 md:p-6">
              <div className="flex flex-col md:flex-row items-start gap-4 md:gap-6">
                {/* Left Side: Info */}
                <div className="flex gap-3 md:gap-4 flex-1 min-w-0 w-full">
                  <div className="p-2.5 md:p-3 icon-bg-primary rounded-xl shrink-0">
                    <FileText className="w-5 h-5 md:w-6 md:h-6 icon-primary" />
                  </div>
                  <div className="flex-1 min-w-0 space-y-2.5 md:space-y-3">
                    {/* Title with Link (YouTube or Channel URL) */}
                    <div>
                      <a
                        href={rationale.youtube_url || rationale.channel_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-foreground hover:text-primary transition-colors inline-flex items-start gap-2 group"
                      >
                        <span className="line-clamp-2 md:line-clamp-none">{rationale.title}</span>
                        <ExternalLink className="w-4 h-4 text-muted-foreground group-hover:text-primary shrink-0 mt-0.5" />
                      </a>
                    </div>
                    
                    {/* Metadata Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 md:gap-y-2.5 text-sm">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <PlatformIcon platform={rationale.platform} size={16} />
                        <span className="text-foreground truncate">
                          {rationale.channel_name}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-muted-foreground flex-wrap">
                        <Calendar className="w-4 h-4 shrink-0" />
                        <span className="text-muted-foreground">Date:</span>
                        <span className="text-foreground">{formatVideoDate(rationale.date)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className={getToolBadgeColor(rationale.tool_used)}>
                          {rationale.tool_used}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-2 text-muted-foreground flex-wrap">
                        <span className="text-muted-foreground shrink-0">Job ID:</span>
                        <span className="font-mono text-xs text-foreground break-all md:break-normal md:truncate">{rationale.job_id}</span>
                      </div>
                    </div>

                    {/* Signed Status */}
                    {rationale.signed_pdf_path && rationale.signed_uploaded_at && (
                      <div className="flex items-center gap-2 text-xs md:text-sm bg-emerald-500/10 px-3 py-2 rounded-lg w-fit border-2 border-emerald-500/30">
                        <CheckCircle className="w-4 h-4 shrink-0 text-emerald-600" />
                        <span className="truncate font-medium text-emerald-600">Signed PDF uploaded on {formatDate(rationale.signed_uploaded_at)}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Right Side: Action Buttons */}
                <div className="flex flex-col gap-2 md:gap-2.5 w-full md:w-auto md:items-end shrink-0">
                  <Button
                    size="sm"
                    onClick={() => handleViewJob(rationale.job_id, rationale.tool_used)}
                    className="bg-primary hover:bg-primary/90 active:scale-95 text-white w-full md:min-w-[160px] transition-all duration-200 hover:shadow-lg"
                  >
                    <Eye className="w-4 h-4 mr-2" />
                    View Progress
                  </Button>

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleDownload(rationale.unsigned_pdf_path, 'unsigned', rationale.id)}
                    disabled={downloadingId === `${rationale.id}-unsigned`}
                    className="border-blue-500/50 text-blue-500 hover:bg-blue-500 hover:text-white hover:border-blue-500 active:scale-95 w-full md:min-w-[160px] transition-all duration-200 hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {downloadingId === `${rationale.id}-unsigned` ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Download className="w-4 h-4 mr-2" />
                    )}
                    Unsigned PDF
                  </Button>

                  {rationale.signed_pdf_path ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleDownload(rationale.signed_pdf_path!, 'signed', rationale.id)}
                      disabled={downloadingId === `${rationale.id}-signed`}
                      className="border-emerald-500/50 text-emerald-600 hover:bg-emerald-600 hover:text-white hover:border-emerald-600 active:scale-95 w-full md:min-w-[160px] transition-all duration-200 hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {downloadingId === `${rationale.id}-signed` ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4 mr-2" />
                      )}
                      Signed PDF
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleUploadSigned(rationale.job_id)}
                      disabled={uploadingId === rationale.job_id}
                      className="border-green-500/50 text-green-500 hover:bg-green-500 hover:text-white active:scale-95 w-full md:min-w-[160px] transition-all duration-200 hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {uploadingId === rationale.job_id ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      ) : (
                        <Upload className="w-4 h-4 mr-2" />
                      )}
                      Upload Signed
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {filteredRationales.length > 0 && (
        <Card className="premium-card p-3 md:p-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <p className="text-xs md:text-sm text-muted-foreground">
              Showing {filteredRationales.length} of {rationales.length} reports
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled>
                Previous
              </Button>
              <Button size="sm" variant="outline" disabled>
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
