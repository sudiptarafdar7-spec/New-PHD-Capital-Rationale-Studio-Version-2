import { useState, useEffect, useRef } from 'react';
import { useAuth } from '@/lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '@/lib/api-config';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { 
  Layers, Play, Download, Save, FileSignature, Trash2, 
  ArrowLeft, Upload, CheckCircle2, XCircle, Loader2, Clock,
  RefreshCw, RotateCcw, FileEdit, Pencil
} from 'lucide-react';
import SignedFileUpload from '@/components/SignedFileUpload';

interface Channel {
  id: number;
  channel_name: string;
  platform: string;
  channel_url?: string;
}

interface JobStep {
  id: string;
  job_id: string;
  step_number: number;
  name?: string;
  step_name?: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  message?: string;
  started_at?: string;
  ended_at?: string;
}

type WorkflowStage = 'input' | 'processing' | 'step4-review' | 'step6-chart-upload' | 'pdf-preview' | 'saved' | 'upload-signed' | 'completed';

interface FailedChart {
  index: number;
  stock_name: string;
  symbol: string;
  short_name: string;
  security_id: string;
  error: string;
  uploaded?: boolean;
}
type SaveType = 'save' | 'save-and-sign' | null;

interface BulkRationalePageProps {
  onNavigate: (page: string, jobId?: string | null) => void;
  selectedJobId?: string | null;
}

const playCompletionBell = () => {
  try {
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    oscillator.frequency.value = 800;
    oscillator.type = 'sine';
    gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.5);
  } catch (e) {}
};

export default function BulkRationalePage({ onNavigate, selectedJobId }: BulkRationalePageProps) {
  const { token } = useAuth();
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastNotifiedPdfPathRef = useRef<string | null>(null);
  
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string>('');
  const [youtubeUrl, setYoutubeUrl] = useState<string>('');
  const [callDate, setCallDate] = useState(new Date().toISOString().split('T')[0]);
  const [callTime, setCallTime] = useState(new Date().toTimeString().split(' ')[0].substring(0, 5));
  const [inputText, setInputText] = useState('');
  
  const [currentJobId, setCurrentJobId] = useState<string | null>(selectedJobId || null);
  const [progress, setProgress] = useState(0);
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>('input');
  const [jobStatus, setJobStatus] = useState<string>('');
  const [jobSteps, setJobSteps] = useState<JobStep[]>([]);
  const [rationaleTitle, setRationaleTitle] = useState('');
  const [saveType, setSaveType] = useState<SaveType>(null);
  
  const [pdfPath, setPdfPath] = useState<string | null>(null);
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null);
  const [selectedRestartStep, setSelectedRestartStep] = useState<number>(1);
  const [isRestarting, setIsRestarting] = useState(false);
  
  // Step 4 CSV Review state
  const [step4CsvData, setStep4CsvData] = useState<any[]>([]);
  const [step4CsvColumns, setStep4CsvColumns] = useState<string[]>([]);
  const [isUploadingStep4Csv, setIsUploadingStep4Csv] = useState(false);
  const [isEditingStep4Csv, setIsEditingStep4Csv] = useState(false);
  const [isSavingStep4Edits, setIsSavingStep4Edits] = useState(false);
  const [hasStep4Edits, setHasStep4Edits] = useState(false);
  const step4CsvFileInputRef = useRef<HTMLInputElement>(null);
  const workflowStageRef = useRef<WorkflowStage>('input');
  
  // Step 6 Failed Charts state
  const [failedCharts, setFailedCharts] = useState<FailedChart[]>([]);
  const [successChartCount, setSuccessChartCount] = useState(0);
  const [uploadingChartIndex, setUploadingChartIndex] = useState<number | null>(null);
  const chartFileInputRefs = useRef<{[key: number]: HTMLInputElement | null}>({});

  // Edit Input dialog state — keeps a copy of the original input fields so the
  // user can review/modify them and restart the pipeline from Step 1.
  const [isEditInputOpen, setIsEditInputOpen] = useState(false);
  const [editChannelId, setEditChannelId] = useState<string>('');
  const [editYoutubeUrl, setEditYoutubeUrl] = useState<string>('');
  const [editCallDate, setEditCallDate] = useState<string>('');
  const [editCallTime, setEditCallTime] = useState<string>('');
  const [editInputText, setEditInputText] = useState<string>('');
  const [isSavingEditInput, setIsSavingEditInput] = useState(false);

  useEffect(() => {
    loadChannels();
  }, []);

  useEffect(() => {
    if (selectedJobId) {
      loadExistingJob(selectedJobId);
    }
  }, [selectedJobId]);

  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, []);

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
      const response = await fetch(API_ENDPOINTS.bulkRationale.getJob(jobId), {
        headers: getAuthHeaders(token),
      });
      
      if (response.ok) {
        const data = await response.json();
        setCurrentJobId(data.jobId);
        setProgress(data.progress || 0);
        setJobStatus(data.status);
        setRationaleTitle(data.title || '');
        
        if (data.job_steps) {
          const mappedSteps = data.job_steps.map((step: any) => ({
            id: String(step.id),
            job_id: step.job_id,
            step_number: step.step_number,
            name: step.step_name,
            status: step.status === 'running' ? 'running' : 
                   step.status === 'success' ? 'success' : 
                   step.status,
            message: step.message || undefined,
            started_at: step.started_at || undefined,
            ended_at: step.ended_at || undefined,
          }));
          setJobSteps(mappedSteps);
        }
        
        if (data.status === 'processing') {
          setWorkflowStage('processing');
          workflowStageRef.current = 'processing';
          startPolling(jobId);
        } else if (data.status === 'awaiting_step4_review') {
          setWorkflowStage('step4-review');
          workflowStageRef.current = 'step4-review';
          fetchStep4CsvData(jobId);
        } else if (data.status === 'awaiting_chart_upload') {
          setWorkflowStage('step6-chart-upload');
          workflowStageRef.current = 'step6-chart-upload';
          fetchFailedCharts(jobId);
        } else if (data.status === 'failed') {
          setWorkflowStage('processing');
        } else if (data.status === 'pdf_ready' && data.pdfPath) {
          setWorkflowStage('pdf-preview');
          workflowStageRef.current = 'pdf-preview';
          await fetchPdfForPreview(data.pdfPath, data.jobId);
        } else if (data.status === 'completed' || data.status === 'signed') {
          setWorkflowStage('completed');
          workflowStageRef.current = 'completed';
          if (data.pdfPath) {
            await fetchPdfForPreview(data.pdfPath, data.jobId);
          }
        }
        
        toast.info('Job loaded', { description: data.title });
      }
    } catch (error) {
      console.error('Error loading job:', error);
      toast.error('Failed to load job');
    }
  };

  const handleStartAnalysis = async () => {
    if (!selectedChannelId || !callDate || !inputText.trim()) {
      toast.error('Please fill all required fields');
      return;
    }

    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.createJob, {
        method: 'POST',
        headers: getAuthHeaders(token),
        body: JSON.stringify({
          channelId: parseInt(selectedChannelId),
          youtubeUrl: youtubeUrl,
          callDate: callDate,
          callTime: callTime + ':00',
          inputText: inputText,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setCurrentJobId(data.jobId);
        setRationaleTitle(data.title);
        setWorkflowStage('processing');
        toast.success('Bulk Rationale job started!');
        
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
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }

    pollingIntervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(API_ENDPOINTS.bulkRationale.getJob(jobId), {
          headers: getAuthHeaders(token),
        });

        if (response.ok) {
          const data = await response.json();
          setProgress(data.progress || 0);
          setJobStatus(data.status);
          
          if (data.job_steps) {
            const mappedSteps = data.job_steps.map((step: any) => ({
              id: String(step.id),
              job_id: step.job_id,
              step_number: step.step_number,
              name: step.step_name,
              status: step.status === 'running' ? 'running' : 
                     step.status === 'success' ? 'success' : 
                     step.status,
              message: step.message || undefined,
              started_at: step.started_at || undefined,
              ended_at: step.ended_at || undefined,
            }));
            setJobSteps(mappedSteps);
          }

          // Check for Step 4 CSV review checkpoint
          if (data.status === 'awaiting_step4_review') {
            const currentWorkflowStage = workflowStageRef.current;
            if (currentWorkflowStage !== 'step4-review') {
              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
              }
              setWorkflowStage('step4-review');
              workflowStageRef.current = 'step4-review';
              
              // Fetch Step 4 CSV data
              fetchStep4CsvData(jobId).catch((error) => {
                console.error('Failed to fetch Step 4 CSV data:', error);
              });
              
              playCompletionBell();
              toast.success('Step 4 Complete - Review Mapped Master File', {
                description: 'Review the stock symbol mapping before continuing',
              });
            }
          } else if (data.status === 'awaiting_chart_upload') {
            const currentWorkflowStage = workflowStageRef.current;
            if (currentWorkflowStage !== 'step6-chart-upload') {
              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
              }
              setWorkflowStage('step6-chart-upload');
              workflowStageRef.current = 'step6-chart-upload';
              
              fetchFailedCharts(jobId).catch((error) => {
                console.error('Failed to fetch failed charts:', error);
              });
              
              playCompletionBell();
              toast.warning('Some charts could not be generated', {
                description: 'Please upload missing charts manually or skip to continue',
              });
            }
          } else if (data.status === 'pdf_ready' && data.pdfPath) {
            if (data.pdfPath !== lastNotifiedPdfPathRef.current || workflowStage !== 'pdf-preview') {
              lastNotifiedPdfPathRef.current = data.pdfPath;
              if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
              }
              setWorkflowStage('pdf-preview');
              workflowStageRef.current = 'pdf-preview';
              await fetchPdfForPreview(data.pdfPath, jobId);
              playCompletionBell();
              toast.success('PDF generated successfully!');
            }
          } else if (data.status === 'failed') {
            if (pollingIntervalRef.current) {
              clearInterval(pollingIntervalRef.current);
            }
            toast.error('Job failed. Check the step details for errors.');
          }
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, 2000);
  };

  const fetchPdfForPreview = async (pdfFilePath: string, jobId?: string) => {
    const targetJobId = jobId || currentJobId;
    if (!targetJobId) {
      console.error('No job ID available for PDF fetch');
      return;
    }
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.downloadPdf(targetJobId), {
        headers: { 'Authorization': `Bearer ${token}` },
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        setPdfBlobUrl(url);
        setPdfPath(pdfFilePath);
      } else {
        console.error('Failed to fetch PDF:', response.status, response.statusText);
      }
    } catch (error) {
      console.error('Error fetching PDF:', error);
    }
  };

  const handleSave = async () => {
    if (!currentJobId) return;

    setSaveType('save');

    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.save(currentJobId), {
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
      toast.info('Saving unsigned PDF and job data');

      const response = await fetch(API_ENDPOINTS.bulkRationale.save(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
        body: JSON.stringify({ jobId: currentJobId }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to save rationale');
      }

      toast.success('Unsigned PDF saved successfully', {
        description: 'Please upload signed PDF.',
      });

      setWorkflowStage('upload-signed');
    } catch (error: any) {
      console.error('Error saving rationale:', error);
      toast.error('Failed to save rationale', {
        description: error.message || 'Please try again',
      });
    }
  };

  const handleSignedUploadComplete = () => {
    setWorkflowStage('completed');
    toast.success('Signed PDF uploaded successfully!');
  };

  const handleDelete = async () => {
    if (!currentJobId) return;

    if (!confirm('Are you sure you want to delete this job?')) return;

    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.deleteJob(currentJobId), {
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
      console.error('Error deleting job:', error);
      toast.error('Failed to delete job');
    }
  };

  const handleRestartStep = async (stepNumber: number) => {
    if (!currentJobId) return;

    setIsRestarting(true);
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.restartStep(currentJobId, stepNumber), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        toast.info(`Restarting from Step ${stepNumber}`, {
          description: 'All subsequent steps will be re-executed',
        });
        setWorkflowStage('processing');
        startPolling(currentJobId);
      } else {
        toast.error('Failed to restart step', {
          description: data.error || 'Please try again',
        });
      }
    } catch (error: any) {
      console.error('Error restarting step:', error);
      toast.error('Failed to restart step', {
        description: error.message || 'Please try again',
      });
    } finally {
      setIsRestarting(false);
    }
  };

  // Edit Input — open dialog with current job's input fields prefilled.
  const handleOpenEditInput = async () => {
    if (!currentJobId) return;
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.getJob(currentJobId), {
        headers: getAuthHeaders(token),
      });
      if (!response.ok) {
        toast.error('Could not load job details');
        return;
      }
      const data = await response.json();
      setEditChannelId(data.channelId ? String(data.channelId) : '');
      setEditYoutubeUrl(data.youtubeUrl || '');
      setEditCallDate(data.date || '');
      // backend stores HH:MM:SS, the <input type="time"> wants HH:MM
      setEditCallTime((data.time || '').substring(0, 5));
      setEditInputText(data.inputText || '');
      setIsEditInputOpen(true);
    } catch (error) {
      console.error('Error opening edit dialog:', error);
      toast.error('Failed to load input for editing');
    }
  };

  const handleSaveEditInput = async () => {
    if (!currentJobId) return;
    if (!editChannelId || !editCallDate || !editInputText.trim()) {
      toast.error('Please fill all required fields');
      return;
    }
    setIsSavingEditInput(true);
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.editInput(currentJobId), {
        method: 'PUT',
        headers: getAuthHeaders(token),
        body: JSON.stringify({
          channelId: parseInt(editChannelId, 10),
          youtubeUrl: editYoutubeUrl,
          callDate: editCallDate,
          callTime: editCallTime ? `${editCallTime}:00` : '10:00:00',
          inputText: editInputText,
        }),
      });
      const data = await response.json();
      if (response.ok && data.success) {
        toast.success('Input updated', {
          description: 'Pipeline restarted from Step 1',
        });
        setIsEditInputOpen(false);
        setRationaleTitle(data.title || rationaleTitle);
        setProgress(0);
        setPdfBlobUrl(null);
        setPdfPath(null);
        lastNotifiedPdfPathRef.current = null;
        setWorkflowStage('processing');
        workflowStageRef.current = 'processing';
        startPolling(currentJobId);
      } else {
        toast.error(data.error || 'Failed to update input');
      }
    } catch (error: any) {
      console.error('Error saving edited input:', error);
      toast.error('Failed to update input', { description: error?.message });
    } finally {
      setIsSavingEditInput(false);
    }
  };

  // Step 4 CSV Review functions
  const fetchStep4CsvData = async (jobId: string) => {
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.step4CsvPreview(jobId), {
        headers: getAuthHeaders(token),
      });
      const data = await response.json();
      if (data.success) {
        setStep4CsvData(data.data);
        setStep4CsvColumns(data.columns);
      }
    } catch (error) {
      toast.error('Failed to load Step 4 CSV data');
      console.error('Step 4 CSV fetch error:', error);
    }
  };

  const handleDownloadStep4Csv = async () => {
    if (!currentJobId) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.step4DownloadCsv(currentJobId), {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'mapped_master_file.csv';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        toast.success('CSV downloaded successfully');
      } else {
        toast.error('Failed to download CSV');
      }
    } catch (error) {
      console.error('Step 4 CSV download error:', error);
      toast.error('Failed to download CSV');
    }
  };

  const handleUploadStep4Csv = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentJobId) return;
    
    setIsUploadingStep4Csv(true);
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.step4UploadCsv(currentJobId), {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
      });
      
      if (response.ok) {
        toast.success('Mapped master file CSV uploaded and replaced successfully');
        await fetchStep4CsvData(currentJobId);
      } else {
        toast.error('Failed to upload CSV');
      }
    } catch (error) {
      toast.error('Upload failed');
      console.error('Step 4 CSV upload error:', error);
    } finally {
      setIsUploadingStep4Csv(false);
      if (step4CsvFileInputRef.current) {
        step4CsvFileInputRef.current.value = '';
      }
    }
  };

  const handleStep4ContinuePipeline = async () => {
    if (!currentJobId) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.step4ContinuePipeline(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });
      
      const data = await response.json();
      
      if (response.ok && data.success) {
        toast.success('Continuing pipeline from Step 5');
        setWorkflowStage('processing');
        workflowStageRef.current = 'processing';
        setIsEditingStep4Csv(false);
        setHasStep4Edits(false);
        startPolling(currentJobId);
      } else {
        toast.error(data.error || 'Failed to continue pipeline');
      }
    } catch (error) {
      toast.error('Failed to continue pipeline');
      console.error('Continue pipeline error:', error);
    }
  };

  const handleStep4CellEdit = (rowIndex: number, column: string, value: string) => {
    const updatedData = [...step4CsvData];
    updatedData[rowIndex] = { ...updatedData[rowIndex], [column]: value };
    setStep4CsvData(updatedData);
    setHasStep4Edits(true);
  };

  // Apply multiple field updates at once — used by the auto-fill flow
  // when changing STOCK SYMBOL fans out to LISTED NAME / SHORT NAME /
  // SECURITY ID / EXCHANGE / INSTRUMENT.
  const applyStep4RowUpdates = (rowIndex: number, updates: Record<string, string>) => {
    setStep4CsvData(prev => {
      const next = [...prev];
      next[rowIndex] = { ...next[rowIndex], ...updates };
      return next;
    });
    setHasStep4Edits(true);
  };

  // After the user finishes editing the STOCK SYMBOL cell, look it up
  // in the Dhan Scrip Master CSV and auto-fill the dependent fields
  // (listed name, short name, security id, exchange, instrument). The
  // existing EXCHANGE value (NSE/BSE) is passed as a hint so dual-listed
  // symbols resolve to the user's preferred exchange.
  const lookupSymbolAndFill = async (rowIndex: number, symbol: string) => {
    const sym = (symbol || '').trim();
    const exchangeHint = (step4CsvData[rowIndex]?.['EXCHANGE'] || '').toString().trim().toUpperCase();

    // Always clear dependent fields up-front so that a failed lookup
    // (or a now-empty symbol) cannot leave stale metadata attached to a
    // different stock — that would corrupt downstream CMP/chart/PDF
    // generation. Fields are re-populated below on success.
    const cleared = {
      'LISTED NAME': '',
      'SHORT NAME':  '',
      'SECURITY ID': '',
      'EXCHANGE':    '',
      'INSTRUMENT':  '',
    } as Record<string, string>;

    if (!sym) {
      applyStep4RowUpdates(rowIndex, cleared);
      return;
    }

    applyStep4RowUpdates(rowIndex, cleared);

    try {
      const r = await fetch(
        API_ENDPOINTS.bulkRationale.scripMasterLookup(sym, exchangeHint || undefined),
        { headers: getAuthHeaders(token) },
      );
      const j = await r.json();
      if (!r.ok || !j.success) {
        toast.error(j.error || `No master-file match for "${sym}"`);
        return;
      }
      const d = j.data || {};
      applyStep4RowUpdates(rowIndex, {
        'STOCK SYMBOL': d['STOCK SYMBOL'] || sym.toUpperCase(),
        'LISTED NAME':  d['LISTED NAME']  || '',
        'SHORT NAME':   d['SHORT NAME']   || '',
        'SECURITY ID':  d['SECURITY ID']  || '',
        'EXCHANGE':     d['EXCHANGE']     || '',
        'INSTRUMENT':   d['INSTRUMENT']   || '',
      });
      toast.success(`Auto-filled from master file (${d['EXCHANGE'] || 'master'})`);
    } catch (err: any) {
      toast.error(err?.message || 'Symbol lookup failed');
    }
  };

  const handleSaveStep4Edits = async () => {
    if (!currentJobId || step4CsvData.length === 0) return;
    
    setIsSavingStep4Edits(true);
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.step4SaveEdits(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
        body: JSON.stringify({ data: step4CsvData, columns: step4CsvColumns }),
      });
      
      const data = await response.json();
      
      if (response.ok && data.success) {
        toast.success('CSV changes saved successfully');
        setHasStep4Edits(false);
      } else {
        toast.error(data.error || 'Failed to save changes');
      }
    } catch (error) {
      toast.error('Failed to save changes');
      console.error('Save edits error:', error);
    } finally {
      setIsSavingStep4Edits(false);
    }
  };

  const handleSaveAndContinueStep4 = async () => {
    if (!currentJobId) return;
    
    if (hasStep4Edits) {
      setIsSavingStep4Edits(true);
      try {
        const response = await fetch(API_ENDPOINTS.bulkRationale.step4SaveEdits(currentJobId), {
          method: 'POST',
          headers: getAuthHeaders(token),
          body: JSON.stringify({ data: step4CsvData, columns: step4CsvColumns }),
        });
        
        const data = await response.json();
        
        if (!response.ok || !data.success) {
          toast.error(data.error || 'Failed to save changes');
          setIsSavingStep4Edits(false);
          return;
        }
        
        toast.success('CSV changes saved');
        setHasStep4Edits(false);
        setIsEditingStep4Csv(false);
      } catch (error) {
        toast.error('Failed to save changes');
        console.error('Save edits error:', error);
        setIsSavingStep4Edits(false);
        return;
      } finally {
        setIsSavingStep4Edits(false);
      }
    }
    
    await handleStep4ContinuePipeline();
  };

  // Step 6 Failed Charts functions
  const fetchFailedCharts = async (jobId: string) => {
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.failedCharts(jobId), {
        headers: getAuthHeaders(token),
      });
      const data = await response.json();
      if (data.success) {
        setFailedCharts(data.failed_charts || []);
        setSuccessChartCount(data.success_count || 0);
      }
    } catch (error) {
      toast.error('Failed to load failed charts data');
      console.error('Failed charts fetch error:', error);
    }
  };

  const handleUploadChart = async (stockIndex: number, file: File) => {
    if (!currentJobId) return;
    
    setUploadingChartIndex(stockIndex);
    const formData = new FormData();
    formData.append('chart', file);
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.uploadChart(currentJobId, stockIndex), {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
      });
      
      const data = await response.json();
      
      if (response.ok && data.success) {
        toast.success(data.message || 'Chart uploaded successfully');
        setFailedCharts(prev => prev.map(fc => 
          fc.index === stockIndex ? { ...fc, uploaded: true } : fc
        ));
      } else {
        toast.error(data.error || 'Failed to upload chart');
      }
    } catch (error) {
      toast.error('Upload failed');
      console.error('Chart upload error:', error);
    } finally {
      setUploadingChartIndex(null);
    }
  };

  const handleChartFileChange = (stockIndex: number, event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      handleUploadChart(stockIndex, file);
    }
  };

  const handleStep6ContinuePipeline = async () => {
    if (!currentJobId) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.step6ContinuePipeline(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });
      
      const data = await response.json();
      
      if (response.ok && data.success) {
        toast.success('Generating PDF report...');
        setWorkflowStage('processing');
        workflowStageRef.current = 'processing';
        startPolling(currentJobId);
      } else {
        toast.error(data.error || 'Failed to continue pipeline');
      }
    } catch (error) {
      toast.error('Failed to continue pipeline');
      console.error('Continue pipeline error:', error);
    }
  };

  const handleSkipFailedCharts = async () => {
    if (!currentJobId) return;
    
    try {
      const response = await fetch(API_ENDPOINTS.bulkRationale.skipFailedCharts(currentJobId), {
        method: 'POST',
        headers: getAuthHeaders(token),
      });
      
      const data = await response.json();
      
      if (response.ok && data.success) {
        toast.info('Skipping failed charts and generating PDF...');
        setWorkflowStage('processing');
        workflowStageRef.current = 'processing';
        startPolling(currentJobId);
      } else {
        toast.error(data.error || 'Failed to skip charts');
      }
    } catch (error) {
      toast.error('Failed to skip charts');
      console.error('Skip charts error:', error);
    }
  };

  const handleReset = () => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }
    setCurrentJobId(null);
    setProgress(0);
    setWorkflowStage('input');
    workflowStageRef.current = 'input';
    setJobStatus('');
    setJobSteps([]);
    setRationaleTitle('');
    setSaveType(null);
    setPdfPath(null);
    setPdfBlobUrl(null);
    setInputText('');
    setYoutubeUrl('');
    setStep4CsvData([]);
    setStep4CsvColumns([]);
    setFailedCharts([]);
    setSuccessChartCount(0);
    lastNotifiedPdfPathRef.current = null;
  };

  const renderStepStatus = (step: JobStep) => {
    const status = step.status;
    switch (status) {
      case 'success':
        return <CheckCircle2 className="h-5 w-5 text-green-500" />;
      case 'running':
        return <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />;
      case 'failed':
        return <XCircle className="h-5 w-5 text-red-500" />;
      default:
        return <Clock className="h-5 w-5 text-gray-400" />;
    }
  };

  const renderRightPanel = () => {
    if (workflowStage === 'processing') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-slate-800">Processing Job</h3>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-12 text-center">
            <Loader2 className="w-16 h-16 mx-auto mb-4 text-purple-500 animate-spin" />
            <p className="text-slate-700">Processing your bulk rationale...</p>
            <p className="text-sm text-slate-500 mt-2">{jobStatus}</p>
          </div>
        </div>
      );
    }

    // Step 4 CSV Review Stage
    if (workflowStage === 'step4-review') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-purple-600 flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5" />
              Step 4 Complete - Review Mapped Master File
            </h3>
          </div>
          
          <p className="text-slate-600">
            Review the stock symbol mapping below. You can edit cells directly in the table, or download/upload the CSV file.
          </p>

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-3">
            <Button 
              onClick={() => setIsEditingStep4Csv(!isEditingStep4Csv)} 
              variant="outline" 
              className={isEditingStep4Csv ? "border-orange-500 text-orange-600 bg-orange-50" : "border-slate-300 text-slate-600 hover:bg-slate-50"}
            >
              <FileEdit className="w-4 h-4 mr-2" />
              {isEditingStep4Csv ? 'Exit Edit Mode' : 'Edit Table'}
            </Button>
            {hasStep4Edits && (
              <Button 
                onClick={handleSaveStep4Edits} 
                variant="outline"
                disabled={isSavingStep4Edits}
                className="border-green-500 text-green-600 hover:bg-green-50"
              >
                <Save className="w-4 h-4 mr-2" />
                {isSavingStep4Edits ? 'Saving...' : 'Save Changes'}
              </Button>
            )}
            <Button 
              onClick={handleDownloadStep4Csv} 
              variant="outline" 
              className="border-blue-500/50 text-blue-500 hover:bg-blue-500/10"
            >
              <Download className="w-4 h-4 mr-2" />
              Download CSV
            </Button>
            <Button 
              onClick={() => step4CsvFileInputRef.current?.click()} 
              variant="outline"
              disabled={isUploadingStep4Csv}
              className="border-purple-500/50 text-purple-500 hover:bg-purple-500/10"
            >
              <Upload className="w-4 h-4 mr-2" />
              {isUploadingStep4Csv ? 'Uploading...' : 'Upload CSV'}
            </Button>
            <input
              ref={step4CsvFileInputRef}
              type="file"
              accept=".csv"
              onChange={handleUploadStep4Csv}
              style={{ display: 'none' }}
            />
            <Button 
              onClick={hasStep4Edits ? handleSaveAndContinueStep4 : handleStep4ContinuePipeline}
              disabled={isSavingStep4Edits}
              className="bg-green-600 hover:bg-green-700 text-white ml-auto"
            >
              <Play className="w-4 h-4 mr-2" />
              {hasStep4Edits ? 'Save & Continue' : 'Continue to Step 5'}
            </Button>
          </div>
          
          {isEditingStep4Csv && (
            <div className="bg-orange-50 border border-orange-200 rounded-lg px-3 py-2 text-sm text-orange-700">
              Click on any cell to edit. Changes are highlighted. Click "Save Changes" or "Save & Continue" when done.
            </div>
          )}
          
          {/* Table Section
              Display order is fixed (per user spec): date, time, input
              stock, stock symbol, listed name, short name, security id,
              exchange, instrument, analysis, chart type. Only the
              user-input columns are editable; the master-file derived
              columns (LISTED NAME / SHORT NAME / SECURITY ID /
              EXCHANGE / INSTRUMENT) are auto-filled when STOCK SYMBOL
              changes via the Scrip Master lookup endpoint. */}
          {(() => {
            const STEP4_DISPLAY_ORDER = [
              'DATE', 'TIME', 'INPUT STOCK',
              'STOCK SYMBOL', 'LISTED NAME', 'SHORT NAME',
              'SECURITY ID', 'EXCHANGE', 'INSTRUMENT',
              'ANALYSIS', 'CHART TYPE',
            ];
            const STEP4_EDITABLE = new Set([
              'DATE', 'TIME', 'INPUT STOCK', 'CHART TYPE',
              'STOCK SYMBOL', 'ANALYSIS',
            ]);
            // Always render the canonical column order; fall back to
            // any extra columns the CSV might carry (forward-compat).
            const cols = [
              ...STEP4_DISPLAY_ORDER.filter(c => step4CsvColumns.includes(c)),
              ...step4CsvColumns.filter(c => !STEP4_DISPLAY_ORDER.includes(c)),
            ];
            const colMinWidth = (col: string) => {
              if (col === 'ANALYSIS')      return '320px';
              if (col === 'LISTED NAME')   return '200px';
              if (col === 'INPUT STOCK')   return '160px';
              if (col === 'STOCK SYMBOL')  return '150px';
              if (col === 'SHORT NAME')    return '140px';
              if (col === 'INSTRUMENT')    return '110px';
              if (col === 'CHART TYPE')    return '110px';
              if (col === 'DATE' || col === 'TIME') return '110px';
              return '120px';
            };
            const inputType = (col: string) => {
              if (col === 'DATE') return 'date';
              if (col === 'TIME') return 'time';
              return 'text';
            };
            return step4CsvData.length > 0 ? (
              <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
                <div className="overflow-x-auto" style={{ maxHeight: '500px' }}>
                  <table className="w-full text-sm border-collapse">
                    <thead className="bg-slate-100 sticky top-0 z-10">
                      <tr>
                        {cols.map(col => (
                          <th
                            key={col}
                            className="px-4 py-3 text-left font-semibold text-slate-700 border-b-2 border-slate-200 whitespace-nowrap"
                            style={{ minWidth: colMinWidth(col) }}
                            title={!STEP4_EDITABLE.has(col) ? 'Auto-filled from master file' : undefined}
                          >
                            {col}
                            {isEditingStep4Csv && !STEP4_EDITABLE.has(col) && (
                              <span className="ml-1 text-[10px] font-normal text-slate-400 uppercase">auto</span>
                            )}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="bg-white">
                      {step4CsvData.map((row, idx) => (
                        <tr
                          key={idx}
                          className="border-b border-slate-100 hover:bg-slate-50 transition-colors"
                        >
                          {cols.map(col => {
                            const editable = isEditingStep4Csv && STEP4_EDITABLE.has(col);
                            const cellPad = isEditingStep4Csv ? 'p-1' : 'px-4 py-3';
                            // Read-only / display cell.
                            if (!editable) {
                              if (col === 'ANALYSIS') {
                                return (
                                  <td key={col} className={`${cellPad} text-slate-700 align-top`}>
                                    <div className="max-w-xs truncate" title={row[col] || ''}>
                                      {row[col] || '-'}
                                    </div>
                                  </td>
                                );
                              }
                              const isMissingSymbol = !row[col] && col === 'STOCK SYMBOL';
                              const isAutoField = isEditingStep4Csv && !STEP4_EDITABLE.has(col);
                              return (
                                <td
                                  key={col}
                                  className={`${cellPad} align-top ${isAutoField ? 'bg-slate-50 text-slate-500' : 'text-slate-700'}`}
                                >
                                  <span className={isMissingSymbol ? 'text-red-500 font-medium' : ''}>
                                    {row[col] || (col === 'STOCK SYMBOL' ? 'NO MATCH' : '-')}
                                  </span>
                                </td>
                              );
                            }
                            // Editable cell.
                            if (col === 'ANALYSIS') {
                              return (
                                <td key={col} className={`${cellPad} align-top`}>
                                  <textarea
                                    value={row[col] || ''}
                                    onChange={(e) => handleStep4CellEdit(idx, col, e.target.value)}
                                    className="w-full min-h-[60px] px-2 py-1 text-sm border border-slate-300 rounded focus:border-purple-500 focus:ring-1 focus:ring-purple-500 resize-y"
                                  />
                                </td>
                              );
                            }
                            if (col === 'CHART TYPE') {
                              return (
                                <td key={col} className={`${cellPad} align-top`}>
                                  <select
                                    value={row[col] || 'Daily'}
                                    onChange={(e) => handleStep4CellEdit(idx, col, e.target.value)}
                                    className="w-full px-2 py-1 text-sm border border-slate-300 rounded bg-white focus:border-purple-500 focus:ring-1 focus:ring-purple-500"
                                  >
                                    <option value="Daily">Daily</option>
                                    <option value="Weekly">Weekly</option>
                                    <option value="Monthly">Monthly</option>
                                    <option value="Intraday">Intraday</option>
                                  </select>
                                </td>
                              );
                            }
                            // STOCK SYMBOL — on blur or Enter, lookup
                            // the master file and auto-fill the
                            // dependent columns.
                            const isSymbol = col === 'STOCK SYMBOL';
                            return (
                              <td key={col} className={`${cellPad} align-top`}>
                                <input
                                  type={inputType(col)}
                                  value={row[col] || ''}
                                  onChange={(e) => handleStep4CellEdit(idx, col, e.target.value)}
                                  onBlur={isSymbol ? (e) => lookupSymbolAndFill(idx, e.target.value) : undefined}
                                  onKeyDown={isSymbol ? (e) => {
                                    if (e.key === 'Enter') {
                                      e.preventDefault();
                                      // Trigger the lookup directly so a row
                                      // refresh happens immediately without
                                      // relying on the blur handler firing.
                                      lookupSymbolAndFill(idx, (e.target as HTMLInputElement).value);
                                    }
                                  } : undefined}
                                  className={`w-full px-2 py-1 text-sm border rounded focus:border-purple-500 focus:ring-1 focus:ring-purple-500 ${
                                    isSymbol && !row[col]
                                      ? 'border-red-300 bg-red-50'
                                      : 'border-slate-300'
                                  }`}
                                />
                                {isSymbol && (
                                  <div className="text-[10px] text-slate-400 mt-0.5">
                                    Tab / Enter to auto-fill
                                  </div>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="bg-white border border-slate-200 rounded-lg p-12 text-center">
                <Loader2 className="w-8 h-8 mx-auto mb-4 text-purple-500 animate-spin" />
                <p className="text-slate-600">Loading mapped master file data...</p>
              </div>
            );
          })()}
        </div>
      );
    }

    // Step 6 Chart Upload Stage
    if (workflowStage === 'step6-chart-upload') {
      const pendingUploads = failedCharts.filter(fc => !fc.uploaded);
      const uploadedCount = failedCharts.filter(fc => fc.uploaded).length;
      
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-orange-600 flex items-center gap-2">
              <XCircle className="h-5 w-5" />
              Step 6 - Some Charts Need Manual Upload
            </h3>
          </div>
          
          <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
            <p className="text-orange-800 text-sm">
              <strong>{successChartCount}</strong> charts generated successfully. 
              <strong className="text-red-600 ml-1">{failedCharts.length}</strong> chart(s) could not be generated automatically.
              {uploadedCount > 0 && (
                <span className="text-green-600 ml-1">
                  ({uploadedCount} uploaded)
                </span>
              )}
            </p>
            <p className="text-orange-700 text-sm mt-2">
              You can upload replacement charts for the failed stocks below, or skip them to continue without these charts.
            </p>
          </div>

          {/* Failed Charts List */}
          <div className="space-y-3">
            {failedCharts.map((chart) => (
              <div 
                key={chart.index}
                className={`border rounded-lg p-4 ${
                  chart.uploaded 
                    ? 'border-green-300 bg-green-50' 
                    : 'border-slate-200 bg-white'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-800">
                        {chart.stock_name}
                      </span>
                      {chart.symbol && (
                        <span className="text-sm text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                          {chart.symbol}
                        </span>
                      )}
                      {chart.uploaded && (
                        <CheckCircle2 className="h-4 w-4 text-green-500" />
                      )}
                    </div>
                    <p className="text-xs text-red-500 mt-1">{chart.error}</p>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    {chart.uploaded ? (
                      <span className="text-sm text-green-600 font-medium">Uploaded</span>
                    ) : (
                      <>
                        <input
                          ref={(el) => { chartFileInputRefs.current[chart.index] = el; }}
                          type="file"
                          accept=".png,.jpg,.jpeg"
                          onChange={(e) => handleChartFileChange(chart.index, e)}
                          style={{ display: 'none' }}
                        />
                        <Button
                          size="sm"
                          onClick={() => chartFileInputRefs.current[chart.index]?.click()}
                          disabled={uploadingChartIndex === chart.index}
                          className="bg-purple-600 hover:bg-purple-700 text-white"
                        >
                          {uploadingChartIndex === chart.index ? (
                            <>
                              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                              Uploading...
                            </>
                          ) : (
                            <>
                              <Upload className="w-4 h-4 mr-1" />
                              Upload Chart
                            </>
                          )}
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Action Buttons */}
          <div className="flex gap-3 pt-4 border-t border-slate-200">
            <Button
              onClick={handleSkipFailedCharts}
              variant="outline"
              className="border-slate-300 text-slate-600 hover:bg-slate-50"
            >
              Skip & Continue Without Charts
            </Button>
            <Button
              onClick={handleStep6ContinuePipeline}
              className="bg-green-600 hover:bg-green-700 text-white ml-auto"
            >
              <Play className="w-4 h-4 mr-2" />
              Generate PDF Report
            </Button>
          </div>
        </div>
      );
    }

    if (workflowStage === 'pdf-preview') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-slate-800">Generated PDF Report</h3>
          </div>

          <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
            {pdfBlobUrl ? (
              <iframe
                src={pdfBlobUrl}
                className="w-full h-[500px]"
                title="PDF Report Preview"
              />
            ) : (
              <div className="w-full h-[500px] flex items-center justify-center bg-slate-100">
                <p className="text-slate-500">Loading PDF...</p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Button
              onClick={() => {
                if (pdfBlobUrl) {
                  const a = document.createElement('a');
                  a.href = pdfBlobUrl;
                  a.download = `${currentJobId}_bulk_rationale.pdf`;
                  a.click();
                }
              }}
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
              onClick={handleDelete}
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

    if (workflowStage === 'upload-signed') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-slate-800">Upload Signed PDF</h3>
          </div>
          
          <div className="bg-white border border-slate-200 rounded-lg p-6">
            {currentJobId && (
              <SignedFileUpload
                jobId={currentJobId}
                uploadEndpoint={API_ENDPOINTS.bulkRationale.uploadSigned(currentJobId)}
                onUploadComplete={handleSignedUploadComplete}
              />
            )}
          </div>
        </div>
      );
    }

    if (workflowStage === 'completed' || workflowStage === 'saved') {
      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-green-600 flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5" />
              Job Completed
            </h3>
          </div>

          <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
            {pdfBlobUrl ? (
              <iframe
                src={pdfBlobUrl}
                className="w-full h-[500px]"
                title="PDF Report Preview"
              />
            ) : (
              <div className="w-full h-[500px] flex items-center justify-center bg-slate-100">
                <p className="text-slate-500">PDF saved to Saved Rationale</p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Button onClick={() => onNavigate('saved-rationale')} className="bg-purple-600 hover:bg-purple-700 text-white">
              View Saved Rationale
            </Button>
            <Button variant="outline" onClick={handleReset}>
              Start New Analysis
            </Button>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center gap-4 mb-6">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onNavigate('dashboard')}
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-purple-600 flex items-center justify-center shadow-lg">
              <Layers className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-800">Bulk Rationale</h1>
              <p className="text-slate-500">Generate multiple stock rationales from text input</p>
            </div>
          </div>
        </div>

        {workflowStage === 'input' && (
          <Card>
            <CardHeader>
              <CardTitle>Input Details</CardTitle>
              <CardDescription>
                Enter the channel/platform details and paste your stock calls text
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Channel/Platform *</Label>
                  <Select value={selectedChannelId} onValueChange={setSelectedChannelId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select platform" />
                    </SelectTrigger>
                    <SelectContent>
                      {channels.map((channel) => (
                        <SelectItem key={channel.id} value={String(channel.id)}>
                          {channel.platform} - {channel.channel_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>YouTube URL (Optional)</Label>
                  <Input
                    placeholder="https://youtube.com/watch?v=..."
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Date *</Label>
                  <Input
                    type="date"
                    value={callDate}
                    onChange={(e) => setCallDate(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Time *</Label>
                  <Input
                    type="time"
                    value={callTime}
                    onChange={(e) => setCallTime(e.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Input Text *</Label>
                <Textarea
                  placeholder="Paste your stock calls text here... (can be in Hindi or English)"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  rows={10}
                  className="font-mono"
                  data-tour="bulk-input"
                />
                <p className="text-sm text-slate-500">
                  Paste stock calls, recommendations, or analysis text. The system will translate, 
                  extract stocks, fetch prices, generate charts, and create a PDF report.
                </p>
              </div>

              <Button 
                onClick={handleStartAnalysis}
                disabled={!selectedChannelId || !callDate || !inputText.trim()}
                className="w-full"
                size="lg"
                data-tour="bulk-generate"
              >
                <Play className="h-5 w-5 mr-2" />
                Generate Rationale
              </Button>
            </CardContent>
          </Card>
        )}

        {currentJobId && jobSteps.length > 0 && workflowStage !== 'input' && (
          <Card className="shadow-sm">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
              {/* Left Column: 6-Step Pipeline */}
              <div className="space-y-4">
                <div className="flex items-start justify-between mb-4 gap-3">
                  <div className="min-w-0">
                    <h3 className="text-lg font-semibold text-slate-800">6-Step Pipeline</h3>
                    <p className="text-sm text-slate-500 truncate">Job ID: {currentJobId}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      onClick={handleOpenEditInput}
                      variant="outline"
                      size="sm"
                      className="h-9 border-slate-300 text-slate-700 hover:bg-slate-100"
                      title="Edit input and restart from Step 1"
                    >
                      <Pencil className="w-4 h-4 mr-1" />
                      Edit Input
                    </Button>
                    <Button
                      onClick={handleDelete}
                      variant="outline"
                      size="icon"
                      className="h-9 w-9 border-red-300 text-red-600 hover:bg-red-50 hover:text-red-700 hover:border-red-400"
                      title="Delete this job"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>

                {/* Progress Bar with Restart Selector */}
                <div className="mb-4">
                  <div className="flex justify-between text-sm text-slate-600 mb-2">
                    <span>Progress</span>
                    <span>{progress}%</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 bg-slate-200 rounded-full h-3">
                      <div 
                        className="bg-gradient-to-r from-purple-500 to-purple-600 h-3 rounded-full transition-all duration-500"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    
                    <div className="flex items-center gap-2">
                      <Select
                        value={selectedRestartStep.toString()}
                        onValueChange={(value) => setSelectedRestartStep(parseInt(value, 10))}
                        disabled={isRestarting}
                      >
                        <SelectTrigger className="w-[100px] h-9">
                          <SelectValue placeholder="Step" />
                        </SelectTrigger>
                        <SelectContent>
                          {jobSteps.filter(s => s.status === 'success' || s.status === 'failed' || s.status === 'running').map((step) => (
                            <SelectItem key={step.step_number} value={step.step_number.toString()}>
                              Step {step.step_number}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      
                      <Button
                        onClick={() => handleRestartStep(selectedRestartStep)}
                        disabled={isRestarting || jobSteps.filter(s => s.status !== 'pending').length === 0}
                        variant="outline"
                        size="sm"
                        className="h-9 px-3 bg-purple-50 border-purple-300 text-purple-700 hover:bg-purple-100 hover:border-purple-400"
                        title={`Restart from step ${selectedRestartStep}`}
                      >
                        {isRestarting ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <RotateCcw className="w-4 h-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Steps List */}
                <div className="space-y-2 max-h-[500px] overflow-y-auto pr-2">
                  {jobSteps.map((step) => (
                    <div 
                      key={step.step_number}
                      className={`flex items-center justify-between p-3 rounded-lg border ${
                        step.status === 'running' ? 'bg-blue-50 border-blue-200' :
                        step.status === 'success' ? 'bg-green-50 border-green-200' :
                        step.status === 'failed' ? 'bg-red-50 border-red-200' :
                        'bg-slate-50 border-slate-200'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        {renderStepStatus(step)}
                        <div>
                          <p className="font-medium text-sm">Step {step.step_number}: {step.name || step.step_name}</p>
                          {step.message && (
                            <p className="text-xs text-slate-600">{step.message}</p>
                          )}
                        </div>
                      </div>
                      {step.status === 'failed' && (
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => handleRestartStep(step.step_number)}
                          disabled={isRestarting}
                          className="h-7 text-xs"
                        >
                          <RefreshCw className="h-3 w-3 mr-1" />
                          Retry
                        </Button>
                      )}
                      {step.status === 'success' && (
                        <Button 
                          variant="ghost" 
                          size="sm"
                          onClick={() => handleRestartStep(step.step_number)}
                          disabled={isRestarting}
                          className="h-7 text-xs text-slate-500 hover:text-purple-600"
                        >
                          <RotateCcw className="h-3 w-3 mr-1" />
                          Reload
                        </Button>
                      )}
                    </div>
                  ))}
                </div>

                {/* New Analysis Button */}
                {(workflowStage === 'pdf-preview' || workflowStage === 'completed' || workflowStage === 'saved') && (
                  <Button
                    variant="outline"
                    onClick={handleReset}
                    className="w-full mt-4 border-purple-500/50 text-purple-600 hover:bg-purple-50"
                  >
                    <RotateCcw className="w-4 h-4 mr-2" />
                    New Analysis
                  </Button>
                )}
              </div>

              {/* Right Column: Dynamic Content Based on Workflow Stage */}
              <div className="space-y-4">
                {renderRightPanel()}
              </div>
            </div>
          </Card>
        )}
      </div>

      {/* Edit Input Dialog */}
      <Dialog open={isEditInputOpen} onOpenChange={setIsEditInputOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Input</DialogTitle>
            <DialogDescription>
              Update any field below and save to restart the pipeline from Step 1
              with the new data. All previously generated outputs will be cleared.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="edit-channel">Channel *</Label>
                <Select value={editChannelId} onValueChange={setEditChannelId}>
                  <SelectTrigger id="edit-channel">
                    <SelectValue placeholder="Select channel" />
                  </SelectTrigger>
                  <SelectContent>
                    {channels.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.platform} - {c.channel_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-youtube">YouTube URL</Label>
                <Input
                  id="edit-youtube"
                  type="url"
                  placeholder="https://youtube.com/..."
                  value={editYoutubeUrl}
                  onChange={(e) => setEditYoutubeUrl(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-date">Call Date *</Label>
                <Input
                  id="edit-date"
                  type="date"
                  value={editCallDate}
                  onChange={(e) => setEditCallDate(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-time">Call Time</Label>
                <Input
                  id="edit-time"
                  type="time"
                  value={editCallTime}
                  onChange={(e) => setEditCallTime(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-input-text">Input Text *</Label>
              <Textarea
                id="edit-input-text"
                placeholder="Paste stock calls, recommendations, or analysis text..."
                value={editInputText}
                onChange={(e) => setEditInputText(e.target.value)}
                style={{ height: '240px', maxHeight: '240px', overflowY: 'auto', resize: 'none' }}
                className="font-mono"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsEditInputOpen(false)}
              disabled={isSavingEditInput}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSaveEditInput}
              disabled={
                isSavingEditInput ||
                !editChannelId ||
                !editCallDate ||
                !editInputText.trim()
              }
              className="bg-purple-600 hover:bg-purple-700 text-white"
            >
              {isSavingEditInput ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <RotateCcw className="w-4 h-4 mr-2" />
                  Save & Restart
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
