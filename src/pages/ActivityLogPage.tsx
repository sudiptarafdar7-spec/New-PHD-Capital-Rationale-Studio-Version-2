import React, { useState } from 'react';
import { formatDateIST, formatTimeIST } from '@/lib/datetime';
import { Search, Filter, Calendar as CalendarIcon, Video, FileSpreadsheet, PenTool, CheckCircle2, XCircle, Clock, LogIn, LogOut, X, ChevronLeft, ChevronRight } from 'lucide-react';
import { mockActivityLogs, mockUsers, mockJobs } from '../lib/mock-data';
import { Card } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '../components/ui/avatar';
import { Label } from '../components/ui/label';
import { Calendar } from '../components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '../components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';

export default function ActivityLogPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [toolFilter, setToolFilter] = useState('all');
  const [userFilter, setUserFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dateFrom, setDateFrom] = useState<Date | undefined>(undefined);
  const [dateTo, setDateTo] = useState<Date | undefined>(undefined);
  const [calendarMonth, setCalendarMonth] = useState<Date>(new Date());

  const getStatusConfig = (action: string) => {
    switch (action) {
      case 'job_completed':
        return {
          label: 'Completed',
          color: 'bg-green-500/20 text-green-400 border-green-500/30',
          icon: CheckCircle2,
        };
      case 'job_started':
        return {
          label: 'Started',
          color: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
          icon: Clock,
        };
      case 'job_failed':
        return {
          label: 'Failed',
          color: 'bg-red-500/20 text-red-400 border-red-500/30',
          icon: XCircle,
        };
      case 'login':
        return {
          label: 'Login',
          color: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
          icon: LogIn,
        };
      case 'logout':
        return {
          label: 'Logout',
          color: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
          icon: LogOut,
        };
      default:
        return {
          label: 'Unknown',
          color: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
          icon: Clock,
        };
    }
  };

  const getToolFromJobId = (jobId?: string) => {
    if (!jobId) return null;
    
    if (jobId.startsWith('prm')) {
      return 'Premium Rationale';
    } else if (jobId.startsWith('man')) {
      return 'Manual Rationale';
    }
    return 'Media Rationale';
  };

  const getToolIcon = (jobId?: string) => {
    if (!jobId) return null;
    
    const toolName = getToolFromJobId(jobId);
    
    if (toolName === 'Premium Rationale') {
      return { icon: FileSpreadsheet, name: 'Premium Rationale', color: 'text-amber-500' };
    } else if (toolName === 'Manual Rationale') {
      return { icon: PenTool, name: 'Manual Rationale', color: 'text-purple-500' };
    }
    return { icon: Video, name: 'Media Rationale', color: 'text-blue-500' };
  };

  const formatDateTime = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    let relative = '';
    if (diffMins < 1) relative = 'Just now';
    else if (diffMins < 60) relative = `${diffMins}m ago`;
    else if (diffHours < 24) relative = `${diffHours}h ago`;
    else if (diffDays === 1) relative = 'Yesterday';
    else if (diffDays < 7) relative = `${diffDays}d ago`;
    else relative = formatDateIST(date);

    const time = formatTimeIST(date);
    const fullDate = formatDateIST(date);

    return { relative, time, fullDate, date };
  };

  const getUserInfo = (userId: string) => {
    const user = mockUsers.find(u => u.id === userId);
    if (!user) {
      return {
        name: 'Unknown User',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Unknown',
        initials: 'U',
      };
    }
    return {
      name: `${user.first_name} ${user.last_name}`,
      avatar: user.avatar_path,
      initials: `${user.first_name[0]}${user.last_name[0]}`,
    };
  };

  const clearFilters = () => {
    setSearchQuery('');
    setToolFilter('all');
    setUserFilter('all');
    setStatusFilter('all');
    setDateFrom(undefined);
    setDateTo(undefined);
  };

  const hasActiveFilters = searchQuery || toolFilter !== 'all' || userFilter !== 'all' || 
                          statusFilter !== 'all' || dateFrom || dateTo;

  const filteredLogs = mockActivityLogs.filter(log => {
    // Search filter
    const matchesSearch = !searchQuery || 
                         log.message.toLowerCase().includes(searchQuery.toLowerCase()) ||
                         log.job_id?.toLowerCase().includes(searchQuery.toLowerCase());
    
    // Tool filter
    const logTool = getToolFromJobId(log.job_id);
    const matchesTool = toolFilter === 'all' || 
                       (toolFilter === 'none' && !log.job_id) ||
                       logTool === toolFilter;
    
    // User filter
    const matchesUser = userFilter === 'all' || log.user_id === userFilter;
    
    // Status filter
    const matchesStatus = statusFilter === 'all' || log.action === statusFilter;
    
    // Date range filter
    const logDate = new Date(log.timestamp);
    const matchesDateFrom = !dateFrom || logDate >= dateFrom;
    const matchesDateTo = !dateTo || logDate <= new Date(dateTo.getTime() + 86400000); // Add 1 day to include the end date
    
    return matchesSearch && matchesTool && matchesUser && matchesStatus && matchesDateFrom && matchesDateTo;
  });

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-xl sm:text-2xl text-foreground mb-1">Recent Activity</h1>
        <p className="text-sm sm:text-base text-muted-foreground">Track all system activities, job executions, and user actions</p>
      </div>

      {/* Filters */}
      <Card className="bg-card border-border p-5 shadow-sm">
        <div className="space-y-4">
          {/* Search Bar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search by message or job ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-background border-input text-foreground placeholder:text-muted-foreground"
            />
          </div>

          {/* Filter Options */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
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
                  <SelectItem value="Media Rationale">
                    <div className="flex items-center gap-2">
                      <Video className="w-4 h-4 text-blue-500" />
                      Media Rationale
                    </div>
                  </SelectItem>
                  <SelectItem value="Premium Rationale">
                    <div className="flex items-center gap-2">
                      <FileSpreadsheet className="w-4 h-4 text-amber-500" />
                      Premium Rationale
                    </div>
                  </SelectItem>
                  <SelectItem value="Manual Rationale">
                    <div className="flex items-center gap-2">
                      <PenTool className="w-4 h-4 text-purple-500" />
                      Manual Rationale
                    </div>
                  </SelectItem>
                  <SelectItem value="none">
                    System Actions
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* User Filter */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Filter by User</Label>
              <Select value={userFilter} onValueChange={setUserFilter}>
                <SelectTrigger className="bg-background border-input text-foreground">
                  <SelectValue placeholder="All Users" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    All Users
                  </SelectItem>
                  {mockUsers.map(user => (
                    <SelectItem 
                      key={user.id} 
                      value={user.id}
                    >
                      <div className="flex items-center gap-2">
                        <Avatar className="w-5 h-5">
                          <AvatarImage src={user.avatar_path} alt={user.first_name} />
                          <AvatarFallback className="bg-blue-600 text-white text-xs">
                            {user.first_name[0]}{user.last_name[0]}
                          </AvatarFallback>
                        </Avatar>
                        {user.first_name} {user.last_name}
                      </div>
                    </SelectItem>
                  ))}
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
                    All Activities
                  </SelectItem>
                  <SelectItem value="job_started">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4 text-blue-500" />
                      Job Started
                    </div>
                  </SelectItem>
                  <SelectItem value="job_completed">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-green-500" />
                      Job Completed
                    </div>
                  </SelectItem>
                  <SelectItem value="job_failed">
                    <div className="flex items-center gap-2">
                      <XCircle className="w-4 h-4 text-red-500" />
                      Job Failed
                    </div>
                  </SelectItem>
                  <SelectItem value="login">
                    <div className="flex items-center gap-2">
                      <LogIn className="w-4 h-4 text-purple-500" />
                      Login
                    </div>
                  </SelectItem>
                  <SelectItem value="logout">
                    <div className="flex items-center gap-2">
                      <LogOut className="w-4 h-4 text-muted-foreground" />
                      Logout
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
                    <CalendarIcon className="mr-2 h-4 w-4 text-muted-foreground" />
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

                    <Calendar
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

          {/* Clear Filters */}
          {hasActiveFilters && (
            <div className="flex items-center justify-between pt-2 border-t border-border">
              <p className="text-sm text-muted-foreground">
                {filteredLogs.length} {filteredLogs.length === 1 ? 'result' : 'results'} found
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
              >
                <X className="w-4 h-4 mr-1" />
                Clear Filters
              </Button>
            </div>
          )}
        </div>
      </Card>

      {/* Activity Grid */}
      <div className="space-y-3">
        {filteredLogs.length === 0 ? (
          <Card className="bg-card border-border p-12 text-center shadow-sm">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-muted rounded-full mb-4">
              <Search className="w-8 h-8 text-muted-foreground" />
            </div>
            <p className="text-foreground mb-1">No activities found</p>
            <p className="text-sm text-muted-foreground">Try adjusting your search or filters</p>
          </Card>
        ) : (
          filteredLogs.map((log) => {
            const statusConfig = getStatusConfig(log.action);
            const StatusIcon = statusConfig.icon;
            const dateTime = formatDateTime(log.timestamp);
            const userInfo = getUserInfo(log.user_id);
            const toolInfo = getToolIcon(log.job_id);
            const ToolIcon = toolInfo?.icon;

            return (
              <Card
                key={log.id}
                className="bg-card border-border p-5 hover:bg-accent/50 transition-all shadow-sm"
              >
                <div className="flex items-start gap-4">
                  {/* User Avatar */}
                  <Avatar className="w-11 h-11 border-2 border-border flex-shrink-0">
                    <AvatarImage src={userInfo.avatar} alt={userInfo.name} />
                    <AvatarFallback className="bg-blue-600 text-white">
                      {userInfo.initials}
                    </AvatarFallback>
                  </Avatar>

                  {/* Main Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-4 mb-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-foreground">{userInfo.name}</span>
                        <Badge className={statusConfig.color} variant="outline">
                          <StatusIcon className="w-3 h-3 mr-1" />
                          {statusConfig.label}
                        </Badge>
                        {toolInfo && (
                          <Badge variant="outline" className="border-border text-muted-foreground">
                            {ToolIcon && <ToolIcon className={`w-3 h-3 mr-1 ${toolInfo.color}`} />}
                            {toolInfo.name}
                          </Badge>
                        )}
                      </div>
                      
                      {/* Date/Time */}
                      <div className="text-right flex-shrink-0">
                        <p className="text-sm text-muted-foreground">{dateTime.relative}</p>
                        <p className="text-xs text-muted-foreground">{dateTime.time}</p>
                      </div>
                    </div>

                    {/* Message */}
                    <p className="text-foreground mb-2">{log.message}</p>

                    {/* Job ID and Date */}
                    <div className="flex items-center gap-4 flex-wrap">
                      {log.job_id && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Job ID:</span>
                          <code className="text-xs px-2 py-0.5 bg-muted border border-border rounded text-blue-500 font-mono">
                            {log.job_id}
                          </code>
                        </div>
                      )}
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <CalendarIcon className="w-3 h-3" />
                        {dateTime.fullDate}
                      </div>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })
        )}
      </div>

      {/* Load More */}
      {filteredLogs.length > 0 && (
        <div className="text-center pt-2">
          <button className="text-sm text-blue-500 hover:text-blue-600 transition-colors px-4 py-2 rounded-lg hover:bg-accent">
            Load More Activities
          </button>
        </div>
      )}
    </div>
  );
}
