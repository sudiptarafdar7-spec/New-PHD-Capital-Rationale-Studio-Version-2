import React from 'react';
import { formatTimeIST } from '@/lib/datetime';
import { CheckCircle2, XCircle, Clock, Loader2, RotateCcw } from 'lucide-react';
import { JobStep } from '../types';
import { Card } from './ui/card';
import { Button } from './ui/button';
import { cn } from './ui/utils';

interface StepProgressTrackerProps {
  steps: JobStep[];
  currentStep?: number;
  completedSteps?: number;
  onRestartFromStep?: (stepNumber: number) => void;
}

export default function StepProgressTracker({ steps, currentStep, completedSteps, onRestartFromStep }: StepProgressTrackerProps) {
  // Determine step status based on currentStep if status is not provided
  const getStepStatus = (step: JobStep, index: number): JobStep['status'] => {
    if (step.status) return step.status;
    
    // If completedSteps is provided, use it to determine status
    if (completedSteps !== undefined) {
      if (index + 1 < completedSteps) return 'success';
      if (index + 1 === completedSteps) return 'running';
      return 'pending';
    }
    
    // Otherwise use currentStep
    if (currentStep !== undefined) {
      if (step.step_number < currentStep) return 'success';
      if (step.step_number === currentStep) return 'running';
      return 'pending';
    }
    
    return step.status || 'pending';
  };

  const getStepIcon = (status: JobStep['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-5 h-5 text-green-500" />;
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-500" />;
      case 'running':
        return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />;
      default:
        return <Clock className="w-5 h-5 text-muted-foreground" />;
    }
  };

  const getStepColor = (status: JobStep['status']) => {
    switch (status) {
      case 'success':
        return 'border-green-500/30 bg-green-500/10';
      case 'failed':
        return 'border-red-500/30 bg-red-500/10';
      case 'running':
        return 'border-blue-500/50 bg-blue-500/20';
      default:
        return 'border-border bg-card';
    }
  };

  const formatTime = (dateString?: string) => {
    if (!dateString) return '';
    return formatTimeIST(dateString);
  };

  return (
    <div className="space-y-3">
      {steps.map((step, index) => {
        const stepStatus = getStepStatus(step, index);
        return (
          <Card
            key={step.id || `step-${step.step_number}`}
            className={cn(
              'p-4 border transition-all duration-300',
              getStepColor(stepStatus)
            )}
          >
            <div className="flex items-start gap-4">
              {/* Step Number & Icon */}
              <div className="flex-shrink-0">
                <div className="flex items-center justify-center w-10 h-10 rounded-full bg-muted">
                  {getStepIcon(stepStatus)}
                </div>
              </div>

              {/* Step Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs text-muted-foreground font-mono">
                        Step {step.step_number}
                      </span>
                      {stepStatus === 'running' && (
                        <span className="px-2 py-0.5 bg-blue-500/20 text-blue-500 text-xs rounded-full animate-pulse">
                          In Progress
                        </span>
                      )}
                    </div>
                    <h4 className="text-foreground">{step.name}</h4>
                    {step.message && (
                      <p className={cn(
                        'text-sm mt-1',
                        stepStatus === 'failed' ? 'text-red-500' : 'text-muted-foreground'
                      )}>
                        {step.message}
                      </p>
                    )}
                  </div>
                  <div className="flex items-start gap-2">
                    {step.started_at && (
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground">
                          {formatTime(step.started_at)}
                        </p>
                        {step.ended_at && step.started_at && (
                          <p className="text-xs text-muted-foreground mt-1">
                            {Math.round((new Date(step.ended_at).getTime() - new Date(step.started_at).getTime()) / 1000)}s
                          </p>
                        )}
                      </div>
                    )}
                    {onRestartFromStep && (stepStatus === 'success' || stepStatus === 'failed') && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onRestartFromStep(step.step_number)}
                        className="h-8 w-8 p-0 hover:bg-blue-500/10 hover:text-blue-500"
                        title={`Restart from Step ${step.step_number}`}
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                </div>

                {/* Progress bar for running step */}
                {stepStatus === 'running' && (
                  <div className="mt-3">
                    <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
                      <div className="h-full bg-blue-500 rounded-full animate-pulse" style={{ width: '60%' }} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
