import React, { useState } from 'react';
import { formatDateIST, formatTimeIST } from '@/lib/datetime';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { Upload, FileCheck, Calendar, Clock, Download } from 'lucide-react';
import { toast } from 'sonner';

interface SignedFileUploadProps {
  jobId: string;
  uploadedFile?: {
    fileName: string;
    uploadedAt: string;
  } | null;
  onUploadComplete: (file: File) => void;
}

export default function SignedFileUpload({ uploadedFile: externalUploadedFile, onUploadComplete }: SignedFileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);

  const uploadedFile = externalUploadedFile;

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Please upload a PDF file');
      return;
    }

    toast.info('Uploading signed PDF...', {
      description: 'Please wait while we process your file',
    });

    // Call the parent handler which will handle the actual upload
    onUploadComplete(file);
  };

  const handleDownloadUnsigned = () => {
    toast.success('Downloading Unsigned PDF', {
      description: 'final_rationale_report.pdf',
    });
  };

  const handleDownloadSigned = () => {
    toast.success('Downloading Signed PDF', {
      description: uploadedFile?.fileName || 'signed_rationale_report.pdf',
    });
  };

  if (uploadedFile) {
    return (
      <div className="space-y-4">
        {/* Success Message */}
        <Card className="bg-card border-border p-6">
          <div className="flex items-center gap-3">
            <div className="p-3 bg-green-500/20 rounded-lg">
              <FileCheck className="w-6 h-6 text-green-500" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg text-foreground">Signed PDF Uploaded Successfully</h3>
              <p className="text-sm text-muted-foreground">
                Job completed and logged
              </p>
            </div>
          </div>

          {/* Signature Upload Information */}
          <div className="mt-4 bg-background border border-border rounded-lg p-4 space-y-2">
            <h4 className="text-sm text-foreground">Signature Upload Date Time Log</h4>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">File:</span>
                <span className="text-foreground truncate">{uploadedFile.fileName}</span>
              </div>
              
              <div className="flex items-center gap-2">
                <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-foreground">
                  {formatDateIST(uploadedFile.uploadedAt)}
                </span>
              </div>
              
              <div className="flex items-center gap-2">
                <Clock className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-foreground">
                  {formatTimeIST(uploadedFile.uploadedAt)}
                </span>
              </div>
            </div>
          </div>
        </Card>

        {/* Signed PDF Iframe */}
        <div className="space-y-3">
          <h3 className="text-foreground">Signed PDF Report</h3>
          <div className="bg-background border border-border rounded-lg overflow-hidden">
            <iframe
              src="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
              className="w-full h-[500px]"
              title="Signed PDF Report Preview"
            />
          </div>
        </div>

        {/* Download Buttons */}
        <div className="grid grid-cols-2 gap-3">
          <Button
            onClick={handleDownloadUnsigned}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            <Download className="w-4 h-4 mr-2" />
            Download Unsigned PDF
          </Button>
          <Button
            onClick={handleDownloadSigned}
            className="bg-green-600 hover:bg-green-700 text-white"
          >
            <Download className="w-4 h-4 mr-2" />
            Download Signed PDF
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Card className="bg-card border-border p-6">
      <div className="space-y-4">
        <div>
          <h3 className="text-lg text-foreground mb-2">Upload Signed PDF</h3>
          <p className="text-sm text-muted-foreground">
            Upload the signed version of the PDF report to complete the workflow
          </p>
        </div>

        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`
            border-2 border-dashed rounded-lg p-12 text-center transition-colors cursor-pointer
            ${isDragging 
              ? 'border-blue-500 bg-blue-500/10' 
              : 'border-border hover:border-blue-500/50 hover:bg-blue-500/5'
            }
          `}
          onClick={() => document.getElementById('signed-file-input')?.click()}
        >
          <div className="flex flex-col items-center gap-4">
            <div className={`p-4 rounded-full transition-colors ${
              isDragging ? 'bg-blue-500/20' : 'bg-muted'
            }`}>
              <Upload className={`w-10 h-10 ${
                isDragging ? 'text-blue-500' : 'text-muted-foreground'
              }`} />
            </div>
            
            <div>
              <p className="text-foreground mb-1">
                Drag and drop your signed PDF here
              </p>
              <p className="text-sm text-muted-foreground">
                or click to browse files
              </p>
            </div>

            <Button
              type="button"
              className="gradient-primary"
              onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                e.stopPropagation();
                document.getElementById('signed-file-input')?.click();
              }}
            >
              <Upload className="w-4 h-4 mr-2" />
              Choose File
            </Button>
          </div>

          <input
            id="signed-file-input"
            type="file"
            accept=".pdf"
            onChange={handleFileSelect}
            className="hidden"
          />
        </div>
      </div>
    </Card>
  );
}
