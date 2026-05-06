// Type definitions for the application

export interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  mobile: string;
  role: 'admin' | 'employee';
  avatar_path?: string;
  job_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  youtube_url: string;
  user_id: string;
  status: 'pending' | 'running' | 'failed' | 'completed' | 'pdf_ready' | 'awaiting_csv_review';
  progress: number;
  folder_path: string;
  title?: string;
  tool?: string;
  tool_used?: string;
  channel_name?: string;
  platform?: string;
  date?: string | null;
  time?: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobStep {
  id: string;
  job_id: string;
  step_number: number;
  name: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  message?: string;
  started_at?: string;
  ended_at?: string;
}

export interface Artifact {
  id: string;
  job_id: string;
  type: 'csv' | 'pdf' | 'chart' | 'log';
  file_path: string;
  file_name: string;
  created_at: string;
}

export interface ActivityLog {
  id: string;
  user_id: string;
  job_id?: string;
  action: string;
  message: string;
  timestamp: string;
}

export interface ApiKey {
  id: string;
  provider: 'openai' | 'assemblyai' | 'google' | 'dhan';
  created_by: string;
  created_at: string;
  is_configured: boolean;
}

export interface SavedRationale {
  id: string;
  job_id: string;
  stock_name: string;
  channel_name: string;
  date: string;
  unsigned_path: string;
  signed_path?: string;
  signed_uploaded_at?: string;
  youtube_video_name: string;
  youtube_url: string;
  tool_used: 'Media Rationale' | 'Premium Rationale' | 'Manual Rationale';
  video_upload_date: string;
}

export interface DashboardStats {
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  total_change: string;
  completed_change: string;
  failed_change: string;
}

export type RationaleToolType = 'media' | 'premium' | 'manual';
