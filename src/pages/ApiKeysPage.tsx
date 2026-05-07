import { useState, useEffect } from 'react';
import { Key, Upload, Check, X, Loader2, Eye, EyeOff } from 'lucide-react';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { toast } from 'sonner';

export default function ApiKeysPage() {
  const [savingStates, setSavingStates] = useState<Record<string, boolean>>({});
  const [keys, setKeys] = useState<Record<string, string>>({
    openai: '',
    gemini: '',
    assemblyai: '',
    dhan: '',
    youtubedata: '',
    rapidapi_video_transcript: '',
  });
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
  const [configuredProviders, setConfiguredProviders] = useState<Record<string, boolean>>({
    openai: false,
    gemini: false,
    assemblyai: false,
    google_cloud: false,
    dhan: false,
    youtubedata: false,
    rapidapi_video_transcript: false,
  });

  useEffect(() => {
    loadApiKeys();
  }, []);

  const loadApiKeys = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(API_ENDPOINTS.apiKeys.get, {
        headers: getAuthHeaders(token || ''),
      });

      if (response.ok) {
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          console.warn('Non-JSON response received during HMR, skipping API key load');
          return;
        }
        
        const data = await response.json();
        
        // Data is now an array of { id, provider, value, created_at, updated_at }
        const keyMap: Record<string, string> = {};
        const configMap: Record<string, boolean> = {
          openai: false,
          gemini: false,
          assemblyai: false,
          google_cloud: false,
          dhan: false,
          youtubedata: false,
          rapidapi_video_transcript: false,
        };
        
        data.forEach((item: any) => {
          if (item.provider === 'google_cloud') {
            configMap.google_cloud = !!item.value;
            if (item.value) {
              const mockFile = new File([''], 'google-cloud.json', { type: 'application/json' });
              setUploadedFile(mockFile);
            }
          } else {
            keyMap[item.provider] = item.value || '';
            configMap[item.provider] = !!item.value;
          }
        });
        
        setKeys(keyMap);
        setConfiguredProviders(configMap);
      } else {
        // Backend returned an error response
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          const error = await response.json();
          toast.error(error.error || 'Failed to load API keys');
        } else {
          // Non-JSON error from backend (500 HTML page, etc.)
          toast.error('Failed to load API keys', {
            description: 'Server error occurred',
          });
        }
      }
    } catch (error) {
      console.error('Error loading API keys:', error);
      // Show toast for any fetch/network error
      toast.error('Failed to load API keys', {
        description: 'Please check your connection and try again',
      });
    }
  };

  const handleSaveKey = async (providerId: string, providerName: string) => {
    if (!keys[providerId] || keys[providerId].trim() === '') {
      toast.error('API key required', {
        description: 'Please enter an API key before saving.',
      });
      return;
    }

    setSavingStates(prev => ({ ...prev, [providerId]: true }));

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(API_ENDPOINTS.apiKeys.update, {
        method: 'PUT',
        headers: getAuthHeaders(token || ''),
        body: JSON.stringify({
          provider: providerId,
          value: keys[providerId],
        }),
      });

      if (response.ok) {
        setConfiguredProviders(prev => ({ ...prev, [providerId]: true }));
        toast.success(`${providerName} API key saved`, {
          description: 'The key has been stored securely.',
        });
      } else {
        const error = await response.json();
        toast.error(error.error || 'Failed to save API key');
      }
    } catch (error) {
      console.error('Error saving API key:', error);
      toast.error('Error saving API key');
    } finally {
      setSavingStates(prev => ({ ...prev, [providerId]: false }));
    }
  };

  const handleFileSelect = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.onchange = (e: Event) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        // Check if it's a JSON file
        if (!file.name.endsWith('.json')) {
          toast.error('Invalid file type', {
            description: 'Please upload a JSON file.',
          });
          return;
        }

        // Check file size (max 1MB)
        if (file.size > 1024 * 1024) {
          toast.error('File too large', {
            description: 'Please upload a file smaller than 1MB.',
          });
          return;
        }

        setUploadedFile(file);
        toast.success('File selected', {
          description: file.name,
        });
      }
    };
    input.click();
  };

  const handleFileUpload = async (providerId: string, providerName: string) => {
    if (!uploadedFile) {
      toast.error('No file selected', {
        description: 'Please select a JSON file first.',
      });
      return;
    }

    setSavingStates(prev => ({ ...prev, [providerId]: true }));

    try {
      const token = localStorage.getItem('token');
      const formData = new FormData();
      formData.append('file', uploadedFile);
      
      const response = await fetch(`${API_ENDPOINTS.apiKeys.base}/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (response.ok) {
        setConfiguredProviders(prev => ({ ...prev, [providerId]: true }));
        toast.success(`${providerName} JSON file uploaded`, {
          description: `${uploadedFile.name} has been saved securely.`,
        });
      } else {
        const error = await response.json();
        toast.error(error.error || 'Failed to upload file');
      }
    } catch (error) {
      console.error('Error uploading file:', error);
      toast.error('Error uploading file');
    } finally {
      setSavingStates(prev => ({ ...prev, [providerId]: false }));
    }
  };

  const apiProviders = [
    {
      id: 'youtubedata',
      name: 'YouTube Data API v3',
      description: 'Required for fetching YouTube video metadata (title, duration, channel)',
      type: 'key',
      placeholder: 'AIzaSy...',
    },
    {
      id: 'rapidapi_video_transcript',
      name: 'RapidAPI',
      description: '',
      type: 'key',
      placeholder: 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx...',
    },
    {
      id: 'openai',
      name: 'OpenAI',
      description: '',
      type: 'key',
      placeholder: 'sk-...',
    },
    {
      id: 'gemini',
      name: 'Gemini',
      description: 'Google AI for Step 8 stock extraction',
      type: 'key',
      placeholder: 'AIzaSy...',
    },
    {
      id: 'assemblyai',
      name: 'AssemblyAI',
      description: '',
      type: 'key',
      placeholder: 'xxxxxxxxxxxxxxxxxxxx',
    },
    {
      id: 'google_cloud',
      name: 'Google Cloud',
      description: '',
      type: 'file',
      placeholder: 'Upload service account JSON',
    },
    {
      id: 'dhan',
      name: 'Dhan API',
      description: '',
      type: 'key',
      placeholder: 'eyJhbGciOiJIUzI1NiIsInR5cCI6...',
    },
  ];

  const getProviderStatus = (providerId: string) => {
    return configuredProviders[providerId] || false;
  };

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-xl sm:text-2xl text-foreground mb-1">API Keys</h1>
        <p className="text-sm sm:text-base text-muted-foreground">Configure external service API keys for the rationale generation pipeline</p>
      </div>

      {/* Warning Banner */}
      <Card className="bg-yellow-500/10 border-yellow-500/30 p-4">
        <div className="flex items-start gap-3">
          <div className="p-2 bg-yellow-500/20 rounded-lg flex-shrink-0">
            <Key className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
          </div>
          <div>
            <h3 className="text-yellow-700 dark:text-yellow-400 mb-1">Security Notice</h3>
            <p className="text-sm text-yellow-700/80 dark:text-yellow-300/80">
              All API keys are stored securely in the database and only accessible to administrators. 
              Keys are used during job execution to connect to external services. Never share your API keys with unauthorized users.
            </p>
          </div>
        </div>
      </Card>

      {/* API Keys Configuration */}
      <div className="grid grid-cols-1 gap-6">
        {apiProviders.map((provider) => {
          const isConfigured = getProviderStatus(provider.id);
          const isSaving = savingStates[provider.id] || false;
          
          return (
            <Card key={provider.id} className="premium-card" data-tour={`api-${provider.id}`}>
              <div className="p-4 sm:p-6">
              <div className="flex flex-col sm:flex-row items-start justify-between mb-4 gap-3">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <div className="p-2.5 sm:p-3 icon-bg-primary rounded-xl shrink-0">
                    <Key className="w-5 h-5 sm:w-6 sm:h-6 text-blue-500" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-base sm:text-lg text-foreground">{provider.name}</h3>
                    {provider.description && <p className="text-xs sm:text-sm text-muted-foreground mb-1.5">{provider.description}</p>}
                    {provider.id === 'youtubedata' && (
                      <a
                        href="https://developers.google.com/youtube/v3/getting-started"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        Setup Youtube Data API v3 Now
                      </a>
                    )}
                    {provider.id === 'openai' && (
                      <a
                        href="https://platform.openai.com/api-keys"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        Setup your OpenAI API Key here. Make sure you have setup your billing account properly
                      </a>
                    )}
                    {provider.id === 'assemblyai' && (
                      <a
                        href="https://www.assemblyai.com/dashboard/api-keys"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        Setup your AssemblyAI API Key here.
                      </a>
                    )}
                    {provider.id === 'rapidapi_video_transcript' && (
                      <a
                        href="https://rapidapi.com/herosAPI/api/video-transcript-scraper"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        Get your RapidAPI Video Transcript key here. Subscribe to access the API.
                      </a>
                    )}
                    {provider.id === 'google_cloud' && (
                      <a
                        href="https://console.cloud.google.com/apis/credentials"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        Setup your Google Cloud Service Account here
                      </a>
                    )}
                    {provider.id === 'dhan' && (
                      <a
                        href="https://web.dhan.co/index/profile"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors underline-offset-4 hover:underline font-medium"
                      >
                        setup your dhan Data API here
                      </a>
                    )}
                  </div>
                </div>
                <Badge className={
                  isConfigured
                    ? 'bg-green-500/20 text-green-600 dark:text-green-500 border-green-500/30 shrink-0'
                    : 'bg-muted text-muted-foreground border-border shrink-0'
                }>
                  {isConfigured ? (
                    <><Check className="w-3 h-3 mr-1" /> Configured</>
                  ) : (
                    <><X className="w-3 h-3 mr-1" /> Not Configured</>
                  )}
                </Badge>
              </div>

              {provider.type === 'key' ? (
                <div className="space-y-3">
                  <Label htmlFor={provider.id} className="text-foreground text-sm">
                    API Key
                  </Label>
                  <div className="relative">
                    <Input
                      id={provider.id}
                      type={visibleKeys[provider.id] ? 'text' : 'password'}
                      placeholder={provider.placeholder}
                      value={keys[provider.id] || ''}
                      onChange={(e) => setKeys(prev => ({ ...prev, [provider.id]: e.target.value }))}
                      className="pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setVisibleKeys(prev => ({ ...prev, [provider.id]: !prev[provider.id] }))}
                      className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground hover:text-foreground transition-colors"
                      aria-label={visibleKeys[provider.id] ? 'Hide API key' : 'Show API key'}
                      title={visibleKeys[provider.id] ? 'Hide API key' : 'Show API key'}
                    >
                      {visibleKeys[provider.id] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <div className="flex items-center justify-between">
                    <Button
                      onClick={() => handleSaveKey(provider.id, provider.name)}
                      disabled={isSaving}
                      className="bg-gradient-to-r from-blue-500 to-purple-600 text-white hover:from-blue-600 hover:to-purple-700"
                    >
                      {isSaving ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        'Save Key'
                      )}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    The key will be stored securely and only accessible to administrators
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  <Label htmlFor={`${provider.id}-file`} className="text-foreground text-sm">
                    Service Account JSON
                  </Label>
                  <div className="flex items-center gap-3">
                    <Button
                      variant="outline"
                      onClick={handleFileSelect}
                      className="flex-1"
                    >
                      <Upload className="w-4 h-4 mr-2" />
                      {uploadedFile ? uploadedFile.name : 'Choose File'}
                    </Button>
                    {uploadedFile && (
                      <Button
                        onClick={() => handleFileUpload(provider.id, provider.name)}
                        disabled={isSaving}
                        className="bg-gradient-to-r from-blue-500 to-purple-600 text-white hover:from-blue-600 hover:to-purple-700"
                      >
                        {isSaving ? (
                          <>
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            Uploading...
                          </>
                        ) : (
                          'Upload'
                        )}
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Upload your Google Cloud service account JSON file. The file will be stored securely on the server.
                  </p>
                </div>
              )}
            </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
