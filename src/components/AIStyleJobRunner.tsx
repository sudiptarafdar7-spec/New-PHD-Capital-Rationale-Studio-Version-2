import { useState, useEffect } from 'react';
import { RotateCcw, Loader2, CheckCircle2, XCircle, Sparkles } from 'lucide-react';
import { Button } from './ui/button';
import { Card } from './ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';
import { getStepConfig, getTotalSteps } from '../lib/ai-steps-config';

interface JobStep {
  step_number: number;
  name: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  message?: string | null;
  outputFiles?: string[];
}

interface AIStyleJobRunnerProps {
  jobSteps: JobStep[];
  currentStepNumber: number;
  progressPercent: number;
  jobStatus: string;
  jobId?: string;
  onRestart?: () => void;
  onStepRestart?: (jobId: string, stepNumber: number) => void;
  isRestarting?: boolean;
}

export default function AIStyleJobRunner({
  jobSteps,
  currentStepNumber,
  progressPercent,
  jobStatus,
  jobId,
  onStepRestart,
  isRestarting = false
}: AIStyleJobRunnerProps) {
  const totalSteps = getTotalSteps();
  const [selectedStep, setSelectedStep] = useState<number>(1);
  
  // Calculate the actual display step number from jobSteps array
  // Prefer: running → failed → next pending → default to 1
  const calculateDisplayStep = (): number => {
    // Find first running step
    const runningStep = jobSteps.find(step => step.status === 'running');
    if (runningStep) return runningStep.step_number;
    
    // Find first failed step
    const failedStep = jobSteps.find(step => step.status === 'failed');
    if (failedStep) return failedStep.step_number;
    
    // Find next pending step
    const pendingStep = jobSteps.find(step => step.status === 'pending');
    if (pendingStep) return pendingStep.step_number;
    
    // Default to currentStepNumber if >= 1, otherwise step 1
    return Math.max(1, currentStepNumber);
  };
  
  const displayStepNumber = calculateDisplayStep();
  const currentStepConfig = getStepConfig(displayStepNumber);
  const currentJobStep = jobSteps.find(step => step.step_number === displayStepNumber);
  
  const isCompleted = displayStepNumber >= totalSteps && jobStatus !== 'failed';

  // Sync selected step with current display step
  useEffect(() => {
    setSelectedStep(displayStepNumber);
  }, [displayStepNumber]);

  // Handle restart button click
  const handleRestart = () => {
    if (jobId && onStepRestart) {
      onStepRestart(jobId, selectedStep);
    }
  };

  // Extract metric from step message if available (lightweight parsing, no backend changes)
  const getMetricValue = (): number | null => {
    if (!currentJobStep || !currentStepConfig?.showMetrics) return null;

    const message = currentJobStep.message || '';
    
    // Try to extract numbers from success messages like "Extracted 25 stocks" or "Fetched 10 charts"
    const numberMatch = message.match(/(\d+)\s+(stocks?|charts?)/i);
    if (numberMatch) {
      return parseInt(numberMatch[1], 10);
    }

    return null;
  };

  const metricValue = getMetricValue();
  const StepIcon = currentStepConfig?.icon || Sparkles;

  // Determine pill state and message
  const pillState = currentJobStep?.status === 'failed' ? 'failed' : 
                    currentJobStep?.status === 'running' ? 'running' : 
                    isCompleted ? 'success' : 'running';
  
  const pillMessage = pillState === 'failed'
    ? (currentJobStep?.message || 'An error occurred during processing')
    : (currentStepConfig?.publicMessage || 'Processing');

  return (
    <Card className="relative overflow-hidden border border-slate-300 dark:border-slate-700/50 shadow-2xl bg-gradient-to-br from-slate-50 via-blue-50 to-slate-50 dark:from-slate-900 dark:via-blue-950 dark:to-slate-900 rounded-[40px]">
      {/* Prominent grid background - 70% coverage */}
      <div className="absolute inset-0 opacity-30 dark:opacity-70">
        <div className="absolute inset-0" style={{
          backgroundImage: 'linear-gradient(rgba(59, 130, 246, 0.15) 1.5px, transparent 1.5px), linear-gradient(90deg, rgba(59, 130, 246, 0.15) 1.5px, transparent 1.5px)',
          backgroundSize: '50px 50px'
        }}></div>
      </div>
      
      <div className="relative z-10 p-8 space-y-6">
        {/* AI Loader Icon */}
        <div className="flex justify-center">
          <div className="relative">
            {/* Outer glowing ring - animated pulse */}
            <div className="absolute inset-0 flex items-center justify-center animate-pulse-ring">
              <div className="w-32 h-32 rounded-full bg-blue-500/20 blur-xl"></div>
            </div>
            
            {/* Middle glow layer */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-28 h-28 rounded-full bg-gradient-to-r from-blue-500/30 via-cyan-500/30 to-blue-500/30 blur-lg animate-spin-slow"></div>
            </div>
            
            {/* Main loader icon with glowing border */}
            <div className="relative bg-white dark:bg-slate-800/50 border-2 border-blue-500/50 rounded-full p-5 shadow-2xl shadow-blue-500/50 flex items-center justify-center ring-4 ring-blue-500/20 ring-offset-2 ring-offset-transparent">
              {isCompleted ? (
                <CheckCircle2 className="w-14 h-14 text-blue-600 dark:text-blue-400" />
              ) : (
                <div className="relative w-14 h-14 flex items-center justify-center">
                  <Loader2 className="w-14 h-14 text-blue-600 dark:text-blue-400 animate-spin absolute" />
                  <StepIcon className="w-7 h-7 text-blue-500 dark:text-blue-300 relative z-10" />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Job ID Header */}
        {jobId && (
          <div className="text-center space-y-1">
            <div className="inline-flex items-center gap-2 bg-white/90 dark:bg-slate-700/90 backdrop-blur-sm px-6 py-3 rounded-2xl border border-slate-300 dark:border-slate-500/50">
              <span className="text-sm font-mono text-slate-900 dark:text-slate-200 tracking-wider">
                JOB ID: {jobId}
              </span>
            </div>
          </div>
        )}

        {/* Progress Information */}
        <div className="space-y-4 text-center">
          {/* Step Counter */}
          <div className="inline-flex items-center gap-2.5 bg-white/90 dark:bg-slate-700/90 backdrop-blur-sm px-6 py-3 rounded-2xl border border-slate-300 dark:border-slate-500/50">
            <Sparkles className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            <span className="text-base font-semibold text-slate-900 dark:text-white tracking-wide">
              STEP {displayStepNumber}/{totalSteps}
            </span>
          </div>

          {/* Current Step Message Box */}
          <div className="bg-white/90 dark:bg-slate-700/90 backdrop-blur-sm px-6 py-4 rounded-full border border-slate-300 dark:border-slate-500/50">
            <h3 className="text-2xl font-medium text-slate-900 dark:text-white">
              {currentStepConfig?.publicMessage || 'Processing'}
              <span className="animate-pulse-dots">...</span>
            </h3>
          </div>

          {/* Metric Display (for steps 8, 9, 11, 13) */}
          {metricValue !== null && (
            <div className="inline-flex items-center gap-2.5 bg-white/90 dark:bg-slate-700/90 backdrop-blur-sm text-slate-900 dark:text-slate-200 px-6 py-3 rounded-2xl border border-slate-300 dark:border-slate-500/50">
              <div className="w-2 h-2 bg-blue-600 dark:bg-blue-400 rounded-full"></div>
              <span className="font-medium text-sm">
                {metricValue} {currentStepConfig?.showMetrics === 'charts_fetched' ? 'charts' : 'stocks'} {currentStepConfig?.showMetrics === 'stocks_extracted' ? 'extracted' : currentStepConfig?.showMetrics === 'stocks_mapped' ? 'mapped' : currentStepConfig?.showMetrics === 'stocks_cmp' ? 'fetched' : 'generated'}
              </span>
            </div>
          )}
        </div>

        {/* Progress Bar - Clean Design with Restart Controls */}
        <div className="space-y-3 mt-6 bg-white/90 dark:bg-slate-700/90 backdrop-blur-sm rounded-full p-4 border border-slate-300 dark:border-slate-500/50">
          <div className="flex flex-col sm:flex-row items-center gap-3 sm:gap-4">
            {/* Progress Bar */}
            <div className="flex-1 w-full relative h-3 bg-slate-200 dark:bg-slate-600/70 rounded-full overflow-hidden border border-slate-300 dark:border-slate-500/50">
              {/* Progress Fill */}
              <div 
                className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full transition-all duration-500 ease-out"
                style={{ 
                  width: `${progressPercent}%`
                }}
              >
                {/* Subtle shimmer */}
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer"></div>
              </div>
            </div>
            
            {/* Percentage Badge */}
            <div className="bg-slate-200 dark:bg-slate-600/90 backdrop-blur-sm px-4 py-1.5 rounded-full border border-slate-300 dark:border-slate-500/60 min-w-[70px] text-center">
              <span className="text-base font-semibold text-slate-900 dark:text-white">
                {Math.round(progressPercent)}%
              </span>
            </div>

            {/* Restart Controls */}
            {jobId && onStepRestart && (
              <div className="flex items-center gap-2">
                {/* Step Selector Dropdown */}
                <Select
                  value={selectedStep.toString()}
                  onValueChange={(value: string) => setSelectedStep(parseInt(value, 10))}
                  disabled={isRestarting}
                >
                  <SelectTrigger className="w-[100px] h-9 bg-white dark:bg-slate-600 border-slate-300 dark:border-slate-500 text-slate-900 dark:text-white">
                    <SelectValue placeholder="Step" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: displayStepNumber }, (_, i) => i + 1).map((step) => (
                      <SelectItem key={step} value={step.toString()}>
                        Step {step}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* Restart Button */}
                <Button
                  onClick={handleRestart}
                  disabled={isRestarting}
                  variant="outline"
                  size="sm"
                  className="h-9 px-3 bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/50 hover:border-blue-400 dark:hover:border-blue-600"
                  title={`Restart from step ${selectedStep}`}
                >
                  {isRestarting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <RotateCcw className="w-4 h-4" />
                  )}
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Dynamic Status Pill - Shows progress message or error */}
        <div 
          className={`flex items-center justify-center gap-3 backdrop-blur-sm px-6 py-3 rounded-full border transition-all duration-300 ${
            pillState === 'failed'
              ? 'bg-red-50/90 dark:bg-red-950/30 border-red-300 dark:border-red-700 text-red-700 dark:text-red-300'
              : 'bg-white/90 dark:bg-slate-700/90 border-slate-300 dark:border-slate-500/50 text-slate-900 dark:text-slate-200'
          }`}
          role="status"
          aria-live="polite"
        >
          {pillState === 'failed' && <XCircle className="w-4 h-4 flex-shrink-0" />}
          <span className="text-sm font-medium">
            {pillMessage}
            {pillState !== 'failed' && <span className="animate-pulse-dots">...</span>}
          </span>
        </div>
      </div>

      <style>{`
        @keyframes shimmer {
          0% {
            transform: translateX(-100%);
          }
          100% {
            transform: translateX(100%);
          }
        }
        .animate-shimmer {
          animation: shimmer 3s infinite;
        }
        @keyframes pulse-dots {
          0%, 20% {
            opacity: 0.2;
          }
          40% {
            opacity: 1;
          }
          60%, 100% {
            opacity: 0.2;
          }
        }
        .animate-pulse-dots {
          animation: pulse-dots 1.5s ease-in-out infinite;
        }
        @keyframes pulse-ring {
          0%, 100% {
            opacity: 1;
            transform: scale(1);
          }
          50% {
            opacity: 0.5;
            transform: scale(1.1);
          }
        }
        .animate-pulse-ring {
          animation: pulse-ring 2s ease-in-out infinite;
        }
        @keyframes spin-slow {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }
        .animate-spin-slow {
          animation: spin-slow 8s linear infinite;
        }
      `}</style>
    </Card>
  );
}
