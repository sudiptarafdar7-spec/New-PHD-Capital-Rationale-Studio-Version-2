// Mock data for development and demonstration
import { User, Job, JobStep, Artifact, ActivityLog, ApiKey, SavedRationale, DashboardStats } from '../types';

export const mockUser: User = {
  id: 'user-1',
  first_name: 'Admin',
  last_name: 'User',
  email: 'admin@phdcapital.in',
  mobile: '+91 98765 43210',
  role: 'admin',
  avatar_path: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Admin',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-10-19T00:00:00Z',
};

export const mockJobs: Job[] = [
  {
    id: 'abc123de',
    youtube_url: 'https://www.youtube.com/watch?v=example1',
    user_id: 'user-1',
    status: 'running',
    progress: 87,
    folder_path: '/process/abc123de',
    title: 'Market Analysis - Nifty 50 Stocks Discussion with Pradip',
    channel_name: 'PHD Capital Main',
    created_at: '2025-10-19T10:25:00Z',
    updated_at: '2025-10-19T10:25:00Z',
  },
  {
    id: 'xyz789ab',
    youtube_url: 'https://www.youtube.com/watch?v=example2',
    user_id: 'user-1',
    status: 'completed',
    progress: 100,
    folder_path: '/process/xyz789ab',
    title: 'Stock Picks for This Week - Banking Sector Analysis',
    channel_name: 'Market Analysis Daily',
    created_at: '2025-10-19T08:00:00Z',
    updated_at: '2025-10-19T09:15:00Z',
  },
  {
    id: 'def456gh',
    youtube_url: 'https://www.youtube.com/watch?v=example3',
    user_id: 'user-1',
    status: 'completed',
    progress: 100,
    folder_path: '/process/def456gh',
    title: 'Mid-Cap Opportunities in Current Market - Expert View',
    channel_name: 'PHD Capital Main',
    created_at: '2025-10-18T14:30:00Z',
    updated_at: '2025-10-18T15:45:00Z',
  },
  {
    id: 'ghi789jk',
    youtube_url: 'https://www.youtube.com/watch?v=example4',
    user_id: 'user-1',
    status: 'failed',
    progress: 45,
    folder_path: '/process/ghi789jk',
    title: 'Q2 Results Analysis - Top Performers',
    channel_name: 'Market Analysis Daily',
    created_at: '2025-10-17T11:00:00Z',
    updated_at: '2025-10-17T11:30:00Z',
  },
];

// Pipeline has 14 steps - Step 15 is handled via API endpoints (Save/Sign/Delete actions)
export const pipelineSteps = [
  { number: 1, name: 'Download Audio', description: 'Extract audio from YouTube video' },
  { number: 2, name: 'Download Captions', description: 'Fetch auto-generated captions' },
  { number: 3, name: 'Transcribe Audio', description: 'AssemblyAI transcription with speaker labels' },
  { number: 4, name: 'Merge Transcripts', description: 'Combine captions and transcript data' },
  { number: 5, name: 'Translate to English', description: 'Google Cloud Translation' },
  { number: 6, name: 'Detect Speakers', description: 'Identify Anchor and Pradip using AI' },
  { number: 7, name: 'Filter Transcription', description: 'Keep only Anchor & Pradip dialogue' },
  { number: 8, name: 'Extract Stock Mentions', description: 'AI extraction of stock names and timestamps' },
  { number: 9, name: 'Map Master File', description: 'Match stocks to api-scrip-master.csv' },
  { number: 10, name: 'Convert Timestamps', description: 'Convert to absolute time and date' },
  { number: 11, name: 'Fetch CMP', description: 'Get current market price from Dhan API' },
  { number: 12, name: 'Extract Analysis', description: 'AI-generated stock analysis' },
  { number: 13, name: 'Generate Charts', description: 'Fetch data and plot technical charts' },
  { number: 14, name: 'Generate PDF', description: 'Create branded PDF report' },
];

export const getMockJobSteps = (jobId: string, currentProgress: number): JobStep[] => {
  // Calculate current step (1-15) based on progress percentage
  // For 100% progress, all steps should be completed (currentStep = 16 so all steps < 16 are success)
  const currentStep = currentProgress === 100 ? 16 : Math.ceil((currentProgress / 100) * 15);
  
  return pipelineSteps.map((step) => ({
    id: `${jobId}-step-${step.number}`,
    job_id: jobId,
    step_number: step.number,
    name: step.name,
    status: step.number < currentStep ? 'success' : step.number === currentStep ? 'running' : 'pending',
    message: step.number < currentStep 
      ? `Completed ${step.description}` 
      : step.number === currentStep 
      ? `Processing ${step.description}...` 
      : undefined,
    started_at: step.number <= currentStep ? new Date().toISOString() : undefined,
    ended_at: step.number < currentStep ? new Date().toISOString() : undefined,
  }));
};

export const manualRationaleSteps = [
  { number: 1, name: 'Create Structured CSV', description: 'Creating structured CSV from manual input' },
  { number: 2, name: 'Map Master File', description: 'Match stocks to api-scrip-master.csv' },
  { number: 3, name: 'Fetch CMP', description: 'Get current market price from Dhan API' },
  { number: 4, name: 'Generate Charts', description: 'Fetch data and plot technical charts' },
  { number: 5, name: 'Generate PDF', description: 'Create branded PDF report' },
  { number: 6, name: 'Save / Save & Sign & Log', description: 'Save final output and update logs' },
];

export const getMockManualRationaleSteps = (jobId: string, isCompleted: boolean = true): JobStep[] => {
  // For saved rationales, all steps should be completed
  return manualRationaleSteps.map((step) => ({
    id: `${jobId}-step-${step.number}`,
    job_id: jobId,
    step_number: step.number,
    name: step.name,
    status: isCompleted ? 'success' : 'pending',
    message: isCompleted ? `Completed ${step.description}` : undefined,
    started_at: isCompleted ? new Date().toISOString() : undefined,
    ended_at: isCompleted ? new Date().toISOString() : undefined,
  }));
};

export const mockArtifacts: Artifact[] = [
  {
    id: 'art-1',
    job_id: 'xyz789ab',
    type: 'pdf',
    file_path: '/output/xyz789ab/final_rationale_report.pdf',
    file_name: 'final_rationale_report.pdf',
    created_at: '2025-10-19T09:15:00Z',
  },
  {
    id: 'art-2',
    job_id: 'xyz789ab',
    type: 'csv',
    file_path: '/process/xyz789ab/output/stocks_with_analysis.csv',
    file_name: 'stocks_with_analysis.csv',
    created_at: '2025-10-19T09:10:00Z',
  },
  {
    id: 'art-3',
    job_id: 'xyz789ab',
    type: 'chart',
    file_path: '/process/xyz789ab/charts/HDFC_BANK_chart.png',
    file_name: 'HDFC_BANK_chart.png',
    created_at: '2025-10-19T09:08:00Z',
  },
];

export const mockUsers: User[] = [
  {
    id: 'user-1',
    first_name: 'Admin',
    last_name: 'User',
    email: 'admin@phdcapital.in',
    mobile: '+91 98765 43210',
    role: 'admin',
    avatar_path: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Admin',
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-10-19T00:00:00Z',
  },
  {
    id: 'user-2',
    first_name: 'Rajesh',
    last_name: 'Kumar',
    email: 'rajesh@phdcapital.com',
    mobile: '+91 98765 43211',
    role: 'analyst',
    avatar_path: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Rajesh',
    created_at: '2025-02-15T00:00:00Z',
    updated_at: '2025-10-19T00:00:00Z',
  },
  {
    id: 'user-3',
    first_name: 'Priya',
    last_name: 'Sharma',
    email: 'priya@phdcapital.com',
    mobile: '+91 98765 43212',
    role: 'analyst',
    avatar_path: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Priya',
    created_at: '2025-03-10T00:00:00Z',
    updated_at: '2025-10-19T00:00:00Z',
  },
];

export const mockActivityLogs: ActivityLog[] = [
  {
    id: 'log-1',
    user_id: 'user-1',
    job_id: 'abc123de',
    action: 'job_started',
    message: 'Started new Media Rationale job for YouTube video',
    timestamp: '2025-10-19T10:25:00Z',
  },
  {
    id: 'log-2',
    user_id: 'user-2',
    job_id: 'xyz789ab',
    action: 'job_completed',
    message: 'Job completed successfully - PDF generated',
    timestamp: '2025-10-19T09:15:00Z',
  },
  {
    id: 'log-3',
    user_id: 'user-1',
    action: 'login',
    message: 'User logged in successfully',
    timestamp: '2025-10-19T08:00:00Z',
  },
  {
    id: 'log-4',
    user_id: 'user-3',
    job_id: 'ghi789jk',
    action: 'job_failed',
    message: 'Job failed at step 7 - API rate limit exceeded',
    timestamp: '2025-10-17T11:30:00Z',
  },
  {
    id: 'log-5',
    user_id: 'user-2',
    job_id: 'def456gh',
    action: 'job_completed',
    message: 'Premium Rationale job completed with 5 stock analyses',
    timestamp: '2025-10-18T15:45:00Z',
  },
  {
    id: 'log-6',
    user_id: 'user-3',
    job_id: 'prm123ab',
    action: 'job_started',
    message: 'Started Manual Rationale job for custom stock analysis',
    timestamp: '2025-10-18T14:20:00Z',
  },
  {
    id: 'log-7',
    user_id: 'user-1',
    action: 'logout',
    message: 'User logged out',
    timestamp: '2025-10-18T12:00:00Z',
  },
  {
    id: 'log-8',
    user_id: 'user-2',
    job_id: 'med456xy',
    action: 'job_completed',
    message: 'Media Rationale analysis completed for banking sector',
    timestamp: '2025-10-17T16:30:00Z',
  },
];

export const mockApiKeys: ApiKey[] = [
  { id: 'key-1', provider: 'openai', created_by: 'user-1', created_at: '2025-10-01T00:00:00Z', is_configured: true },
  { id: 'key-2', provider: 'assemblyai', created_by: 'user-1', created_at: '2025-10-01T00:00:00Z', is_configured: true },
  { id: 'key-3', provider: 'google', created_by: 'user-1', created_at: '2025-10-01T00:00:00Z', is_configured: true },
  { id: 'key-4', provider: 'dhan', created_by: 'user-1', created_at: '2025-10-01T00:00:00Z', is_configured: false },
];

export const mockSavedRationale: SavedRationale[] = [
  {
    id: 'rat-1',
    job_id: 'xyz789ab',
    stock_name: 'HDFC Bank, ICICI Bank, Axis Bank',
    channel_name: 'Market Analysis Daily',
    date: '2025-10-19',
    unsigned_path: '/output/xyz789ab/final_rationale_report.pdf',
    signed_path: '/output/xyz789ab/signed/final_rationale_report_signed.pdf',
    signed_uploaded_at: '2025-10-19T10:00:00Z',
    youtube_video_name: 'Stock Picks for This Week - Banking Sector Analysis',
    youtube_url: 'https://www.youtube.com/watch?v=example2',
    tool_used: 'Media Rationale',
    video_upload_date: '2025-10-19',
  },
  {
    id: 'rat-2',
    job_id: 'def456gh',
    stock_name: 'Tata Motors, M&M, Bajaj Auto',
    channel_name: 'PHD Capital Main',
    date: '2025-10-18',
    unsigned_path: '/output/def456gh/final_rationale_report.pdf',
    youtube_video_name: 'Mid-Cap Opportunities in Current Market - Expert View',
    youtube_url: 'https://www.youtube.com/watch?v=example3',
    tool_used: 'Media Rationale',
    video_upload_date: '2025-10-18',
  },
  {
    id: 'rat-3',
    job_id: 'prm123ab',
    stock_name: 'Reliance Industries, TCS, Infosys',
    channel_name: 'Premium Analysis',
    date: '2025-10-17',
    unsigned_path: '/output/prm123ab/final_rationale_report.pdf',
    signed_path: '/output/prm123ab/signed/final_rationale_report_signed.pdf',
    signed_uploaded_at: '2025-10-17T15:30:00Z',
    youtube_video_name: 'Large Cap Tech Giants - Q3 Performance Review',
    youtube_url: 'https://www.youtube.com/watch?v=example5',
    tool_used: 'Premium Rationale',
    video_upload_date: '2025-10-16',
  },
  {
    id: 'rat-4',
    job_id: 'man456cd',
    stock_name: 'Adani Ports, Adani Green Energy',
    channel_name: 'PHD Capital Main',
    date: '2025-10-16',
    unsigned_path: '/output/man456cd/final_rationale_report.pdf',
    youtube_video_name: 'Infrastructure Stocks Analysis - Green Energy Focus',
    youtube_url: 'https://www.youtube.com/watch?v=example6',
    tool_used: 'Manual Rationale',
    video_upload_date: '2025-10-15',
  },
];

export const mockDashboardStats: DashboardStats = {
  total_jobs: 4,
  completed_jobs: 2,
  failed_jobs: 1,
  total_change: '+ 6% from last month',
  completed_change: '+ 5% from last month',
  failed_change: '- 2% from last month',
};

// Helper function to get video metadata for a job
export const getVideoMetadataForJob = (jobId: string) => {
  const rationale = mockSavedRationale.find(r => r.job_id === jobId);
  if (!rationale) return null;

  // Extract video ID from YouTube URL
  const videoIdMatch = rationale.youtube_url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\s]+)/);
  const videoId = videoIdMatch ? videoIdMatch[1] : 'dQw4w9WgXcQ'; // fallback

  // Get channel logo
  const mockChannels = [
    { name: 'PHD Capital Main', logo: 'https://api.dicebear.com/7.x/shapes/svg?seed=PHD' },
    { name: 'Market Analysis Daily', logo: 'https://api.dicebear.com/7.x/shapes/svg?seed=Market' },
    { name: 'Premium Analysis', logo: 'https://api.dicebear.com/7.x/shapes/svg?seed=Premium' },
  ];
  
  const channel = mockChannels.find(ch => ch.name === rationale.channel_name);
  const channelLogo = channel?.logo || 'https://api.dicebear.com/7.x/shapes/svg?seed=default';

  const uploadDate = new Date(rationale.video_upload_date);
  
  return {
    title: rationale.youtube_video_name,
    uploadDate: uploadDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    uploadTime: '10:30 AM', // Mock time
    duration: '45:30', // Mock duration
    videoId: videoId,
    channelName: rationale.channel_name,
    channelLogo: channelLogo,
  };
};
