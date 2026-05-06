import React, { useState, useEffect } from 'react';
import { formatIST } from '@/lib/datetime';
import { PenTool, Plus, Trash2, Calendar, Save, Download, FileSignature, Loader2, Clock } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import StepProgressTracker from '../components/StepProgressTracker';
import SignedFileUpload from '../components/SignedFileUpload';
import { StockAutocompleteInput } from '../components/StockAutocompleteInput';
import { playCompletionBell, playSuccessBell } from '../lib/sound-utils';
import { JobStep } from '../types';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { useAuth } from '../lib/auth-context';

interface ManualRationalePageProps {
  selectedJobId?: string;
  onNavigate?: (page: string, jobId?: string) => void;
}

interface Channel {
  id: number;
  channel_name: string;
  platform: string;
  channel_url?: string;
}

interface StockDetail {
  id: string;
  stockName: string;
  time: string;
  chartType: string;
  analysis: string;
  // Master file data
  securityId?: string;
  listedName?: string;
  shortName?: string;
  exchange?: string;
  instrument?: string;
}

type WorkflowStage = 'input' | 'processing' | 'pdf-preview' | 'saved' | 'upload-signed' | 'completed';

const MANUAL_STEPS: JobStep[] = [
  { id: 'step-1', job_id: '', step_number: 1, name: 'Fetch CMP', status: 'pending' },
  { id: 'step-2', job_id: '', step_number: 2, name: 'Generate Charts', status: 'pending' },
  { id: 'step-3', job_id: '', step_number: 3, name: 'Generate PDF', status: 'pending' },
  { id: 'step-4', job_id: '', step_number: 4, name: 'Save / Save & Sign & Log', status: 'pending', message: 'Save final output and update logs' },
];

export default function ManualRationalePage({ selectedJobId, onNavigate }: ManualRationalePageProps) {
  const { token } = useAuth();
  
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState('');
  const [url, setUrl] = useState('');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [stockDetails, setStockDetails] = useState<StockDetail[]>([
    { id: '1', stockName: '', time: '', chartType: 'Daily', analysis: '' }
  ]);
  
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [jobSteps, setJobSteps] = useState<JobStep[]>([]);
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>('input');
  const [isProcessing, setIsProcessing] = useState(false);
  const [uploadedSignedFile, setUploadedSignedFile] = useState<{ fileName: string; uploadedAt: string } | null>(null);
  const [saveType, setSaveType] = useState<'save' | 'save-and-sign' | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string>('');
  const [pdfFilename, setPdfFilename] = useState<string>('rationale_report.pdf');

  // Load channels on mount
  useEffect(() => {
    loadChannels();
  }, []);

  const loadChannels = async () => {
    try {
      const response = await fetch(API_ENDPOINTS.channels.getAll, {
        headers: getAuthHeaders(token || ''),
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

  const loadSavedJob = React.useCallback(async (jobId: string) => {
    try {
      // Try to fetch from v2 jobs API first (for unsaved jobs)
      const jobResponse = await fetch(API_ENDPOINTS.manualV2.getJob(jobId), {
        headers: getAuthHeaders(token || ''),
      });

      if (jobResponse.ok) {
        const responseData = await jobResponse.json();
        const jobData = responseData.job || responseData;  // Handle both nested and flat responses
        const jobStepsData = responseData.job_steps || [];
        
        console.log('[DEBUG] Loading job data:', jobData);
        console.log('[DEBUG] Job steps from API:', jobStepsData);
        
        // Set the job ID
        setCurrentJobId(jobId);

        // Map job steps
        const mappedSteps = jobStepsData.map((step: any) => ({
          id: String(step.id),
          job_id: step.job_id,
          step_number: step.step_number,
          name: step.step_name,
          status: step.status,
          message: step.message || undefined,
          started_at: step.started_at || undefined,
          ended_at: step.ended_at || undefined,
        }));
        
        console.log('[DEBUG] Mapped steps:', mappedSteps);
        setJobSteps(mappedSteps);

        // Determine workflow stage based on job status
        const jobStatus = jobData.status;
        console.log('[DEBUG] Job status:', jobStatus);
        
        if (jobStatus === 'completed') {
          setWorkflowStage('saved');
        } else if (jobStatus === 'signed') {
          setWorkflowStage('completed');
          setSaveType('save-and-sign');
        } else if (jobStatus === 'pdf_ready') {
          setWorkflowStage('pdf-preview');
          // Fetch PDF with auth headers and create blob URL
          loadPdfBlob(jobId);
        } else if (jobStatus === 'processing') {
          setWorkflowStage('processing');
          setIsProcessing(true);
        } else if (jobStatus === 'failed') {
          setWorkflowStage('input');
          toast.error('Job failed', {
            description: 'This job encountered an error during processing',
          });
        } else {
          // For any other status (pending, etc.), show the steps but not in processing mode
          setWorkflowStage('input');
        }
        
        // Start polling if job is still processing
        if (jobStatus === 'processing' || jobStatus === 'pending') {
          pollJobStatus(jobId);
        }

        // Load form data from job payload
        const payload = jobData.payload || {};
        setSelectedChannelId(String(jobData.channel_id || ''));
        setDate(payload.date || jobData.date || '');

        // Reconstruct stock details from payload
        const stocks = payload.stocks || [];
        const loadedStocks = stocks.length > 0 ? 
          stocks.map((stock: any, index: number) => ({
            id: `loaded-${index}`,
            stockName: stock.symbol || '',
            time: stock.call_time || '10:00',
            chartType: (stock.chart_type || 'Daily') as 'Daily' | 'Weekly' | 'Monthly',
            analysis: stock.analysis || '',
          })) : 
          [{ id: '1', stockName: '', time: '', chartType: 'Daily', analysis: '' }];
        
        setStockDetails(loadedStocks);
        return;
      }

      // Fallback to saved_rationale if not found in jobs table
      const response = await fetch(API_ENDPOINTS.savedRationale.getAll, {
        headers: getAuthHeaders(token || ''),
      });

      if (!response.ok) {
        throw new Error('Failed to fetch saved rationale');
      }

      const data = await response.json();
      const savedRationales = Array.isArray(data.rationales) ? data.rationales : [];
      const savedRationale = savedRationales.find((r: any) => r.job_id === jobId);

      if (!savedRationale) {
        toast.error('Job not found', {
          description: `Could not find job with ID: ${jobId}`,
        });
        return;
      }

      // Set the job ID
      setCurrentJobId(jobId);

      // Determine workflow stage based on signed file
      if (savedRationale.signed_pdf_path) {
        setWorkflowStage('completed');
        setSaveType('save-and-sign');
        const fileName = savedRationale.signed_pdf_path ? 
          String(savedRationale.signed_pdf_path).split('/').pop() || 'signed.pdf' : 
          'signed.pdf';
        setUploadedSignedFile({
          fileName: fileName,
          uploadedAt: savedRationale.signed_uploaded_at || new Date().toISOString(),
        });
      } else {
        setWorkflowStage('saved');
        setSaveType('save');
      }

      // Load form data from saved rationale
      setSelectedChannelId(String(savedRationale.channel_id || ''));
      setUrl(savedRationale.youtube_url || '');
      setDate(savedRationale.date || '');

      // Parse stock names into stock details (basic reconstruction)
      const stockNames = savedRationale.title ? 
        String(savedRationale.title).split(',').map((s: string) => s.trim()).filter(Boolean) : 
        [];
      
      const loadedStocks = stockNames.length > 0 ? 
        stockNames.map((name: string, index: number) => ({
          id: `loaded-${index}`,
          stockName: name,
          time: '10:00',
          chartType: 'Daily' as const,
          analysis: '',
        })) : 
        [{ id: '1', stockName: '', time: '', chartType: 'Daily', analysis: '' }];
      
      setStockDetails(loadedStocks);

      toast.success('Loaded saved job', {
        description: `Job ID: ${jobId}`,
      });

    } catch (error: any) {
      console.error('Error loading saved job:', error);
      console.error('Error details:', {
        message: error?.message,
        stack: error?.stack,
        jobId: jobId
      });
      toast.error('Failed to load saved job', {
        description: error?.message || 'Please try again',
      });
    }
  }, [token]);

  React.useEffect(() => {
    if (selectedJobId) {
      // Load the saved job data
      loadSavedJob(selectedJobId);
    }
  }, [selectedJobId, loadSavedJob]);

  const addStockDetail = () => {
    const newStock: StockDetail = {
      id: Date.now().toString(),
      stockName: '',
      time: '',
      chartType: 'Daily',
      analysis: ''
    };
    setStockDetails([...stockDetails, newStock]);
  };

  const removeStockDetail = (id: string) => {
    if (stockDetails.length === 1) {
      toast.error('Error', {
        description: 'At least one stock detail is required',
      });
      return;
    }
    setStockDetails(stockDetails.filter(stock => stock.id !== id));
  };

  const updateStockDetail = (id: string, field: keyof StockDetail, value: string) => {
    setStockDetails(stockDetails.map(stock => 
      stock.id === id ? { ...stock, [field]: value } : stock
    ));
  };

  const validateForm = () => {
    if (!selectedChannelId) {
      toast.error('Validation Error', { description: 'Platform is required' });
      return false;
    }
    if (!date) {
      toast.error('Validation Error', { description: 'Date is required' });
      return false;
    }
    
    for (const stock of stockDetails) {
      if (!stock.stockName || !stock.time || !stock.chartType || !stock.analysis) {
        toast.error('Validation Error', { description: 'All stock fields (name, time, chart type, analysis) are required' });
        return false;
      }
    }
    
    return true;
  };


  const generateRationale = async () => {
    if (!validateForm()) return;

    try {
      setIsProcessing(true);
      setWorkflowStage('processing');

      // Step 1: Create job with v2 API
      const stockNames = stockDetails.map(s => s.stockName).join(', ');
      const createResponse = await fetch(API_ENDPOINTS.manualV2.createJob, {
        method: 'POST',
        headers: getAuthHeaders(token || ''),
        body: JSON.stringify({
          channel_id: parseInt(selectedChannelId),
          title: stockNames,
          date: date,
          call_time: stockDetails[0]?.time || '10:00',
          stocks: stockDetails.map(stock => ({
            symbol: stock.stockName,
            call_time: stock.time,
            chart_type: stock.chartType,
            analysis: stock.analysis,
          }))
        }),
      });

      if (!createResponse.ok) {
        const error = await createResponse.json();
        throw new Error(error.error || 'Failed to create job');
      }

      const createData = await createResponse.json();
      const jobId = createData.job_id;
      setCurrentJobId(jobId);

      toast.success('Job Created!', {
        description: `Job ID: ${jobId}. Starting pipeline...`,
      });

      // Step 2: Start the pipeline
      const runResponse = await fetch(API_ENDPOINTS.manualV2.runPipeline(jobId), {
        method: 'POST',
        headers: getAuthHeaders(token || ''),
      });

      if (!runResponse.ok) {
        const error = await runResponse.json();
        throw new Error(error.error || 'Failed to start pipeline');
      }

      toast.info('Pipeline started', {
        description: 'Processing manual rationale...',
      });

      // Poll for job status
      pollJobStatus(jobId);

    } catch (error: any) {
      console.error('Error creating job:', error);
      toast.error('Failed to create job', {
        description: error.message || 'Please try again',
      });
      setIsProcessing(false);
      setWorkflowStage('input');
    }
  };

  const loadPdfBlob = async (jobId: string) => {
    try {
      // Revoke previous blob URL to prevent memory leaks
      if (pdfUrl && pdfUrl.startsWith('blob:')) {
        URL.revokeObjectURL(pdfUrl);
      }

      const response = await fetch(API_ENDPOINTS.manualV2.downloadPdf(jobId), {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: 'Failed to fetch PDF' }));
        toast.error('Failed to load PDF', {
          description: errorData.error || 'Please try again',
        });
        return;
      }

      // Extract filename from Content-Disposition header
      const contentDisposition = response.headers.get('Content-Disposition');
      let filename = 'rationale_report.pdf';
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }
      setPdfFilename(filename);

      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      setPdfUrl(blobUrl);
    } catch (error) {
      console.error('Error loading PDF blob:', error);
      toast.error('Failed to load PDF', {
        description: 'An error occurred while loading the PDF',
      });
    }
  };

  // Cleanup blob URL on unmount
  useEffect(() => {
    return () => {
      if (pdfUrl && pdfUrl.startsWith('blob:')) {
        URL.revokeObjectURL(pdfUrl);
      }
    };
  }, [pdfUrl]);

  const pollJobStatus = async (jobId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(API_ENDPOINTS.manualV2.getJob(jobId), {
          headers: getAuthHeaders(token || ''),
        });

        if (!response.ok) return;

        const responseData = await response.json();
        const jobData = responseData.job || responseData;
        const jobStepsData = responseData.job_steps || [];
        
        // Update job steps
        const mappedSteps = jobStepsData.map((step: any) => ({
          id: String(step.id),
          job_id: step.job_id,
          step_number: step.step_number,
          name: step.step_name,
          status: step.status === 'running' ? 'running' : 
                  step.status === 'success' ? 'success' : 
                  step.status,
          message: step.error_message || undefined,
          started_at: step.started_at || undefined,
          ended_at: step.ended_at || undefined,
        }));
        setJobSteps(mappedSteps);

        // Check if job is complete
        if (jobData.status === 'pdf_ready') {
          clearInterval(pollInterval);
          setIsProcessing(false);
          setWorkflowStage('pdf-preview');
          // Fetch PDF with auth headers and create blob URL for iframe
          // Use jobId parameter instead of currentJobId to avoid stale closure
          loadPdfBlob(jobId);
          playCompletionBell();
          toast.success('PDF Generated Successfully!', {
            description: 'Your rationale report is ready',
          });
        } else if (jobData.status === 'failed') {
          clearInterval(pollInterval);
          setIsProcessing(false);
          toast.error('Job Failed', {
            description: 'Please check the steps for errors',
          });
        }

      } catch (error) {
        console.error('Error polling job status:', error);
      }
    }, 2000); // Poll every 2 seconds
  };

  const handleDownloadPDF = async () => {
    if (!currentJobId) return;
    
    try {
      // Reuse existing blob URL if available, otherwise fetch
      if (pdfUrl && pdfUrl.startsWith('blob:')) {
        const link = document.createElement('a');
        link.href = pdfUrl;
        link.download = pdfFilename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        toast.success('Downloading PDF', {
          description: pdfFilename,
        });
        return;
      }

      // Fetch PDF with auth headers if no blob URL available
      const response = await fetch(API_ENDPOINTS.manualV2.downloadPdf(currentJobId), {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: 'Failed to download PDF' }));
        toast.error('Failed to download PDF', {
          description: errorData.error || 'Please try again',
        });
        return;
      }

      // Extract filename from Content-Disposition header
      const contentDisposition = response.headers.get('Content-Disposition');
      let filename = pdfFilename;
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }

      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      
      // Create temporary anchor and trigger download
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      // Clean up blob URL
      URL.revokeObjectURL(blobUrl);
      
      toast.success('Downloading PDF', {
        description: filename,
      });
    } catch (error) {
      console.error('Error downloading PDF:', error);
      toast.error('Failed to download PDF', {
        description: 'An error occurred while downloading',
      });
    }
  };

  const handleSave = async () => {
    if (!currentJobId) return;

    try {
      setSaveType('save');

      toast.info('Saving rationale...', {
        description: 'Saving PDF and job data',
      });

      const response = await fetch(API_ENDPOINTS.manualV2.save(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token || ''),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to save job');
      }

      toast.success('Rationale saved successfully!', {
        description: 'Job saved and logged. View in Saved Rationale.',
      });

      setWorkflowStage('saved');

    } catch (error: any) {
      console.error('Error saving job:', error);
      toast.error('Failed to save job', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleSaveAndSign = async () => {
    if (!currentJobId) return;

    try {
      setSaveType('save-and-sign');

      toast.info('Saving unsigned PDF and job data', {
        description: 'Preparing for signed file upload',
      });

      const response = await fetch(API_ENDPOINTS.manualV2.save(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token || ''),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to save job');
      }

      toast.success('Unsigned PDF saved successfully', {
        description: 'Job and rationale log created. Please upload signed PDF.',
      });

      setWorkflowStage('upload-signed');

    } catch (error: any) {
      console.error('Error saving job:', error);
      toast.error('Failed to save job', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleSignedFileUpload = async (file: File) => {
    if (!currentJobId) return;

    try {
      toast.info('Uploading signed PDF...', {
        description: 'Processing signed file',
      });

      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(API_ENDPOINTS.manualV2.uploadSigned(currentJobId), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to upload signed PDF');
      }

      const uploadInfo = {
        fileName: file.name,
        uploadedAt: new Date().toISOString(),
      };
      setUploadedSignedFile(uploadInfo);

      setWorkflowStage('completed');
      playSuccessBell();

      toast.success('Workflow completed! 🎉', {
        description: 'Signed PDF uploaded successfully',
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

    try {
      const response = await fetch(API_ENDPOINTS.manualRationale.deleteJob(currentJobId), {
        method: 'DELETE',
        headers: getAuthHeaders(token || ''),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to delete job');
      }

      toast.success('Job deleted successfully', {
        description: 'Starting a new analysis',
      });
      handleRestart();

    } catch (error: any) {
      console.error('Error deleting job:', error);
      toast.error('Failed to delete job', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleRestart = () => {
    setSelectedChannelId('');
    setUrl('');
    setDate(new Date().toISOString().split('T')[0]);
    setStockDetails([{ id: '1', stockName: '', time: '', chartType: 'Daily', analysis: '' }]);
    setCurrentJobId(null);
    setJobSteps([]);
    setWorkflowStage('input');
    setIsProcessing(false);
    setUploadedSignedFile(null);
    setSaveType(null);
  };

  const handleRestartFromStep = async (stepNumber: number) => {
    if (!currentJobId) return;

    try {
      toast.info('Restarting Pipeline', {
        description: 'Re-running entire pipeline (Manual v2 - 3 steps)',
      });

      // For Manual v2, re-run the entire pipeline (it's only 3 steps and very fast)
      const response = await fetch(API_ENDPOINTS.manualV2.runPipeline(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token || ''),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to restart pipeline');
      }

      // Set processing state
      setIsProcessing(true);
      setWorkflowStage('processing');

      toast.success('Pipeline restarted', {
        description: 'Running all 3 steps from beginning',
      });

      // Poll for job status
      pollJobStatus(currentJobId);

    } catch (error: any) {
      console.error('Error restarting step:', error);
      toast.error('Failed to restart pipeline', {
        description: error.message || 'Please try again',
      });
    }
  };

  const renderRightPanel = () => {
    if (workflowStage === 'processing') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg text-foreground">Generating Rationale Report</h3>
          </div>
          <div className="bg-background border border-border rounded-lg p-12 text-center">
            <Loader2 className="w-16 h-16 mx-auto mb-4 text-blue-500 animate-spin" />
            <p className="text-foreground">Processing manual rationale data...</p>
            <p className="text-sm text-muted-foreground mt-2">Running pipeline steps</p>
          </div>
        </div>
      );
    }

    if (workflowStage === 'pdf-preview') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg text-foreground">Generated PDF Report</h3>
          </div>

          {/* PDF Viewer */}
          <div className="bg-background border border-border rounded-lg overflow-hidden">
            <iframe
              src={pdfUrl || "about:blank"}
              className="w-full h-[500px]"
              title="PDF Report Preview"
            />
          </div>

          {/* Action Buttons - 4 buttons in 2x2 grid */}
          <div className="grid grid-cols-2 gap-3">
            <Button
              onClick={handleDownloadPDF}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              <Download className="w-4 h-4 mr-2" />
              Download
            </Button>
            <Button
              onClick={handleSave}
              className="bg-purple-600 hover:bg-purple-700 text-white"
            >
              <Save className="w-4 h-4 mr-2" />
              Save
            </Button>
            <Button
              onClick={handleSaveAndSign}
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              <FileSignature className="w-4 h-4 mr-2" />
              Save & Sign
            </Button>
            <Button
              onClick={handleDeleteJob}
              variant="outline"
              className="border-red-500/50 text-red-500 hover:bg-red-600 hover:text-white hover:border-red-600"
            >
              <Trash2 className="w-4 h-4 mr-2" />
              Delete
            </Button>
          </div>
        </div>
      );
    }

    if (workflowStage === 'saved') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg text-foreground">Rationale Saved Successfully</h3>
          </div>

          <Card className="bg-card border-border p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-3 bg-green-500/20 rounded-lg">
                <Save className="w-6 h-6 text-green-500" />
              </div>
              <div>
                <h4 className="text-foreground">Saved to Rationale Database</h4>
                <p className="text-sm text-muted-foreground">
                  Job ID: {currentJobId}
                </p>
              </div>
            </div>
            <div className="bg-background border border-border rounded-lg p-4">
              <p className="text-sm text-muted-foreground">
                Your rationale report has been saved successfully. You can view it in the Saved Rationale section.
              </p>
            </div>
          </Card>

          {/* PDF Viewer */}
          <div className="bg-background border border-border rounded-lg overflow-hidden">
            <iframe
              src={pdfUrl || "about:blank"}
              className="w-full h-[500px]"
              title="PDF Report Preview"
            />
          </div>

          {/* Download and Sign Now Buttons */}
          <div className="grid grid-cols-2 gap-3">
            <Button
              onClick={handleDownloadPDF}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              <Download className="w-4 h-4 mr-2" />
              Download PDF
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
      );
    }

    if (workflowStage === 'completed') {
      return (
        <div className="space-y-4">
          <div className="bg-green-50 dark:bg-green-900/20 border-2 border-green-200 dark:border-green-800 rounded-lg p-6 text-center">
            <div className="flex justify-center mb-4">
              <div className="rounded-full bg-green-100 dark:bg-green-900/40 p-3">
                <svg className="w-8 h-8 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
                </svg>
              </div>
            </div>
            <h3 className="text-xl font-semibold text-green-800 dark:text-green-200 mb-2">
              Workflow Completed Successfully! 🎉
            </h3>
            <p className="text-green-700 dark:text-green-300 mb-4">
              Your signed PDF has been uploaded and the rationale is now complete.
            </p>
            {uploadedSignedFile && (
              <div className="bg-white dark:bg-gray-800 rounded-lg p-4 mb-4">
                <p className="text-sm text-muted-foreground mb-1">Signed PDF:</p>
                <p className="font-medium text-foreground">{uploadedSignedFile.fileName}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Uploaded: {formatIST(uploadedSignedFile.uploadedAt)}
                </p>
              </div>
            )}
            <Button
              onClick={() => onNavigate?.('saved-rationale')}
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              View in Saved Rationale
            </Button>
          </div>
        </div>
      );
    }

    if (workflowStage === 'upload-signed') {
      return (
        <SignedFileUpload
          jobId={currentJobId || ''}
          uploadedFile={uploadedSignedFile}
          onUploadComplete={handleSignedFileUpload}
        />
      );
    }

    return null;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl text-foreground mb-1">Manual Rationale</h1>
        <p className="text-muted-foreground">Create rationale reports with manual data entry</p>
      </div>

      {/* Main Content - Two Column Layout */}
      <Card className="bg-card border-border p-6 shadow-sm">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left Column: Form or Progress */}
          <div className="flex flex-col">
            {workflowStage === 'input' ? (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2.5 bg-purple-500/20 rounded-lg">
                    <PenTool className="w-5 h-5 text-purple-500" />
                  </div>
                  <div>
                    <h2 className="text-foreground">Manual Data Entry</h2>
                    <p className="text-xs text-muted-foreground">Enter rationale details manually</p>
                  </div>
                </div>

                <div className="space-y-4">
                  {/* Platform Details */}
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="channel">Channel / Platform *</Label>
                      <Select value={selectedChannelId} onValueChange={setSelectedChannelId}>
                        <SelectTrigger className="bg-background border-input">
                          <SelectValue placeholder="Select channel / platform" />
                        </SelectTrigger>
                        <SelectContent>
                          {channels.map((channel) => (
                            <SelectItem key={channel.id} value={String(channel.id)}>
                              {channel.channel_name} ({channel.platform})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="url">URL (Optional)</Label>
                      <Input
                        id="url"
                        type="url"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        placeholder="https://..."
                        className="bg-background border-input"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="date">Date *</Label>
                      <div className="relative">
                        <Input
                          id="date"
                          type="date"
                          value={date}
                          onChange={(e) => setDate(e.target.value)}
                          className="bg-background border-input"
                        />
                        <Calendar className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground/50 pointer-events-none" />
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-foreground">5-Step Pipeline</h2>
                    <p className="text-xs text-muted-foreground">Job ID: {currentJobId}</p>
                  </div>
                  <Button
                    onClick={handleRestart}
                    size="sm"
                    variant="outline"
                    className="border-border hover:bg-accent h-8"
                  >
                    New Analysis
                  </Button>
                </div>

                <div className="flex-1 overflow-y-auto pr-2">
                  <StepProgressTracker
                    steps={jobSteps}
                    onRestartFromStep={handleRestartFromStep}
                  />
                </div>
              </>
            )}
          </div>

          {/* Right Column: Output or Stock Details */}
          <div className="flex flex-col">
            {workflowStage === 'input' ? (
              <>
                <div className="mb-4">
                  <h3 className="text-foreground">Stock Details</h3>
                </div>

                <div className="space-y-3 flex-1 overflow-y-auto pr-1">
                  {stockDetails.map((stock, index) => (
                    <Card key={stock.id} className="bg-muted border-border p-3 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted-foreground">Stock #{index + 1}</span>
                        {stockDetails.length > 1 && (
                          <Button
                            onClick={() => removeStockDetail(stock.id)}
                            size="sm"
                            variant="ghost"
                            className="text-red-500 hover:text-red-600 hover:bg-red-500/10 h-6 w-6 p-0"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>

                      <div className="space-y-2">
                        <div className="space-y-1.5">
                          <Label className="text-xs">Stock Symbol *</Label>
                          <StockAutocompleteInput
                            value={stock.stockName}
                            useV2Api={true}
                            onSelect={(stockData, stockSymbol) => {
                              if (stockData) {
                                // Update with complete master data
                                setStockDetails(stockDetails.map(s => 
                                  s.id === stock.id ? {
                                    ...s,
                                    stockName: stockSymbol,
                                    securityId: stockData.securityId,
                                    listedName: stockData.listedName,
                                    shortName: stockData.shortName,
                                    exchange: stockData.exchange,
                                    instrument: stockData.instrument
                                  } : s
                                ));
                              } else {
                                // Just update the stock name if typing manually
                                updateStockDetail(stock.id, 'stockName', stockSymbol);
                              }
                            }}
                            token={token || ''}
                            placeholder="Type to search EQUITY stocks..."
                            disabled={workflowStage !== 'input'}
                          />
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                          <div className="space-y-1.5">
                            <Label className="text-xs">Time *</Label>
                            <div className="relative">
                              <Input
                                type="time"
                                value={stock.time}
                                onChange={(e) => updateStockDetail(stock.id, 'time', e.target.value)}
                                className="bg-background border-input h-9 text-sm"
                              />
                              <Clock className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-foreground/50 pointer-events-none" />
                            </div>
                          </div>

                          <div className="space-y-1.5">
                            <Label className="text-xs">Chart Type *</Label>
                            <Select 
                              value={stock.chartType} 
                              onValueChange={(value: string) => updateStockDetail(stock.id, 'chartType', value)}
                            >
                              <SelectTrigger className="bg-background border-input h-9 text-sm">
                                <SelectValue placeholder="Select" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="Daily">Daily</SelectItem>
                                <SelectItem value="Weekly">Weekly</SelectItem>
                                <SelectItem value="Monthly">Monthly</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <Label className="text-xs">Analysis *</Label>
                          <Input
                            value={stock.analysis}
                            onChange={(e) => updateStockDetail(stock.id, 'analysis', e.target.value)}
                            placeholder="Detailed Analysis"
                            className="bg-background border-input h-9 text-sm"
                          />
                        </div>
                      </div>
                    </Card>
                  ))}
                  
                  {/* Add Stock Button - Below all stocks */}
                  <Button
                    onClick={addStockDetail}
                    size="sm"
                    variant="outline"
                    className="w-full border-dashed border-primary/50 text-primary hover:bg-primary/10 h-9"
                  >
                    <Plus className="w-3.5 h-3.5 mr-1.5" />
                    Add Stock
                  </Button>
                </div>

                {/* Generate Button */}
                <Button
                  onClick={generateRationale}
                  disabled={isProcessing}
                  className="gradient-primary w-full h-11 mt-4"
                >
                  {isProcessing ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <FileSignature className="w-4 h-4 mr-2" />
                      Generate Rationale
                    </>
                  )}
                </Button>
              </>
            ) : (
              renderRightPanel()
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
