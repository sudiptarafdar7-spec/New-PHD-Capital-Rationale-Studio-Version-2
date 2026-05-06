import React, { useState, useRef, useEffect } from 'react';
import { formatDateIST } from '@/lib/datetime';
import { Play, Plus, Trash2, Upload, Edit, ExternalLink, Loader2 } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
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
import { toast } from 'sonner@2.0.3';
import { useAuth } from '../lib/auth-context';
import { API_ENDPOINTS } from '../lib/api-config';

interface Channel {
  id: string;
  name: string;
  logoPath: string;
  channelLink: string;
  addedAt: string;
  platform: string;
}

export default function ChannelLogosPage() {
  const { token } = useAuth();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isAddDialogLoading, setIsAddDialogLoading] = useState(false);
  const [isEditDialogLoading, setIsEditDialogLoading] = useState(false);
  const [isDeleteDialogLoading, setIsDeleteDialogLoading] = useState(false);
  
  const [platform, setPlatform] = useState('youtube');
  const [channelName, setChannelName] = useState('');
  const [channelLink, setChannelLink] = useState('');
  const [channelLogo, setChannelLogo] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string>('');
  
  const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
  const [channelToDelete, setChannelToDelete] = useState<Channel | null>(null);
  
  const addLogoInputRef = useRef<HTMLInputElement | null>(null);
  const editLogoInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    loadChannels();
  }, []);

  const loadChannels = async () => {
    try {
      setIsLoading(true);
      const response = await fetch(API_ENDPOINTS.channels.getAll, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const data = await response.json();
        setChannels(data);
      } else {
        toast.error('Failed to load channels');
      }
    } catch (error) {
      console.error('Error loading channels:', error);
      toast.error('Failed to load channels');
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogoSelect = (event: React.ChangeEvent<HTMLInputElement>, isEdit: boolean = false) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      toast.error('Invalid file type', {
        description: 'Please upload an image file (PNG or JPG).',
      });
      return;
    }

    // Create preview URL
    const previewUrl = URL.createObjectURL(file);
    setLogoPreview(previewUrl);
    setChannelLogo(file);
  };

  const handleAddChannel = async () => {
    try {
      setIsAddDialogLoading(true);

      const formData = new FormData();
      formData.append('platform', platform);
      formData.append('channelName', channelName);
      formData.append('channelUrl', channelLink || '');
      if (channelLogo) {
        formData.append('logo', channelLogo);
      }

      const response = await fetch(API_ENDPOINTS.channels.create, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (response.ok) {
        const newChannel = await response.json();
        setChannels([newChannel, ...channels]);
        
        // Reset form
        setChannelName('');
        setChannelLink('');
        setChannelLogo(null);
        setLogoPreview('');
        setIsAddDialogOpen(false);

        toast.success('Channel added successfully', {
          description: `${channelName} has been added to the system.`,
        });
      } else {
        const error = await response.json();
        toast.error('Failed to add channel', {
          description: error.error || 'Please try again',
        });
      }
    } catch (error) {
      console.error('Error adding channel:', error);
      toast.error('Failed to add channel', {
        description: 'Please check your connection and try again',
      });
    } finally {
      setIsAddDialogLoading(false);
    }
  };

  const handleEditClick = (channel: Channel) => {
    setEditingChannel(channel);
    setPlatform(channel.platform || 'youtube');
    setChannelName(channel.name);
    setChannelLink(channel.channelLink);
    setLogoPreview(channel.logoPath);
    setIsEditDialogOpen(true);
  };

  const handleUpdateChannel = async () => {
    if (!editingChannel) return;

    try {
      setIsEditDialogLoading(true);

      const formData = new FormData();
      formData.append('platform', platform);
      formData.append('channelName', channelName);
      formData.append('channelUrl', channelLink || '');
      if (channelLogo) {
        formData.append('logo', channelLogo);
      }

      const response = await fetch(API_ENDPOINTS.channels.update(Number(editingChannel.id)), {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });

      if (response.ok) {
        const updatedChannel = await response.json();
        setChannels(channels.map(ch => ch.id === editingChannel.id ? updatedChannel : ch));
        
        // Reset form
        setChannelName('');
        setChannelLink('');
        setChannelLogo(null);
        setLogoPreview('');
        setEditingChannel(null);
        setIsEditDialogOpen(false);

        toast.success('Channel updated successfully', {
          description: `${channelName} has been updated.`,
        });
      } else {
        const error = await response.json();
        toast.error('Failed to update channel', {
          description: error.error || 'Please try again',
        });
      }
    } catch (error) {
      console.error('Error updating channel:', error);
      toast.error('Failed to update channel', {
        description: 'Please check your connection and try again',
      });
    } finally {
      setIsEditDialogLoading(false);
    }
  };

  const handleDeleteClick = (channel: Channel) => {
    setChannelToDelete(channel);
    setIsDeleteDialogOpen(true);
  };

  const confirmDelete = async () => {
    if (!channelToDelete) return;

    try {
      setIsDeleteDialogLoading(true);

      const response = await fetch(API_ENDPOINTS.channels.delete(Number(channelToDelete.id)), {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (response.ok) {
        setChannels(channels.filter(ch => ch.id !== channelToDelete.id));
        
        toast.success('Channel deleted', {
          description: `${channelToDelete.name} has been removed.`,
        });

        setChannelToDelete(null);
        setIsDeleteDialogOpen(false);
      } else {
        const error = await response.json();
        toast.error('Failed to delete channel', {
          description: error.error || 'Please try again',
        });
      }
    } catch (error) {
      console.error('Error deleting channel:', error);
      toast.error('Failed to delete channel', {
        description: 'Please check your connection and try again',
      });
    } finally {
      setIsDeleteDialogLoading(false);
    }
  };

  const handleLogoClick = (channelLink: string) => {
    window.open(channelLink, '_blank', 'noopener,noreferrer');
  };

  const resetAddDialog = () => {
    setPlatform('youtube');
    setChannelName('');
    setChannelLink('');
    setChannelLogo(null);
    setLogoPreview('');
    setIsAddDialogOpen(false);
  };

  const resetEditDialog = () => {
    setPlatform('youtube');
    setChannelName('');
    setChannelLink('');
    setChannelLogo(null);
    setLogoPreview('');
    setEditingChannel(null);
    setIsEditDialogOpen(false);
  };

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
        <div className="flex-1">
          <h1 className="text-xl sm:text-2xl text-foreground mb-1">Manage Platform</h1>
          <p className="text-sm sm:text-base text-muted-foreground">Add and manage YouTube channels/Facebook Pages/Instagram Accounts/Telegram Channels Etc</p>
        </div>

        <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
          <DialogTrigger asChild>
            <Button className="gradient-primary glow-primary h-11 w-full sm:w-auto shrink-0" data-tour="channel-new">
              <Plus className="w-4 h-4 mr-2" />
              Add Platform
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-card border-border text-foreground">
            <DialogHeader>
              <DialogTitle>Add New Platform</DialogTitle>
              <DialogDescription className="text-muted-foreground">
                Add a new platform with logo and link
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 pt-4">
              <div className="space-y-2">
                <Label htmlFor="add-platform" className="text-foreground">
                  Platform *
                </Label>
                <select
                  id="add-platform"
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-input rounded-md text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="youtube">YouTube</option>
                  <option value="facebook">Facebook</option>
                  <option value="instagram">Instagram</option>
                  <option value="telegram">Telegram</option>
                  <option value="whatsapp">WhatsApp</option>
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="add-channel-name" className="text-foreground">
                  Channel Name/Username
                </Label>
                <Input
                  id="add-channel-name"
                  placeholder="e.g., Market Expert Channel"
                  value={channelName}
                  onChange={(e) => setChannelName(e.target.value)}
                  className="bg-background border-input text-foreground"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="add-channel-link" className="text-foreground">
                  Channel Link
                </Label>
                <Input
                  id="add-channel-link"
                  placeholder="https://www.youtube.com/@channelname (optional)"
                  value={channelLink}
                  onChange={(e) => setChannelLink(e.target.value)}
                  className="bg-background border-input text-foreground"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-foreground">Channel Logo/Profile Image</Label>
                <input
                  type="file"
                  ref={addLogoInputRef}
                  onChange={(e) => handleLogoSelect(e, false)}
                  accept="image/*"
                  className="hidden"
                />
                
                {logoPreview ? (
                  <div className="border border-border rounded-lg p-4 bg-muted/50">
                    <div className="flex items-center gap-4">
                      <img
                        src={logoPreview}
                        alt="Logo preview"
                        className="w-16 h-16 object-cover rounded-lg"
                      />
                      <div className="flex-1">
                        <p className="text-sm text-foreground">Logo selected</p>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setLogoPreview('');
                            setChannelLogo(null);
                          }}
                          className="text-red-500 hover:text-red-600 h-8 px-2"
                        >
                          Remove
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div
                    onClick={() => addLogoInputRef.current?.click()}
                    className="border-2 border-dashed border-border rounded-lg p-6 text-center bg-muted/50 cursor-pointer hover:bg-accent transition-colors"
                  >
                    <Upload className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                    <p className="text-sm text-foreground mb-1">Click to upload or drag and drop</p>
                    <p className="text-xs text-muted-foreground">PNG or JPG (recommended: 200x200px)</p>
                  </div>
                )}
              </div>

              <div className="flex flex-col sm:flex-row sm:justify-end gap-2.5 sm:gap-3 pt-4">
                <Button
                  variant="outline"
                  onClick={resetAddDialog}
                  className="w-full sm:w-auto h-11 border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleAddChannel}
                  disabled={isAddDialogLoading}
                  className="gradient-primary h-11 w-full sm:w-auto"
                >
                  {isAddDialogLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Adding...
                    </>
                  ) : (
                    'Add Platform'
                  )}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Info Banner */}
      <Card className="bg-blue-500/10 border-blue-500/30 p-4">
        <div className="flex items-start gap-3">
          <div className="p-2 bg-blue-500/20 rounded-lg flex-shrink-0">
            <Play className="w-5 h-5 text-blue-600 dark:text-blue-400" />
          </div>
          <div>
            <h3 className="text-blue-700 dark:text-blue-400 mb-1">Platform Management Guidelines</h3>
            <ul className="text-sm text-blue-700/80 dark:text-blue-300/80 space-y-1 list-disc list-inside">
              <li>Click on platform logo to open the platform page in new tab</li>
              <li>Logos are automatically matched to content during analysis</li>
              <li>Recommended logo size: 200x200px with transparent background</li>
            </ul>
          </div>
        </div>
      </Card>

      {/* Channels Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
        {channels.map((channel) => (
          <Card key={channel.id} className="bg-card border-border shadow-sm p-5 sm:p-6">
            <div className="text-center">
              <div
                onClick={() => handleLogoClick(channel.channelLink)}
                className="inline-flex items-center justify-center w-20 h-20 bg-muted rounded-full mb-3 sm:mb-4 overflow-hidden cursor-pointer hover:ring-2 hover:ring-blue-500/50 transition-all group relative"
                title="Click to open channel"
              >
                <img
                  src={channel.logoPath}
                  alt={channel.name}
                  className="w-full h-full object-cover"
                />
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                  <ExternalLink className="w-6 h-6 text-white" />
                </div>
              </div>

              <h3 className="text-base sm:text-lg text-foreground mb-1">{channel.name}</h3>
              <a
                href={channel.channelLink}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-500 hover:text-blue-600 hover:underline inline-flex items-center gap-1 mb-2 sm:mb-3"
              >
                View
                <ExternalLink className="w-3 h-3" />
              </a>
              <p className="text-xs sm:text-sm text-muted-foreground mb-3 sm:mb-4">
                Added {formatDateIST(channel.addedAt)}
              </p>

              <div className="flex flex-col gap-2.5 sm:gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleEditClick(channel)}
                  className="w-full h-10 border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
                >
                  <Edit className="w-4 h-4 mr-2" />
                  Update
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleDeleteClick(channel)}
                  className="w-full h-10 border-red-500/30 text-red-500 hover:bg-red-500/10"
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete
                </Button>
              </div>
            </div>
          </Card>
        ))}

        {/* Add New Card */}
        <Card className="bg-card border-border border-dashed shadow-sm p-5 sm:p-6 flex items-center justify-center min-h-[280px] sm:min-h-[320px]">
          <button
            onClick={() => setIsAddDialogOpen(true)}
            className="text-center hover:bg-accent rounded-lg p-4 transition-colors"
          >
            <div className="inline-flex items-center justify-center w-14 h-14 sm:w-16 sm:h-16 bg-blue-500/20 rounded-full mb-2 sm:mb-3">
              <Plus className="w-7 h-7 sm:w-8 sm:h-8 text-blue-500" />
            </div>
            <p className="text-sm sm:text-base text-foreground mb-1">Add New Platform</p>
            <p className="text-xs sm:text-sm text-muted-foreground">Upload platform details</p>
          </button>
        </Card>
      </div>

      {/* Edit Platform Dialog */}
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent className="bg-card border-border text-foreground">
          <DialogHeader>
            <DialogTitle>Update Platform</DialogTitle>
            <DialogDescription className="text-muted-foreground">
              Update platform name, logo, and link
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="edit-platform" className="text-foreground">
                Platform *
              </Label>
              <select
                id="edit-platform"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="youtube">YouTube</option>
                <option value="facebook">Facebook</option>
                <option value="instagram">Instagram</option>
                <option value="telegram">Telegram</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-channel-name" className="text-foreground">
                Channel Name/Username
              </Label>
              <Input
                id="edit-channel-name"
                placeholder="e.g., Market Expert Channel"
                value={channelName}
                onChange={(e) => setChannelName(e.target.value)}
                className="bg-background border-input text-foreground"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-channel-link" className="text-foreground">
                Channel Link
              </Label>
              <Input
                id="edit-channel-link"
                placeholder="https://www.youtube.com/@channelname (optional)"
                value={channelLink}
                onChange={(e) => setChannelLink(e.target.value)}
                className="bg-background border-input text-foreground"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-foreground">Channel Logo/Profile Image</Label>
              <input
                type="file"
                ref={editLogoInputRef}
                onChange={(e) => handleLogoSelect(e, true)}
                accept="image/*"
                className="hidden"
              />
              
              {logoPreview ? (
                <div className="border border-border rounded-lg p-4 bg-muted/50">
                  <div className="flex items-center gap-4">
                    <img
                      src={logoPreview}
                      alt="Logo preview"
                      className="w-16 h-16 object-cover rounded-lg"
                    />
                    <div className="flex-1">
                      <p className="text-sm text-foreground">Current logo</p>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => editLogoInputRef.current?.click()}
                        className="text-blue-500 hover:text-blue-600 h-8 px-2"
                      >
                        Change Logo
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <div
                  onClick={() => editLogoInputRef.current?.click()}
                  className="border-2 border-dashed border-border rounded-lg p-6 text-center bg-muted/50 cursor-pointer hover:bg-accent transition-colors"
                >
                  <Upload className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-foreground mb-1">Click to upload new logo</p>
                  <p className="text-xs text-muted-foreground">PNG or JPG (recommended: 200x200px)</p>
                </div>
              )}
            </div>

            <div className="flex flex-col sm:flex-row sm:justify-end gap-2.5 sm:gap-3 pt-4">
              <Button
                variant="outline"
                onClick={resetEditDialog}
                className="w-full sm:w-auto h-11 border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
              >
                Cancel
              </Button>
              <Button
                onClick={handleUpdateChannel}
                disabled={isEditDialogLoading}
                className="gradient-primary h-11 w-full sm:w-auto"
              >
                {isEditDialogLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Updating...
                  </>
                ) : (
                  'Update Channel'
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-foreground">Delete Channel?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              Are you sure you want to delete "{channelToDelete?.name}"? This action cannot be undone
              and may affect video analysis for this channel.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-muted text-foreground hover:bg-accent border-border">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              disabled={isDeleteDialogLoading}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              {isDeleteDialogLoading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                'Delete Channel'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
