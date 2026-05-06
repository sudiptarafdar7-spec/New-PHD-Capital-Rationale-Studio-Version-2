import React, { useState } from 'react';
import { AuthProvider, useAuth } from './lib/auth-context';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import MediaRationalePage from './pages/MediaRationalePage';
import PremiumRationalePage from './pages/PremiumRationalePage';
import ManualRationalePage from './pages/ManualRationalePage';
import BulkRationalePage from './pages/BulkRationalePage';
import GenerateChartPage from './pages/GenerateChartPage';
import ActivityLogPage from './pages/ActivityLogPage';
import SavedRationalePage from './pages/SavedRationalePage';
import ProfilePage from './pages/ProfilePage';
import ApiKeysPage from './pages/ApiKeysPage';
import UsersPage from './pages/UsersPage';
import PdfTemplatePage from './pages/PdfTemplatePage';
import UploadFilesPage from './pages/UploadFilesPage';
import ChannelLogosPage from './pages/ChannelLogosPage';
import MediaPresencePage from './pages/MediaPresencePage';
import VoiceTypingPage from './pages/VoiceTypingPage';
import VoiceTypingJobsPage from './pages/VoiceTypingJobsPage';
import AITranscribePage from './pages/AITranscribePage';
import LiveTranscribePage from './pages/LiveTranscribePage';
import LiveTranscribeJobsPage from './pages/LiveTranscribeJobsPage';
import { Toaster } from './components/ui/sonner';
import { VoiceRecordingProvider } from './lib/voice-recording-context';
import AyushiAssistant from './components/AyushiAssistant';

type PageType = 
  | 'login'
  | 'dashboard'
  | 'media-rationale'
  | 'premium-rationale'
  | 'manual-rationale'
  | 'bulk-rationale'
  | 'generate-chart'
  | 'activity-log'
  | 'saved-rationale'
  | 'profile'
  | 'api-keys'
  | 'users'
  | 'pdf-template'
  | 'upload-files'
  | 'channel-logos'
  | 'media-presence'
  | 'voice-typing'
  | 'ai-transcribe'
  | 'live-transcribe'
  | 'settings'
  | 'job-details';

function AppContent() {
  const { isAuthenticated } = useAuth();
  const [currentPage, setCurrentPage] = useState<PageType>('login');
  const [selectedJobId, setSelectedJobId] = useState<string | undefined>();
  const [selectedMediaId, setSelectedMediaId] = useState<number | undefined>();

  const handleNavigate = (page: string, jobIdOrMediaId?: string | number | null) => {
    setCurrentPage(page as PageType);
    if (page === 'voice-typing') {
      // Voice Typing accepts:
      //   • a string voice-typing job id (e.g. "voice-...") → open the job editor
      //   • a numeric mediaId (legacy from Media Presence)  → standalone media-tied flow
      //   • nothing → open the jobs hub page
      if (typeof jobIdOrMediaId === 'string' && jobIdOrMediaId.startsWith('voice-')) {
        setSelectedJobId(jobIdOrMediaId);
        setSelectedMediaId(undefined);
      } else if (jobIdOrMediaId == null) {
        setSelectedJobId(undefined);
        setSelectedMediaId(undefined);
      } else {
        const mid = typeof jobIdOrMediaId === 'string' ? parseInt(jobIdOrMediaId, 10) : jobIdOrMediaId;
        setSelectedMediaId(typeof mid === 'number' && !isNaN(mid) ? mid : undefined);
        setSelectedJobId(undefined);
      }
    } else if (page === 'live-transcribe') {
      // Live Transcribe accepts:
      //   • a string job id starting with "live-" → open the editor
      //   • a numeric mediaId (from Media Presence)  → standalone media-tied flow
      //   • nothing → open the jobs hub page
      if (typeof jobIdOrMediaId === 'string' && jobIdOrMediaId.startsWith('live-')) {
        setSelectedJobId(jobIdOrMediaId);
        setSelectedMediaId(undefined);
      } else if (jobIdOrMediaId == null) {
        setSelectedJobId(undefined);
        setSelectedMediaId(undefined);
      } else {
        const mid = typeof jobIdOrMediaId === 'string' ? parseInt(jobIdOrMediaId, 10) : jobIdOrMediaId;
        setSelectedMediaId(typeof mid === 'number' && !isNaN(mid) ? mid : undefined);
        setSelectedJobId(undefined);
      }
    } else if (page === 'ai-transcribe') {
      // AI Transcribe accepts either a numeric mediaId (when launched from a
      // Media Presence row) or a string jobId like "aitr-…" (when opened
      // from the dashboard for a previously-started standalone job).
      if (typeof jobIdOrMediaId === 'string' && jobIdOrMediaId.startsWith('aitr-')) {
        setSelectedJobId(jobIdOrMediaId);
        setSelectedMediaId(undefined);
      } else {
        const mid = typeof jobIdOrMediaId === 'string' ? parseInt(jobIdOrMediaId, 10) : jobIdOrMediaId;
        setSelectedMediaId(typeof mid === 'number' && !isNaN(mid) ? mid : undefined);
        setSelectedJobId(undefined);
      }
    } else {
      setSelectedJobId(typeof jobIdOrMediaId === 'string' ? jobIdOrMediaId : undefined);
    }
  };

  const handleLoginSuccess = () => {
    setCurrentPage('dashboard');
  };

  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return <DashboardPage onNavigate={handleNavigate} />;
      case 'media-rationale':
        return <MediaRationalePage onNavigate={handleNavigate} selectedJobId={selectedJobId} />;
      case 'premium-rationale':
        return <PremiumRationalePage onNavigate={handleNavigate} selectedJobId={selectedJobId} />;
      case 'manual-rationale':
        return <ManualRationalePage key={selectedJobId} selectedJobId={selectedJobId} onNavigate={handleNavigate} />;
      case 'bulk-rationale':
        return <BulkRationalePage onNavigate={handleNavigate} selectedJobId={selectedJobId} />;
      case 'generate-chart':
        return <GenerateChartPage onNavigate={handleNavigate} />;
      case 'activity-log':
        return <ActivityLogPage />;
      case 'saved-rationale':
        return <SavedRationalePage onNavigate={handleNavigate} />;
      case 'profile':
        return <ProfilePage />;
      case 'api-keys':
        return <ApiKeysPage />;
      case 'users':
        return <UsersPage />;
      case 'pdf-template':
        return <PdfTemplatePage />;
      case 'upload-files':
        return <UploadFilesPage />;
      case 'channel-logos':
        return <ChannelLogosPage />;
      case 'media-presence':
        return <MediaPresencePage onNavigate={handleNavigate} />;
      case 'voice-typing':
        if (selectedJobId && selectedJobId.startsWith('voice-')) {
          return (
            <VoiceTypingPage
              key={selectedJobId}
              onNavigate={handleNavigate}
              voiceJobId={selectedJobId}
            />
          );
        }
        if (selectedMediaId) {
          return <VoiceTypingPage onNavigate={handleNavigate} mediaId={selectedMediaId} />;
        }
        return <VoiceTypingJobsPage onNavigate={handleNavigate} />;
      case 'ai-transcribe':
        return (
          <AITranscribePage
            onNavigate={handleNavigate}
            mediaId={selectedMediaId}
            selectedJobId={selectedJobId}
          />
        );
      case 'live-transcribe':
        if (selectedJobId && selectedJobId.startsWith('live-')) {
          return (
            <LiveTranscribePage
              key={selectedJobId}
              onNavigate={handleNavigate}
              liveJobId={selectedJobId}
            />
          );
        }
        return <LiveTranscribeJobsPage onNavigate={handleNavigate} mediaId={selectedMediaId} />;
      case 'settings':
        return (
          <div className="p-6">
            <h1 className="text-2xl text-foreground mb-1">Settings</h1>
            <p className="text-muted-foreground">System configuration and preferences</p>
          </div>
        );
      case 'job-details':
        return <MediaRationalePage onNavigate={handleNavigate} />;
      default:
        return <DashboardPage onNavigate={handleNavigate} />;
    }
  };

  return (
    <>
      <Layout currentPage={currentPage} onNavigate={handleNavigate}>
        {renderPage()}
      </Layout>
      <AyushiAssistant currentPage={currentPage} onNavigate={handleNavigate} />
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <VoiceRecordingProvider>
        <AppContent />
        <Toaster 
          position="top-right"
          toastOptions={{
            classNames: {
              toast: 'bg-slate-800 border-slate-700 text-slate-100',
              title: 'text-slate-100',
              description: 'text-slate-400',
              actionButton: 'bg-blue-600 text-white',
              cancelButton: 'bg-slate-700 text-slate-300',
            },
          }}
        />
      </VoiceRecordingProvider>
    </AuthProvider>
  );
}
