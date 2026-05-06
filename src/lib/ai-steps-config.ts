import { Video, Database, Mic, FileText, Languages, Users, UserX, TrendingUp, Link, Clock, DollarSign, FileBarChart, BarChart3, FileCheck } from 'lucide-react';

export interface StepConfig {
  stepNumber: number;
  publicMessage: string;
  icon: any;
  showMetrics?: 'stocks_extracted' | 'stocks_mapped' | 'stocks_cmp' | 'charts_fetched';
}

export const MEDIA_RATIONALE_STEPS: StepConfig[] = [
  {
    stepNumber: 1,
    publicMessage: "We are gathering your video data",
    icon: Video,
  },
  {
    stepNumber: 2,
    publicMessage: "Fetching additional data",
    icon: Database,
  },
  {
    stepNumber: 3,
    publicMessage: "Now Detecting Speech",
    icon: Mic,
  },
  {
    stepNumber: 4,
    publicMessage: "Polishing transcription",
    icon: FileText,
  },
  {
    stepNumber: 5,
    publicMessage: "Translating Video to English",
    icon: Languages,
  },
  {
    stepNumber: 6,
    publicMessage: "Detecting All Speakers",
    icon: Users,
  },
  {
    stepNumber: 7,
    publicMessage: "Removing Other Speakers",
    icon: UserX,
  },
  {
    stepNumber: 8,
    publicMessage: "Extracting All Stock Names",
    icon: TrendingUp,
    showMetrics: 'stocks_extracted',
  },
  {
    stepNumber: 9,
    publicMessage: "Mapping with Real Stock Data",
    icon: Link,
    showMetrics: 'stocks_mapped',
  },
  {
    stepNumber: 10,
    publicMessage: "Gathering Timestamp",
    icon: Clock,
  },
  {
    stepNumber: 11,
    publicMessage: "Fetching CMP",
    icon: DollarSign,
    showMetrics: 'stocks_cmp',
  },
  {
    stepNumber: 12,
    publicMessage: "Generating Rationale Overview",
    icon: FileBarChart,
  },
  {
    stepNumber: 13,
    publicMessage: "Fetching Candle Charts / applying indicators",
    icon: BarChart3,
    showMetrics: 'charts_fetched',
  },
  {
    stepNumber: 14,
    publicMessage: "Generating Final PDF",
    icon: FileCheck,
  },
];

export const getStepConfig = (stepNumber: number): StepConfig | undefined => {
  return MEDIA_RATIONALE_STEPS.find(step => step.stepNumber === stepNumber);
};

export const getTotalSteps = (): number => {
  return MEDIA_RATIONALE_STEPS.length;
};
