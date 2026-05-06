import React, { useState, useEffect, useRef } from 'react';
import { Sparkles, Calendar, Clock, Download, FileText, Upload, Trash2, FileSignature, Save, Loader2 } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import SignedFileUpload from '../components/SignedFileUpload';
import StepProgressTracker from '../components/StepProgressTracker';
import { playCompletionBell, playSuccessBell } from '../lib/sound-utils';
import { toast } from 'sonner';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { useAuth } from '../lib/auth-context';
import { JobStep } from '../types';

interface PremiumRationalePageProps {
  onNavigate: (page: string, jobId?: string) => void;
  selectedJobId?: string;
}

interface Channel {
  id: number;
  channel_name: string;
  platform: string;
  channel_url?: string;
}

type WorkflowStage = 'input' | 'processing' | 'csv-review' | 'pdf-preview' | 'saved' | 'upload-signed' | 'completed';
type SaveType = 'save' | 'save-and-sign' | null;

export default function PremiumRationalePage({ onNavigate, selectedJobId }: PremiumRationalePageProps) {
  const { token } = useAuth();
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const csvFileInputRef = useRef<HTMLInputElement | null>(null);
  const lastNotifiedPdfPathRef = useRef<string | null>(null);
  
  // Form state
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string>('');
  const [callDate, setCallDate] = useState(new Date().toISOString().split('T')[0]);
  const [callTime, setCallTime] = useState(new Date().toTimeString().split(' ')[0].substring(0, 5));
  const [stockCallsText, setStockCallsText] = useState('');
  
  // Job state
  const [currentJobId, setCurrentJobId] = useState<string | null>(selectedJobId || null);
  const [progress, setProgress] = useState(0);
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>('input');
  const [jobStatus, setJobStatus] = useState<string>('');
  const [jobSteps, setJobSteps] = useState<JobStep[]>([]);
  const [rationaleTitle, setRationaleTitle] = useState('');
  const [saveType, setSaveType] = useState<SaveType>(null);
  const [uploadedSignedFile, setUploadedSignedFile] = useState<{
    fileName: string;
    uploadedAt: string;
  } | null>(null);
  const [pdfPath, setPdfPath] = useState<string | null>(null);
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null);
  const [isUploadingCsv, setIsUploadingCsv] = useState(false);

  // Load channels on mount
  useEffect(() => {
    loadChannels();
  }, []);

  // Load existing job if selectedJobId is provided
  useEffect(() => {
    if (selectedJobId) {
      loadExistingJob(selectedJobId);
    }
  }, [selectedJobId]);

  const loadChannels = async () => {
    try {
      const response = await fetch(API_ENDPOINTS.channels.getAll, {
        headers: getAuthHeaders(token),
      });
      
      if (response.ok) {
        const data = await response.json();
        setChannels(data);
      }
    } catch (error) {
      console.error('Error loading channels:', error);
      toast.error('Failed to load platforms');
    }
  };

  const loadExistingJob = async (jobId: string) => {
    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.getJob(jobId), {
        headers: getAuthHeaders(token),
      });
      
      if (response.ok) {
        const data = await response.json();
        setCurrentJobId(data.jobId);
        setProgress(data.progress || 0);
        setJobStatus(data.status);
        setRationaleTitle(data.title || '');
        
        // Update job steps if available - map backend format to frontend format
        if (data.job_steps) {
          const mappedSteps = data.job_steps.map((step: any) => ({
            id: String(step.id),
            job_id: step.job_id,
            step_number: step.step_number,
            name: step.step_name,
            status: step.status === 'in_progress' ? 'running' : 
                   step.status === 'completed' ? 'success' : 
                   step.status,
            message: step.error_message || step.message || undefined,
            started_at: step.started_at || undefined,
            ended_at: step.ended_at || step.completed_at || undefined,
          }));
          setJobSteps(mappedSteps);
        }
        
        // Determine workflow stage based on status (check status first, then PDFs)
        if (data.status === 'awaiting_csv_review') {
          setWorkflowStage('csv-review');
        } else if (data.status === 'processing' || data.status === 'running') {
          setWorkflowStage('processing');
          startPolling(jobId);
        } else if (data.status === 'failed') {
          setWorkflowStage('processing'); // Show progress with failed steps
        } else if (data.status === 'signed') {
          // Signed PDF uploaded - show success message
          const pdfFile = data.signedPdfPath || data.unsignedPdfPath || null;
          if (pdfFile) {
            fetchPdfForPreview(pdfFile);
          }
          setWorkflowStage('saved');
        } else if (data.status === 'completed') {
          // Saved but not signed yet - show Download Unsigned PDF + Sign Now
          const pdfFile = data.unsignedPdfPath || data.pdfPath || null;
          if (pdfFile) {
            fetchPdfForPreview(pdfFile);
          }
          setWorkflowStage('completed');
        } else if (data.status === 'pdf_ready') {
          // PDF ready but not saved yet - show Download PDF, Save, Save & Sign
          if (data.pdfPath) {
            fetchPdfForPreview(data.pdfPath);
          }
          setWorkflowStage('pdf-preview');
        }
        
        toast.info('Job loaded', {
          description: `${data.title}`,
        });
      }
    } catch (error) {
      console.error('Error loading job:', error);
      toast.error('Failed to load job');
    }
  };

  const handleStartAnalysis = async () => {
    if (!selectedChannelId || !callDate || !stockCallsText.trim()) {
      toast.error('Please fill all required fields');
      return;
    }

    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.createJob, {
        method: 'POST',
        headers: getAuthHeaders(token),
        body: JSON.stringify({
          channelId: parseInt(selectedChannelId),
          callDate: callDate,
          callTime: callTime + ':00',
          stockCallsText: stockCallsText,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setCurrentJobId(data.jobId);
        setRationaleTitle(data.title);
        setWorkflowStage('processing');
        toast.success('Premium Rationale job started!');
        
        // Start polling for progress
        startPolling(data.jobId);
      } else {
        const error = await response.json();
        toast.error(error.error || 'Failed to start job');
      }
    } catch (error) {
      console.error('Error starting analysis:', error);
      toast.error('Failed to start analysis');
    }
  };

  const startPolling = (jobId: string) => {
    // Clear any existing interval
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }

    // Poll every 2 seconds
    pollingIntervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(API_ENDPOINTS.premiumRationale.getJob(jobId), {
          headers: getAuthHeaders(token),
        });

        if (response.ok) {
          const data = await response.json();
          setProgress(data.progress || 0);
          setJobStatus(data.status);
          
          // Update job steps if available - map backend format to frontend format
          if (data.job_steps) {
            const mappedSteps = data.job_steps.map((step: any) => ({
              id: String(step.id),
              job_id: step.job_id,
              step_number: step.step_number,
              name: step.step_name,
              status: step.status === 'in_progress' ? 'running' : 
                     step.status === 'completed' ? 'success' : 
                     step.status,
              message: step.error_message || undefined,
              started_at: step.started_at || undefined,
              ended_at: step.completed_at || undefined,
            }));
            setJobSteps(mappedSteps);
          }

          // Check if CSV review is ready
          if (data.status === 'awaiting_csv_review') {
            if (pollingIntervalRef.current) {
              clearInterval(pollingIntervalRef.current);
            }
            setWorkflowStage('csv-review');
            playCompletionBell();
            toast.success('Analysis complete! Please review the CSV.');
          }
          
          // Check if PDF is ready
          else if (data.status === 'pdf_ready' && data.pdfPath) {
            // Get PDF path - use saved_rationale paths if available
            let pdfFile = data.signedPdfPath || data.unsignedPdfPath || data.pdfPath;
            
            // Only transition if PDF path changed or stage is different
            if (pdfFile && (pdfFile !== lastNotifiedPdfPathRef.current || workflowStage !== 'pdf-preview')) {
              lastNotifiedPdfPathRef.current = pdfFile;
              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
              }
              setWorkflowStage('pdf-preview');
              await fetchPdfForPreview(pdfFile);
              playSuccessBell();
              toast.success('PDF generated successfully!');
            }
          }
          
          // Check if rationale is saved but not signed
          else if (data.status === 'completed') {
            let pdfFile = data.unsignedPdfPath || data.pdfPath || null;
            
            if (pdfFile && (pdfFile !== lastNotifiedPdfPathRef.current || workflowStage !== 'completed')) {
              lastNotifiedPdfPathRef.current = pdfFile;
              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
              }
              setWorkflowStage('completed');
              await fetchPdfForPreview(pdfFile);
            }
          }
          
          // Check if signed PDF uploaded
          else if (data.status === 'signed') {
            let pdfFile = data.signedPdfPath || data.unsignedPdfPath || null;
            
            if (pdfFile && (pdfFile !== lastNotifiedPdfPathRef.current || workflowStage !== 'saved')) {
              lastNotifiedPdfPathRef.current = pdfFile;
              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
              }
              setWorkflowStage('saved');
              await fetchPdfForPreview(pdfFile);
            }
          }
          
          // Check if job failed
          else if (data.status === 'failed') {
            if (pollingIntervalRef.current) {
              clearInterval(pollingIntervalRef.current);
            }
            toast.error('Job failed. Please check the logs.');
          }
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, 2000);
  };

  const handleDownloadCsv = async () => {
    if (!currentJobId) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.downloadCsv(currentJobId), {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${currentJobId}_analysis.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        toast.success('CSV downloaded successfully');
      } else {
        toast.error('Failed to download CSV');
      }
    } catch (error) {
      console.error('CSV download error:', error);
      toast.error('Failed to download CSV');
    }
  };

  const handleUploadCsv = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentJobId) return;
    
    setIsUploadingCsv(true);
    const formData = new FormData();
    formData.append('csv_file', file);
    
    try {
      const uploadResponse = await fetch(API_ENDPOINTS.premiumRationale.uploadCsv(currentJobId), {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
      });
      
      if (!uploadResponse.ok) {
        toast.error('Failed to upload CSV');
        return;
      }
      
      toast.success('CSV uploaded successfully');
      
      const continueResponse = await fetch(API_ENDPOINTS.premiumRationale.continueToPdf(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });
      
      if (continueResponse.ok) {
        toast.success('Generating PDF...');
        setWorkflowStage('processing');
        startPolling(currentJobId);
      } else {
        toast.error('Failed to continue to PDF');
      }
    } catch (error) {
      toast.error('Upload failed');
      console.error('CSV upload error:', error);
    } finally {
      setIsUploadingCsv(false);
      if (csvFileInputRef.current) {
        csvFileInputRef.current.value = '';
      }
    }
  };

  const handleContinueToPdf = async () => {
    if (!currentJobId) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.continueToPdf(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });
      
      if (response.ok) {
        toast.success('Generating PDF...');
        setWorkflowStage('processing');
        startPolling(currentJobId);
      } else {
        toast.error('Failed to continue to PDF');
      }
    } catch (error) {
      toast.error('Continue failed');
      console.error('Continue error:', error);
    }
  };

  const fetchPdfForPreview = async (pdfFilePath: string) => {
    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.downloadPdf(pdfFilePath), {
        headers: { 'Authorization': `Bearer ${token}` },
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        setPdfBlobUrl(url);
        setPdfPath(pdfFilePath);
      }
    } catch (error) {
      console.error('Error fetching PDF:', error);
    }
  };

  const handleSave = async () => {
    if (!currentJobId) return;

    setSaveType('save');

    try {
      toast.info('Saving rationale...', {
        description: 'Saving PDF and job data',
      });

      const response = await fetch(API_ENDPOINTS.premiumRationale.save(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
        body: JSON.stringify({ jobId: currentJobId }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to save rationale');
      }

      setProgress(100);

      toast.success('Rationale saved successfully!', {
        description: 'Job saved and logged. View in Saved Rationale.',
      });

      setWorkflowStage('completed');
    } catch (error: any) {
      console.error('Error saving rationale:', error);
      toast.error('Failed to save rationale', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleSaveAndSign = async () => {
    if (!currentJobId) return;

    setSaveType('save-and-sign');

    try {
      toast.info('Saving unsigned PDF and job data', {
        description: 'Preparing for signed file upload',
      });

      const response = await fetch(API_ENDPOINTS.premiumRationale.save(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
        body: JSON.stringify({ jobId: currentJobId }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to save rationale');
      }

      toast.success('Unsigned PDF saved successfully', {
        description: 'Job and rationale log created. Please upload signed PDF.',
      });

      setWorkflowStage('upload-signed');
    } catch (error: any) {
      console.error('Error saving rationale:', error);
      toast.error('Failed to save rationale', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleSignedFileUpload = async (file: File) => {
    if (!currentJobId) return;

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('jobId', currentJobId);

      // Don't set Content-Type header - let browser set it automatically for FormData
      const response = await fetch(API_ENDPOINTS.premiumRationale.uploadSigned(currentJobId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to upload signed PDF');
      }

      // Store the uploaded file info
      setUploadedSignedFile({
        fileName: file.name,
        uploadedAt: new Date().toISOString(),
      });

      setProgress(100);
      setWorkflowStage('saved');

      // Play success bell for signed file upload
      playSuccessBell();

      toast.success('Workflow completed! 🎉', {
        description: 'All steps finished successfully with signed PDF',
      });
    } catch (error: any) {
      console.error('Error uploading signed PDF:', error);
      toast.error('Failed to upload signed PDF', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleDeleteJob = async () => {
    if (!currentJobId) return;

    if (!confirm('Are you sure you want to delete this job? This action cannot be undone.')) {
      return;
    }

    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.deleteJob(currentJobId), {
        method: 'DELETE',
        headers: getAuthHeaders(token),
      });

      if (response.ok) {
        toast.success('Job deleted successfully');
        handleReset();
      } else {
        toast.error('Failed to delete job');
      }
    } catch (error) {
      console.error('Delete error:', error);
      toast.error('Delete failed');
    }
  };

  const handleRestartFromStep = async (stepNumber: number) => {
    if (!currentJobId) return;

    try {
      const response = await fetch(API_ENDPOINTS.premiumRationale.restartStep(currentJobId, stepNumber), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to restart step');
      }

      toast.info(`Restarting from Step ${stepNumber}`, {
        description: 'All subsequent steps will be re-executed',
      });
      
      // Set workflow stage to processing and start polling
      setWorkflowStage('processing');
      startPolling(currentJobId);
    } catch (error: any) {
      console.error('Error restarting step:', error);
      toast.error('Failed to restart step', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleReset = () => {
    setCurrentJobId(null);
    setWorkflowStage('input');
    setProgress(0);
    setJobStatus('');
    setStockCallsText('');
    setCallDate(new Date().toISOString().split('T')[0]);
    setCallTime(new Date().toTimeString().split(' ')[0].substring(0, 5));
    setPdfBlobUrl(null);
    setPdfPath(null);
    setSaveType(null);
    setUploadedSignedFile(null);
    
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
      if (pdfBlobUrl) {
        window.URL.revokeObjectURL(pdfBlobUrl);
      }
    };
  }, [pdfBlobUrl]);

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl text-foreground flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-purple-500" />
            Premium Rationale
          </h1>
          <p className="text-sm sm:text-base text-muted-foreground mt-1">
            Generate professional stock analysis reports from your platform calls
          </p>
        </div>
      </div>

      {/* Input Form Stage */}
      {workflowStage === 'input' && (
        <Card className="bg-card border-border shadow-sm p-4 sm:p-6">
          <div className="space-y-4 sm:space-y-5">
            <div className="flex items-center gap-2 pb-3 border-b border-border">
              <div className="p-2 bg-purple-500/20 rounded-lg">
                <FileText className="w-5 h-5 text-purple-500" />
              </div>
              <h2 className="text-lg text-foreground">Stock Call Input</h2>
            </div>

            {/* Platform/Channel Selection */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="channel">Platform & Channel *</Label>
                <Select value={selectedChannelId} onValueChange={setSelectedChannelId}>
                  <SelectTrigger id="channel">
                    <SelectValue placeholder="Select platform" />
                  </SelectTrigger>
                  <SelectContent>
                    {channels.map((channel) => (
                      <SelectItem key={channel.id} value={channel.id.toString()}>
                        {channel.platform.toUpperCase()} - {channel.channel_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="date" className="flex items-center gap-1">
                    <Calendar className="w-4 h-4" />
                    Date *
                  </Label>
                  <Input
                    id="date"
                    type="date"
                    value={callDate}
                    onChange={(e) => setCallDate(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="time" className="flex items-center gap-1">
                    <Clock className="w-4 h-4" />
                    Time *
                  </Label>
                  <Input
                    id="time"
                    type="time"
                    value={callTime}
                    onChange={(e) => setCallTime(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {/* Stock Calls Text Area */}
            <div className="space-y-2">
              <Label htmlFor="stock-calls">Stock Calls Text *</Label>
              <Textarea
                id="stock-calls"
                placeholder="Paste all stock calls here (Stock Name, CMP, Entry, Targets, Stop Loss, Holding Period, Call Type)...

Example:
RELIANCE CMP 2450, BUY @ 2400-2420, TARGET 2600, 2700, SL 2350, HOLDING 2-3 weeks
TCS CMP 3850, SELL @ 3900, TARGET 3700, 3600, SL 4000, HOLDING 1 week"
                value={stockCallsText}
                onChange={(e) => setStockCallsText(e.target.value)}
                className="min-h-[250px] font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Enter one or more stock calls. Each call should include stock name, targets, stop loss, holding period, and call type (Buy/Sell/Hold).
              </p>
            </div>

            {/* Generate Button */}
            <Button
              onClick={handleStartAnalysis}
              className="w-full gradient-primary h-12 text-base"
              disabled={!selectedChannelId || !callDate || !stockCallsText.trim()}
              data-tour="premium-generate"
            >
              <Sparkles className="w-5 h-5 mr-2" />
              Generate Rationale
            </Button>
          </div>
        </Card>
      )}

      {/* Results Section - 2 Column Layout matching Media Rationale */}
      {currentJobId && jobSteps.length > 0 && workflowStage !== 'saved' && workflowStage !== 'completed' && workflowStage !== 'upload-signed' && (
        <Card className="bg-card border-border shadow-sm">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
            {/* Left Column: 8-Step Pipeline */}
            <div className="space-y-4">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-lg text-foreground">8-Step Pipeline</h3>
                  <p className="text-sm text-muted-foreground">Job ID: {currentJobId}</p>
                </div>
              </div>

              <StepProgressTracker 
                steps={jobSteps} 
                onRestartFromStep={handleRestartFromStep}
              />
            </div>

            {/* Right Column: Dynamic Content Based on Workflow Stage */}
            <div className="space-y-4">
              {/* Processing Status */}
              {workflowStage === 'processing' && (
                <div className="flex items-center justify-center bg-background border border-dashed border-border rounded-lg h-full">
                  <div className="text-center py-12">
                    <Loader2 className="w-12 h-12 mx-auto mb-3 text-blue-500 animate-spin" />
                    <p className="text-sm text-muted-foreground">Processing your stock calls...</p>
                    <p className="text-xs text-muted-foreground mt-1">This may take a few moments</p>
                  </div>
                </div>
              )}

              {/* CSV Review Stage */}
              {workflowStage === 'csv-review' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-border">
                    <div className="flex items-center gap-2">
                      <div className="p-2 bg-green-500/20 rounded-lg">
                        <FileText className="w-5 h-5 text-green-500" />
                      </div>
                      <div>
                        <h2 className="text-lg text-foreground">Analysis Complete - Review CSV</h2>
                        <p className="text-sm text-muted-foreground">Download, review, and edit if needed</p>
                      </div>
                    </div>
                  </div>

                  <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
                    <p className="text-sm text-green-700 dark:text-green-400">
                      ✓ Stock analysis completed successfully! Review the CSV file and make any necessary edits before generating the PDF.
                    </p>
                  </div>

                  {/* Action Buttons */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <Button
                      onClick={handleDownloadCsv}
                      variant="outline"
                      className="border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
                    >
                      <Download className="w-4 h-4 mr-2" />
                      Download CSV
                    </Button>

                    <div>
                      <input
                        ref={csvFileInputRef}
                        type="file"
                        accept=".csv"
                        onChange={handleUploadCsv}
                        className="hidden"
                      />
                      <Button
                        onClick={() => csvFileInputRef.current?.click()}
                        variant="outline"
                        className="w-full border-orange-500/50 text-orange-500 hover:bg-orange-600 hover:text-white hover:border-orange-600"
                        disabled={isUploadingCsv}
                      >
                        {isUploadingCsv ? (
                          <>
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            Uploading...
                          </>
                        ) : (
                          <>
                            <Upload className="w-4 h-4 mr-2" />
                            Upload Edited CSV
                          </>
                        )}
                      </Button>
                    </div>

                    <Button
                      onClick={handleContinueToPdf}
                      className="gradient-primary"
                    >
                      Continue to PDF
                    </Button>
                  </div>
                </div>
              )}

              {/* PDF Preview Stage */}
              {workflowStage === 'pdf-preview' && pdfBlobUrl && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-border">
                    <div className="flex items-center gap-2">
                      <div className="p-2 bg-green-500/20 rounded-lg">
                        <FileText className="w-5 h-5 text-green-500" />
                      </div>
                      <div>
                        <h2 className="text-lg text-foreground">PDF Generated Successfully</h2>
                        <p className="text-sm text-muted-foreground">{rationaleTitle}</p>
                      </div>
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      onClick={async () => {
                        try {
                          if (!pdfPath) {
                            toast.error('PDF path not found');
                            return;
                          }
                          
                          const response = await fetch(API_ENDPOINTS.premiumRationale.downloadPdf(pdfPath), {
                            headers: { 'Authorization': `Bearer ${token}` },
                          });
                          
                          if (response.ok) {
                            const blob = await response.blob();
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = 'premium_rationale.pdf';
                            document.body.appendChild(a);
                            a.click();
                            window.URL.revokeObjectURL(url);
                            document.body.removeChild(a);
                            toast.success('PDF downloaded successfully!');
                          } else {
                            toast.error('Failed to download PDF');
                          }
                        } catch (error) {
                          console.error('Error downloading PDF:', error);
                          toast.error('Failed to download PDF');
                        }
                      }}
                      variant="outline"
                      className="border-green-500/50 text-green-500 hover:bg-green-600 hover:text-white"
                    >
                      <Download className="w-4 h-4 mr-2" />
                      Download PDF
                    </Button>
                    <Button
                      onClick={handleSave}
                      variant="outline"
                      className="border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white"
                    >
                      <Save className="w-4 h-4 mr-2" />
                      Save
                    </Button>
                    <Button
                      onClick={handleSaveAndSign}
                      className="bg-purple-600 hover:bg-purple-700 text-white"
                    >
                      <FileSignature className="w-4 h-4 mr-2" />
                      Save & Sign
                    </Button>
                    <Button
                      onClick={handleDeleteJob}
                      variant="outline"
                      className="border-red-500/50 text-red-500 hover:bg-red-600 hover:text-white"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>

                  {/* PDF Viewer */}
                  <div className="bg-card border-border shadow-sm overflow-hidden rounded-lg">
                    <iframe
                      src={pdfBlobUrl}
                      className="w-full h-[500px]"
                      title="Premium Rationale PDF Preview"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Upload Signed PDF Stage */}
      {workflowStage === 'upload-signed' && currentJobId && (
        <SignedFileUpload
          jobId={currentJobId}
          uploadedFile={uploadedSignedFile}
          onUploadComplete={handleSignedFileUpload}
        />
      )}

      {/* Completed Stage - After Save (Unsigned PDF) */}
      {workflowStage === 'completed' && (
        <Card className="bg-card border-border shadow-sm p-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg text-foreground">Unsigned PDF Preview</h3>
            </div>

            {/* PDF Viewer - Shows Unsigned PDF */}
            <div className="bg-background border border-border rounded-lg overflow-hidden">
              {pdfBlobUrl ? (
                <iframe
                  src={pdfBlobUrl}
                  className="w-full h-[500px]"
                  title="Unsigned Premium PDF Preview"
                />
              ) : (
                <div className="w-full h-[500px] flex items-center justify-center bg-muted">
                  <p className="text-muted-foreground">Loading Unsigned PDF...</p>
                </div>
              )}
            </div>

            {/* Download Unsigned PDF and Sign Now Buttons */}
            <div className="grid grid-cols-2 gap-3">
              <Button
                onClick={async () => {
                  try {
                    const jobResponse = await fetch(API_ENDPOINTS.premiumRationale.getJob(currentJobId!), {
                      headers: { 'Authorization': `Bearer ${token}` },
                    });
                    
                    if (!jobResponse.ok) {
                      toast.error('Failed to fetch job data');
                      return;
                    }
                    
                    const jobData = await jobResponse.json();
                    const unsignedPdfPath = jobData.unsignedPdfPath;
                    
                    if (!unsignedPdfPath) {
                      toast.error('Unsigned PDF not found');
                      return;
                    }
                    
                    const response = await fetch(API_ENDPOINTS.premiumRationale.downloadPdf(unsignedPdfPath), {
                      headers: { 'Authorization': `Bearer ${token}` },
                    });
                    
                    if (response.ok) {
                      const blob = await response.blob();
                      const url = window.URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = 'unsigned_premium_rationale.pdf';
                      document.body.appendChild(a);
                      a.click();
                      window.URL.revokeObjectURL(url);
                      document.body.removeChild(a);
                      toast.success('Unsigned PDF downloaded successfully!');
                    } else {
                      toast.error('Failed to download unsigned PDF');
                    }
                  } catch (error) {
                    console.error('Error downloading unsigned PDF:', error);
                    toast.error('Failed to download unsigned PDF');
                  }
                }}
                variant="outline"
                className="border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
              >
                <Download className="w-4 h-4 mr-2" />
                Download Unsigned PDF
              </Button>
              <Button
                onClick={() => {
                  setSaveType('save-and-sign');
                  setWorkflowStage('upload-signed');
                  toast.info('Upload signed PDF', {
                    description: 'Please upload the signed version of your PDF',
                  });
                }}
                className="bg-green-600 hover:bg-green-700 text-white"
              >
                <FileSignature className="w-4 h-4 mr-2" />
                Sign Now
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Saved Stage - After Signing */}
      {workflowStage === 'saved' && (
        <Card className="bg-card border-border shadow-sm p-6 sm:p-8">
          <div className="text-center space-y-4">
            <div className="flex flex-col items-center gap-4">
              <div className="p-4 bg-green-500/20 rounded-full">
                <FileText className="w-12 h-12 text-green-500" />
              </div>
              <div>
                <h3 className="text-xl text-foreground mb-2">Signed PDF Uploaded!</h3>
                <p className="text-muted-foreground">Your signed rationale has been saved to the database</p>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button
                onClick={() => onNavigate('saved-rationale')}
                className="gradient-primary"
              >
                View Saved Rationale
              </Button>
              <Button
                onClick={handleReset}
                variant="outline"
              >
                Create New Analysis
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
