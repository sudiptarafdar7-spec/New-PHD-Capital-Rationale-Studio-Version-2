import React, { useState, useEffect } from 'react';
import { formatDateIST } from '@/lib/datetime';
import { User, Mail, Phone, Shield, Camera, Save, Lock, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../lib/auth-context';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Avatar, AvatarFallback, AvatarImage } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { toast } from 'sonner@2.0.3';

export default function ProfilePage() {
  const { user, token, setUser } = useAuth();
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [mobile, setMobile] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  
  // Password dialog state
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSavingPassword, setIsSavingPassword] = useState(false);

  // Load user data when component mounts or user changes
  useEffect(() => {
    if (user) {
      setFirstName(user.first_name || '');
      setLastName(user.last_name || '');
      setEmail(user.email || '');
      setMobile(user.mobile || '');
      setAvatarUrl(user.avatar_path || '');
    }
  }, [user]);

  const handleSave = async () => {
    if (!user?.id || !token) return;
    
    setIsSaving(true);
    try {
      const response = await fetch(API_ENDPOINTS.users.update(user.id), {
        method: 'PUT',
        headers: getAuthHeaders(token),
        body: JSON.stringify({
          first_name: firstName,
          last_name: lastName,
          email: email,
          mobile: mobile,
          avatar_path: avatarUrl,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to update profile');
      }

      setUser(data);
      toast.success('Profile updated successfully');
    } catch (error) {
      toast.error('Failed to update profile', {
        description: error instanceof Error ? error.message : 'Please try again later',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleAvatarChange = () => {
    // Create a file input element
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = (e: Event) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        // Check file size (max 5MB)
        if (file.size > 5 * 1024 * 1024) {
          toast.error('File too large', {
            description: 'Please select an image smaller than 5MB.',
          });
          return;
        }

        // Create a preview URL
        const reader = new FileReader();
        reader.onload = (event) => {
          const imageUrl = event.target?.result as string;
          setAvatarUrl(imageUrl);
          toast.success('Avatar updated successfully', {
            description: `${file.name} has been set as your profile picture.`,
          });
        };
        reader.readAsDataURL(file);
      }
    };
    input.click();
  };

  const handlePasswordChange = async () => {
    if (!user?.id || !token) return;
    
    // Validation
    if (!newPassword || !confirmPassword) {
      toast.error('Please fill in all fields');
      return;
    }

    if (newPassword.length < 8) {
      toast.error('Password too short', {
        description: 'Password must be at least 8 characters long.',
      });
      return;
    }

    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match', {
        description: 'Please make sure both passwords are the same.',
      });
      return;
    }

    setIsSavingPassword(true);
    try {
      const response = await fetch(API_ENDPOINTS.users.changePassword(user.id), {
        method: 'PUT',
        headers: getAuthHeaders(token),
        body: JSON.stringify({
          new_password: newPassword,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to change password');
      }

      toast.success('Password changed successfully', {
        description: 'Your password has been updated.',
      });
      
      setIsPasswordDialogOpen(false);
      setNewPassword('');
      setConfirmPassword('');
    } catch (error) {
      toast.error('Failed to change password', {
        description: error instanceof Error ? error.message : 'Please try again later',
      });
    } finally {
      setIsSavingPassword(false);
    }
  };

  const handlePasswordDialogChange = (open: boolean) => {
    setIsPasswordDialogOpen(open);
    if (!open) {
      setNewPassword('');
      setConfirmPassword('');
      setShowNewPassword(false);
      setShowConfirmPassword(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-xl sm:text-2xl text-foreground mb-1">Profile</h1>
        <p className="text-sm sm:text-base text-muted-foreground">Manage your account settings and preferences</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">
        {/* Profile Card */}
        <Card className="premium-card lg:col-span-1">
          <div className="p-5 sm:p-6">
          <div className="text-center">
            <div className="relative inline-block mb-4">
              <Avatar className="w-24 h-24">
                <AvatarImage src={avatarUrl} alt={user?.first_name} />
                <AvatarFallback className="bg-blue-600 text-white text-2xl">
                  {user?.first_name?.[0]}{user?.last_name?.[0]}
                </AvatarFallback>
              </Avatar>
              <button
                onClick={handleAvatarChange}
                className="absolute bottom-0 right-0 p-2.5 gradient-primary rounded-full text-white transition-all shadow-lg hover:shadow-xl hover:scale-110 glow-primary"
                aria-label="Change avatar"
              >
                <Camera className="w-4 h-4" />
              </button>
            </div>

            <h2 className="text-xl text-foreground mb-1">
              {user?.first_name} {user?.last_name}
            </h2>
            <p className="text-muted-foreground mb-3">{user?.email}</p>

            <Badge className={
              user?.role === 'admin'
                ? 'badge-premium shadow-lg'
                : 'badge-info shadow-lg'
            }>
              <Shield className="w-3.5 h-3.5 mr-1.5" />
              {user?.role === 'admin' ? 'Administrator' : 'Employee'}
            </Badge>

            <div className="mt-6 pt-6 border-t border-border">
              <div className="space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Member since</span>
                  <span className="text-foreground">
                    {user?.created_at ? formatDateIST(user.created_at) : 'N/A'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Jobs created</span>
                  <span className="text-foreground">{user?.job_count ?? 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Last login</span>
                  <span className="text-foreground">Today</span>
                </div>
              </div>
            </div>
          </div>
          </div>
        </Card>

        {/* Edit Form */}
        <Card className="premium-card lg:col-span-2">
          <div className="p-5 sm:p-6">
            <h3 className="text-lg sm:text-xl text-foreground mb-6">Personal Information</h3>

          <form className="space-y-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="first-name" className="text-foreground">
                  First Name
                </Label>
                <Input
                  id="first-name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  className="bg-background border-input text-foreground"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="last-name" className="text-foreground">
                  Last Name
                </Label>
                <Input
                  id="last-name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  className="bg-background border-input text-foreground"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="email" className="text-foreground">
                Email Address
              </Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-10 bg-background border-input text-foreground"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="mobile" className="text-foreground">
                Mobile Number
              </Label>
              <div className="relative">
                <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="mobile"
                  type="tel"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                  className="pl-10 bg-background border-input text-foreground"
                />
              </div>
            </div>

            <div className="pt-4 flex flex-col sm:flex-row gap-3">
              <Button
                type="button"
                onClick={handleSave}
                disabled={isSaving}
                className="gradient-primary glow-primary w-full sm:w-auto h-11"
              >
                {isSaving ? (
                  <>
                    <span className="animate-spin mr-2">⏳</span>
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4 mr-2" />
                    Save Changes
                  </>
                )}
              </Button>
            </div>
          </form>

          {/* Password Change Section */}
          <div className="mt-8 pt-8 border-t border-border">
            <h3 className="text-xl text-foreground mb-4">Security</h3>
            <p className="text-muted-foreground text-sm mb-4">
              Change your password to keep your account secure
            </p>
            <Button
              variant="outline"
              onClick={() => setIsPasswordDialogOpen(true)}
              className="border-blue-500/50 text-blue-500 hover:bg-blue-500 hover:text-white transition-all w-full sm:w-auto h-11"
            >
              <Lock className="w-4 h-4 mr-2" />
              Change Password
            </Button>
          </div>
          </div>
        </Card>
      </div>

      {/* Password Change Dialog */}
      <Dialog open={isPasswordDialogOpen} onOpenChange={handlePasswordDialogChange}>
        <DialogContent className="bg-card border-border text-foreground">
          <DialogHeader>
            <DialogTitle className="text-foreground">Change Password</DialogTitle>
            <DialogDescription className="text-muted-foreground">
              Enter your new password below. Make sure it's at least 8 characters long.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="new-password" className="text-foreground">
                New Password
              </Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="new-password"
                  type={showNewPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter new password"
                  className="pl-10 pr-10 bg-background border-input text-foreground"
                />
                <button
                  type="button"
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirm-password" className="text-foreground">
                Confirm Password
              </Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="confirm-password"
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  className="pl-10 pr-10 bg-background border-input text-foreground"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {newPassword && confirmPassword && newPassword !== confirmPassword && (
              <p className="text-sm text-red-500">Passwords do not match</p>
            )}
          </div>

          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button
              variant="outline"
              onClick={() => handlePasswordDialogChange(false)}
              className="border-blue-500/50 text-blue-500 hover:bg-blue-500 hover:text-white transition-all w-full sm:w-auto h-10"
            >
              Cancel
            </Button>
            <Button
              onClick={handlePasswordChange}
              disabled={isSavingPassword || !newPassword || !confirmPassword}
              className="gradient-primary w-full sm:w-auto h-10"
            >
              {isSavingPassword ? (
                <>
                  <span className="animate-spin mr-2">⏳</span>
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-2" />
                  Save Password
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
