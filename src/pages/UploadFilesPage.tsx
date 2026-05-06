import React, { useState, useRef, useEffect } from 'react';
import { formatDateIST } from '@/lib/datetime';
import { Upload, FileText, Image as ImageIcon, CheckCircle2, Download, X, Loader2, Cookie } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/ui/alert-dialog';
import { toast } from 'sonner';
import { API_ENDPOINTS } from '../lib/api-config';
import { useAuth } from '../lib/auth-context';

interface UploadedFile {
  id?: number;
  name: string;
  size: string;
  uploadedAt: string;
  status: 'success' | 'pending';
}

interface FontFile extends UploadedFile {
  id: number;
}

export default function UploadFilesPage() {
  const { token } = useAuth();
  const [files, setFiles] = useState<Record<string, UploadedFile | null>>({
    masterFile: null,
    companyLogo: null,
    youtubeCookies: null,
  });
  const [fontFiles, setFontFiles] = useState<FontFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  
  const [replaceDialogOpen, setReplaceDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [fileToReplace, setFileToReplace] = useState<string | null>(null);
  const [fontToDelete, setFontToDelete] = useState<number | null>(null);
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const fontInputRef = useRef<HTMLInputElement | null>(null);

  // Load files from backend on mount
  useEffect(() => {
    loadFiles();
  }, []);

  const loadFiles = async () => {
    try {
      setLoading(true);
      const response = await fetch(API_ENDPOINTS.uploadedFiles.getAll, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) throw new Error('Failed to load files');

      const data = await response.json();
      
      // Organize files by type
      const masterFile = data.find((f: any) => f.file_type === 'masterFile');
      const companyLogo = data.find((f: any) => f.file_type === 'companyLogo');
      const youtubeCookies = data.find((f: any) => f.file_type === 'youtubeCookies');
      const customFonts = data.filter((f: any) => f.file_type === 'customFont');

      setFiles({
        masterFile: masterFile ? {
          id: masterFile.id,
          name: masterFile.file_name,
          size: masterFile.file_size,
          uploadedAt: masterFile.uploaded_at.split('T')[0],
          status: 'success',
        } : null,
        companyLogo: companyLogo ? {
          id: companyLogo.id,
          name: companyLogo.file_name,
          size: companyLogo.file_size,
          uploadedAt: companyLogo.uploaded_at.split('T')[0],
          status: 'success',
        } : null,
        youtubeCookies: youtubeCookies ? {
          id: youtubeCookies.id,
          name: youtubeCookies.file_name,
          size: youtubeCookies.file_size,
          uploadedAt: youtubeCookies.uploaded_at.split('T')[0],
          status: 'success',
        } : null,
      });

      setFontFiles(customFonts.map((f: any) => ({
        id: f.id,
        name: f.file_name,
        size: f.file_size,
        uploadedAt: f.uploaded_at.split('T')[0],
        status: 'success',
      })));

    } catch (error) {
      console.error('Error loading files:', error);
      toast.error('Failed to load files', {
        description: 'Please refresh the page to try again.',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = async (fileType: string, event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    try {
      setUploading(fileType);

      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('file_type', fileType);

      const response = await fetch(API_ENDPOINTS.uploadedFiles.upload, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Upload failed');
      }

      const uploadedFile = await response.json();

      // Handle YouTube cookies special response (no database storage)
      if (fileType === 'youtubeCookies') {
        setFiles(prev => ({
          ...prev,
          youtubeCookies: {
            name: uploadedFile.file_name || 'youtube_cookies.txt',
            size: uploadedFile.file_size || 'Unknown',
            uploadedAt: new Date().toISOString().split('T')[0],
            status: 'success',
          },
        }));

        toast.success('YouTube cookies uploaded successfully', {
          description: uploadedFile.info || 'Cookies will be used for video downloads.',
        });
      } else {
        // Update state with new file (from database)
        setFiles(prev => ({
          ...prev,
          [fileType]: {
            id: uploadedFile.id,
            name: uploadedFile.file_name,
            size: uploadedFile.file_size,
            uploadedAt: uploadedFile.uploaded_at.split('T')[0],
            status: 'success',
          },
        }));

        toast.success(`${selectedFile.name} uploaded successfully`, {
          description: 'The file has been saved and is ready to use.',
        });
      }

    } catch (error: any) {
      console.error('Error uploading file:', error);
      toast.error('Upload failed', {
        description: error.message || 'Please try again.',
      });
    } finally {
      setUploading(null);
      // Reset the file input
      if (fileInputRefs.current[fileType]) {
        fileInputRefs.current[fileType]!.value = '';
      }
    }
  };

  const handleFontSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    // Validate file type
    if (!selectedFile.name.endsWith('.ttf')) {
      toast.error('Invalid file type', {
        description: 'Please upload a .ttf font file.',
      });
      return;
    }

    try {
      setUploading('customFont');

      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('file_type', 'customFont');

      const response = await fetch(API_ENDPOINTS.uploadedFiles.upload, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Upload failed');
      }

      const uploadedFont = await response.json();

      // Add to font files array
      const newFont: FontFile = {
        id: uploadedFont.id,
        name: uploadedFont.file_name,
        size: uploadedFont.file_size,
        uploadedAt: uploadedFont.uploaded_at.split('T')[0],
        status: 'success',
      };

      setFontFiles(prev => [...prev, newFont]);

      toast.success(`${selectedFile.name} uploaded successfully`, {
        description: 'The font has been added to your collection.',
      });

    } catch (error: any) {
      console.error('Error uploading font:', error);
      toast.error('Upload failed', {
        description: error.message || 'Please try again.',
      });
    } finally {
      setUploading(null);
      // Reset the file input
      if (fontInputRef.current) {
        fontInputRef.current.value = '';
      }
    }
  };

  const handleUploadClick = (fileType: string) => {
    fileInputRefs.current[fileType]?.click();
  };

  const handleFontUploadClick = () => {
    fontInputRef.current?.click();
  };

  const handleReplaceClick = (fileType: string) => {
    setFileToReplace(fileType);
    setReplaceDialogOpen(true);
  };

  const handleDeleteFontClick = (fontId: number) => {
    setFontToDelete(fontId);
    setDeleteDialogOpen(true);
  };

  const confirmReplace = async () => {
    if (fileToReplace) {
      const currentFile = files[fileToReplace];
      
      if (currentFile && currentFile.id) {
        try {
          // Delete from backend
          const response = await fetch(API_ENDPOINTS.uploadedFiles.delete(currentFile.id), {
            method: 'DELETE',
            headers: {
              'Authorization': `Bearer ${token}`,
            },
          });

          if (!response.ok) throw new Error('Failed to delete file');

          // Clear the file from state
          setFiles(prev => ({
            ...prev,
            [fileToReplace]: null,
          }));

          toast.info('File removed', {
            description: 'You can now upload a new file.',
          });

        } catch (error) {
          console.error('Error deleting file:', error);
          toast.error('Failed to remove file', {
            description: 'Please try again.',
          });
        }
      }

      setReplaceDialogOpen(false);
      setFileToReplace(null);

      // Trigger file upload dialog after a short delay
      setTimeout(() => {
        if (fileToReplace) {
          handleUploadClick(fileToReplace);
        }
      }, 300);
    }
  };

  const confirmDeleteFont = async () => {
    if (fontToDelete) {
      try {
        setDeleting(fontToDelete);

        const response = await fetch(API_ENDPOINTS.uploadedFiles.delete(fontToDelete), {
          method: 'DELETE',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) throw new Error('Failed to delete font');

        const fontToRemove = fontFiles.find(f => f.id === fontToDelete);
        
        setFontFiles(prev => prev.filter(f => f.id !== fontToDelete));

        toast.success('Font removed', {
          description: fontToRemove ? `${fontToRemove.name} has been removed.` : 'Font has been removed.',
        });

      } catch (error) {
        console.error('Error deleting font:', error);
        toast.error('Failed to remove font', {
          description: 'Please try again.',
        });
      } finally {
        setDeleting(null);
        setDeleteDialogOpen(false);
        setFontToDelete(null);
      }
    }
  };

  const handleDownload = async (fileType: string) => {
    const file = files[fileType];
    if (file && file.id) {
      try {
        const response = await fetch(API_ENDPOINTS.uploadedFiles.download(file.id), {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) throw new Error('Download failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = file.name;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        toast.success('Download started', {
          description: `Downloading ${file.name}...`,
        });
      } catch (error) {
        console.error('Error downloading file:', error);
        toast.error('Download failed', {
          description: 'Please try again.',
        });
      }
    }
  };

  const handleFontDownload = async (fontId: number) => {
    const font = fontFiles.find(f => f.id === fontId);
    if (font) {
      try {
        const response = await fetch(API_ENDPOINTS.uploadedFiles.download(fontId), {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) throw new Error('Download failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = font.name;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        toast.success('Download started', {
          description: `Downloading ${font.name}...`,
        });
      } catch (error) {
        console.error('Error downloading font:', error);
        toast.error('Download failed', {
          description: 'Please try again.',
        });
      }
    }
  };

  const fileConfigs = [
    {
      id: 'masterFile',
      title: 'API Scrip Master File',
      description: 'CSV file containing stock symbols, security IDs, and exchange information (NSE/BSE)',
      fileName: 'api-scrip-master.csv',
      accept: '.csv',
      icon: FileText,
      iconColor: 'text-green-500',
      iconBg: 'bg-green-500/20',
    },
    {
      id: 'companyLogo',
      title: 'Company Logo',
      description: 'PNG or JPG logo file for PDF letterhead (recommended: 400x400px, transparent background)',
      fileName: 'company-logo.png',
      accept: '.png,.jpg,.jpeg',
      icon: ImageIcon,
      iconColor: 'text-blue-500',
      iconBg: 'bg-blue-500/20',
    },
    {
      id: 'youtubeCookies',
      title: 'YouTube Cookies File (Optional)',
      description: 'Upload YouTube cookies.txt file to bypass bot detection. Required when YouTube blocks video downloads.',
      fileName: 'youtube_cookies.txt',
      accept: '.txt',
      icon: Cookie,
      iconColor: 'text-orange-500',
      iconBg: 'bg-orange-500/20',
      showChromeLink: true,
    },
  ];

  if (loading) {
    return (
      <div className="p-4 sm:p-6 flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin mx-auto mb-3" />
          <p className="text-muted-foreground">Loading files...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-xl sm:text-2xl text-foreground mb-1">Upload Required Files</h1>
        <p className="text-sm sm:text-base text-muted-foreground">Manage master data files and assets for the rationale generation pipeline</p>
      </div>

      {/* Info Banner */}
      <Card className="bg-blue-500/10 border-blue-500/30 p-4">
        <div className="flex items-start gap-3">
          <div className="p-2 bg-blue-500/20 rounded-lg flex-shrink-0">
            <Upload className="w-5 h-5 text-blue-600 dark:text-blue-400" />
          </div>
          <div>
            <h3 className="text-blue-700 dark:text-blue-400 mb-1">Important Notes</h3>
            <ul className="text-sm text-blue-700/80 dark:text-blue-300/80 space-y-1 list-disc list-inside">
              <li>All uploaded files are stored securely on the server</li>
              <li>Files are automatically validated before being saved</li>
              <li>Master file changes will affect all new job executions</li>
            </ul>
          </div>
        </div>
      </Card>

      {/* Upload Cards */}
      <div className="space-y-4 sm:space-y-6">
        {fileConfigs.map((config) => {
          const Icon = config.icon;
          const currentFile = files[config.id];
          const isUploading = uploading === config.id;

          return (
            <Card key={config.id} className="bg-card border-border shadow-sm p-4 sm:p-6" data-tour={`upload-${config.id}`}>
              <div className="flex items-start gap-3 sm:gap-4">
                <div className={`p-2.5 sm:p-3 ${config.iconBg} rounded-xl flex-shrink-0`}>
                  <Icon className={`w-5 h-5 sm:w-6 sm:h-6 ${config.iconColor}`} />
                </div>

                <div className="flex-1 min-w-0">
                  <h3 className="text-base sm:text-lg text-foreground mb-1">{config.title}</h3>
                  <p className="text-xs sm:text-sm text-muted-foreground mb-2">{config.description}</p>
                  
                  {/* Download Latest Master File Link - Only for masterFile */}
                  {config.id === 'masterFile' && (
                    <div className="mb-3 sm:mb-4">
                      <a
                        href="https://images.dhan.co/api-data/api-scrip-master.csv"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs sm:text-sm text-green-600 dark:text-green-400 hover:text-green-700 dark:hover:text-green-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Download Latest Master File
                      </a>
                    </div>
                  )}
                  
                  {/* Chrome Extension Link - Only for youtubeCookies */}
                  {config.showChromeLink && (
                    <div className="mb-3 sm:mb-4">
                      <a
                        href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs sm:text-sm text-orange-600 dark:text-orange-400 hover:text-orange-700 dark:hover:text-orange-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Install Get cookies on your chrome
                      </a>
                    </div>
                  )}

                  {currentFile ? (
                    <div className="bg-muted/50 border border-border rounded-lg p-3 sm:p-4 mb-3 sm:mb-4">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="flex items-start gap-2.5 sm:gap-3 flex-1 min-w-0">
                          <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5 text-green-500 shrink-0 mt-0.5 sm:mt-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm sm:text-base text-foreground break-words">{currentFile.name}</p>
                            <p className="text-xs text-muted-foreground">
                              {currentFile.size} • Uploaded {formatDateIST(currentFile.uploadedAt)}
                            </p>
                          </div>
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleReplaceClick(config.id)}
                          className="border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600 w-full sm:w-auto shrink-0"
                        >
                          Replace
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="border-2 border-dashed border-border rounded-lg p-6 sm:p-8 text-center mb-3 sm:mb-4 bg-muted/50">
                      <Upload className="w-6 h-6 sm:w-8 sm:h-8 text-muted-foreground mx-auto mb-2 sm:mb-3" />
                      <p className="text-sm sm:text-base text-foreground mb-1">No file uploaded</p>
                      <p className="text-xs text-muted-foreground">Expected: {config.fileName}</p>
                    </div>
                  )}

                  <div className="flex flex-col sm:flex-row gap-2.5 sm:gap-3">
                    {/* Hidden file input */}
                    <input
                      type="file"
                      ref={(el) => (fileInputRefs.current[config.id] = el)}
                      onChange={(e) => handleFileSelect(config.id, e)}
                      accept={config.accept}
                      className="hidden"
                      disabled={isUploading}
                    />
                    
                    <Button
                      onClick={() => handleUploadClick(config.id)}
                      className="gradient-primary h-11 w-full sm:w-auto"
                      disabled={isUploading}
                    >
                      {isUploading ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Uploading...
                        </>
                      ) : (
                        <>
                          <Upload className="w-4 h-4 mr-2" />
                          {currentFile ? 'Upload New File' : 'Upload File'}
                        </>
                      )}
                    </Button>
                    {currentFile && (
                      <Button
                        variant="outline"
                        onClick={() => handleDownload(config.id)}
                        className="border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600 h-11 w-full sm:w-auto"
                      >
                        <Download className="w-4 h-4 mr-2" />
                        Download Current
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          );
        })}

        {/* Custom Fonts Section */}
        <Card className="bg-card border-border shadow-sm p-4 sm:p-6">
          <div className="flex items-start gap-3 sm:gap-4">
            <div className="p-2.5 sm:p-3 bg-purple-500/20 rounded-xl flex-shrink-0">
              <FileText className="w-5 h-5 sm:w-6 sm:h-6 text-purple-500" />
            </div>

            <div className="flex-1 min-w-0">
              <h3 className="text-base sm:text-lg text-foreground mb-1">Custom Fonts (Optional)</h3>
              <p className="text-xs sm:text-sm text-muted-foreground mb-3 sm:mb-4">
                Upload custom .ttf fonts for PDF generation. You can add multiple font files.
              </p>

              {/* Font Files List */}
              {fontFiles.length > 0 ? (
                <div className="space-y-2 mb-3 sm:mb-4">
                  {fontFiles.map((font) => (
                    <div
                      key={font.id}
                      className="bg-muted/50 border border-border rounded-lg p-2.5 sm:p-3"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                        <div className="flex items-start gap-2.5 sm:gap-3 flex-1 min-w-0">
                          <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5 sm:mt-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-foreground text-sm break-words">{font.name}</p>
                            <p className="text-xs text-muted-foreground">
                              {font.size} • Uploaded {formatDateIST(font.uploadedAt)}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 sm:ml-2 self-end sm:self-center">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleFontDownload(font.id)}
                            className="h-9 w-9 sm:h-8 sm:w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-accent"
                            title="Download"
                          >
                            <Download className="w-4 h-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDeleteFontClick(font.id)}
                            className="h-9 w-9 sm:h-8 sm:w-8 p-0 text-red-500 hover:text-red-600 hover:bg-red-500/20"
                            title="Remove"
                            disabled={deleting === font.id}
                          >
                            {deleting === font.id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <X className="w-4 h-4" />
                            )}
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="border-2 border-dashed border-border rounded-lg p-6 sm:p-8 text-center mb-3 sm:mb-4 bg-muted/50">
                  <FileText className="w-6 h-6 sm:w-8 sm:h-8 text-muted-foreground mx-auto mb-2 sm:mb-3" />
                  <p className="text-sm sm:text-base text-foreground mb-1">No fonts uploaded</p>
                  <p className="text-xs text-muted-foreground">Upload .ttf font files for PDF generation</p>
                </div>
              )}

              {/* Hidden font file input */}
              <input
                type="file"
                ref={fontInputRef}
                onChange={handleFontSelect}
                accept=".ttf"
                className="hidden"
                disabled={uploading === 'customFont'}
              />

              <Button
                onClick={handleFontUploadClick}
                className="bg-purple-600 hover:bg-purple-700 text-white h-11 w-full sm:w-auto"
                disabled={uploading === 'customFont'}
              >
                {uploading === 'customFont' ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4 mr-2" />
                    Add Font File
                  </>
                )}
              </Button>
            </div>
          </div>
        </Card>
      </div>

      {/* Replace Confirmation Dialog */}
      <AlertDialog open={replaceDialogOpen} onOpenChange={setReplaceDialogOpen}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Replace Existing File?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              This will remove the current file and allow you to upload a new one. 
              This action cannot be undone and may affect ongoing or future operations.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-muted text-foreground hover:bg-accent border-border">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmReplace}
              className="gradient-primary h-10"
            >
              Replace File
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Font Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Remove Font File?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              This will permanently remove this font file from your collection.
              PDFs using this font may not render correctly.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-muted text-foreground hover:bg-accent border-border">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteFont}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              Remove Font
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
