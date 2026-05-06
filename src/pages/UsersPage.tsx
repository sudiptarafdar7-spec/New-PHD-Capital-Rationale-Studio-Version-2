import React, { useState, useEffect } from 'react';
import { formatDateIST } from '@/lib/datetime';
import { Users, Plus, Trash2, Edit, Mail, Phone, Shield, Upload, Lock, Eye, EyeOff, RefreshCw } from 'lucide-react';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { useAuth } from '../lib/auth-context';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Avatar, AvatarFallback, AvatarImage } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { toast } from 'sonner@2.0.3';

interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  mobile: string;
  role: 'admin' | 'employee';
  avatar_path?: string;
  created_at: string;
}

export default function UsersPage() {
  const { user: currentUser, setUser: setCurrentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    mobile: '',
    role: 'employee' as 'admin' | 'employee',
    password: '',
    confirmPassword: '',
    avatar_path: '',
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [deleteUserId, setDeleteUserId] = useState<string | null>(null);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(API_ENDPOINTS.users.getAll, {
        headers: getAuthHeaders(token || ''),
      });

      if (response.ok) {
        const data = await response.json();
        setUsers(data);
      } else {
        toast.error('Failed to fetch users');
      }
    } catch (error) {
      console.error('Error fetching users:', error);
      toast.error('Error loading users');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(API_ENDPOINTS.users.getAll, {
        headers: getAuthHeaders(token || ''),
      });

      if (response.ok) {
        const data = await response.json();
        setUsers(data);
        toast.success('Users list refreshed');
      } else {
        toast.error('Failed to refresh users');
      }
    } catch (error) {
      console.error('Error refreshing users:', error);
      toast.error('Error refreshing users');
    } finally {
      setRefreshing(false);
    }
  };

  const handleAvatarUpload = () => {
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

        setAvatarFile(file);
        
        // Create a preview URL
        const reader = new FileReader();
        reader.onload = (event) => {
          const imageUrl = event.target?.result as string;
          setFormData({ ...formData, avatar_path: imageUrl });
        };
        reader.readAsDataURL(file);
        
        toast.success('Avatar selected', {
          description: file.name,
        });
      }
    };
    input.click();
  };

  const handleOpenEditDialog = (user: User) => {
    setEditingUser(user);
    setFormData({
      first_name: user.first_name,
      last_name: user.last_name,
      email: user.email,
      mobile: user.mobile,
      role: user.role,
      password: '',
      confirmPassword: '',
      avatar_path: user.avatar_path || '',
    });
    setAvatarFile(null);
    setIsDialogOpen(true);
  };

  const handleOpenAddDialog = () => {
    setEditingUser(null);
    setFormData({
      first_name: '',
      last_name: '',
      email: '',
      mobile: '',
      role: 'employee',
      password: '',
      confirmPassword: '',
      avatar_path: '',
    });
    setAvatarFile(null);
    setIsDialogOpen(true);
  };

  const handleSaveUser = async () => {
    if (!formData.first_name || !formData.last_name || !formData.email) {
      toast.error('Please fill in all required fields');
      return;
    }

    if (!editingUser || formData.password) {
      if (!formData.password && !editingUser) {
        toast.error('Please enter a password');
        return;
      }

      if (formData.password && formData.password.length < 8) {
        toast.error('Password too short', {
          description: 'Password must be at least 8 characters long.',
        });
        return;
      }

      if (formData.password !== formData.confirmPassword) {
        toast.error('Passwords do not match', {
          description: 'Please make sure both passwords are the same.',
        });
        return;
      }
    }

    try {
      const token = localStorage.getItem('token');
      const payload: any = {
        first_name: formData.first_name,
        last_name: formData.last_name,
        email: formData.email,
        mobile: formData.mobile,
        role: formData.role,
      };

      if (avatarFile || formData.avatar_path) {
        payload.avatar_path = formData.avatar_path;
      }

      if (formData.password) {
        payload.password = formData.password;
      }

      if (editingUser) {
        const response = await fetch(API_ENDPOINTS.users.update(editingUser.id), {
          method: 'PUT',
          headers: getAuthHeaders(token || ''),
          body: JSON.stringify(payload),
        });

        if (response.ok) {
          const updatedUser = await response.json();
          setUsers(users.map(user => user.id === editingUser.id ? updatedUser : user));
          
          // If the updated user is the current logged-in user, update auth context
          if (currentUser && updatedUser.id === currentUser.id) {
            setCurrentUser(updatedUser);
          }
          
          toast.success('User updated successfully', {
            description: `${formData.first_name} ${formData.last_name} has been updated.`,
          });
        } else {
          const error = await response.json();
          toast.error(error.error || 'Failed to update user');
          return;
        }
      } else {
        const response = await fetch(API_ENDPOINTS.users.create, {
          method: 'POST',
          headers: getAuthHeaders(token || ''),
          body: JSON.stringify(payload),
        });

        if (response.ok) {
          const newUser = await response.json();
          setUsers([...users, newUser]);
          toast.success('User added successfully', {
            description: `${formData.first_name} ${formData.last_name} has been added to the system.`,
          });
        } else {
          const error = await response.json();
          toast.error(error.error || 'Failed to create user');
          return;
        }
      }

      setIsDialogOpen(false);
      setEditingUser(null);
      setFormData({ 
        first_name: '', 
        last_name: '', 
        email: '', 
        mobile: '', 
        role: 'employee',
        password: '',
        confirmPassword: '',
        avatar_path: '',
      });
      setAvatarFile(null);
      setShowPassword(false);
      setShowConfirmPassword(false);
    } catch (error) {
      console.error('Error saving user:', error);
      toast.error('An error occurred while saving user');
    }
  };

  const handleConfirmDelete = async () => {
    if (deleteUserId) {
      try {
        const token = localStorage.getItem('token');
        const response = await fetch(API_ENDPOINTS.users.delete(deleteUserId), {
          method: 'DELETE',
          headers: getAuthHeaders(token || ''),
        });

        if (response.ok) {
          const user = users.find(u => u.id === deleteUserId);
          setUsers(users.filter(u => u.id !== deleteUserId));
          toast.success('User deleted', {
            description: `${user?.first_name} ${user?.last_name} has been removed from the system.`,
          });
        } else {
          const error = await response.json();
          toast.error(error.error || 'Failed to delete user');
        }
      } catch (error) {
        console.error('Error deleting user:', error);
        toast.error('An error occurred while deleting user');
      }
      setDeleteUserId(null);
    }
  };

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl text-foreground mb-1">Users (Admin/Employees)</h1>
          <p className="text-sm sm:text-base text-muted-foreground">Manage user accounts and permissions</p>
        </div>

        <div className="flex gap-2 w-full sm:w-auto">
          <Button 
            onClick={handleRefresh}
            disabled={refreshing}
            variant="outline"
            className="flex-1 sm:flex-initial border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600 h-11"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button 
            onClick={handleOpenAddDialog}
            className="gradient-primary glow-primary h-11 flex-1 sm:flex-initial"
          >
            <Plus className="w-4 h-4 mr-2" />
            Add New User
          </Button>
          <span data-tour="users-new" style={{ position: 'absolute', width: 0, height: 0 }} />
        </div>

        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogContent className="bg-card border-border text-foreground">
            <DialogHeader>
              <DialogTitle>{editingUser ? 'Edit User' : 'Add New User'}</DialogTitle>
              <DialogDescription className="text-muted-foreground">
                {editingUser 
                  ? 'Update user account information and permissions'
                  : 'Create a new user account with specific role and permissions'
                }
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 pt-4">
              {/* Avatar Upload */}
              <div className="space-y-2">
                <Label className="text-foreground">Profile Avatar</Label>
                <div className="flex items-center gap-4">
                  <Avatar className="w-16 h-16">
                    <AvatarImage src={formData.avatar_path} alt="Preview" />
                    <AvatarFallback className="bg-blue-600 text-white">
                      {formData.first_name?.[0] || 'U'}{formData.last_name?.[0] || 'N'}
                    </AvatarFallback>
                  </Avatar>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleAvatarUpload}
                    className="border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
                  >
                    <Upload className="w-4 h-4 mr-2" />
                    Upload Avatar
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="first-name" className="text-foreground">
                    First Name *
                  </Label>
                  <Input
                    id="first-name"
                    value={formData.first_name}
                    onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                    className="bg-background border-input text-foreground"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="last-name" className="text-foreground">
                    Last Name *
                  </Label>
                  <Input
                    id="last-name"
                    value={formData.last_name}
                    onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                    className="bg-background border-input text-foreground"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="email" className="text-foreground">
                  Email Address *
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="bg-background border-input text-foreground"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="mobile" className="text-foreground">
                  Mobile Number
                </Label>
                <Input
                  id="mobile"
                  type="tel"
                  value={formData.mobile}
                  onChange={(e) => setFormData({ ...formData, mobile: e.target.value })}
                  className="bg-background border-input text-foreground"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="role" className="text-foreground">
                  Role *
                </Label>
                <Select
                  value={formData.role}
                  onValueChange={(value: 'admin' | 'employee') => setFormData({ ...formData, role: value })}
                >
                  <SelectTrigger className="bg-background border-input text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="employee">Employee</SelectItem>
                    <SelectItem value="admin">Administrator</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-foreground">
                  Password {editingUser ? '(Leave blank to keep current)' : '*'}
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    placeholder={editingUser ? "Enter new password (optional)" : "Enter password"}
                    className="pl-10 pr-10 bg-background border-input text-foreground"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-password" className="text-foreground">
                  Confirm Password {editingUser ? '(Leave blank to keep current)' : '*'}
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    id="confirm-password"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={formData.confirmPassword}
                    onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                    placeholder={editingUser ? "Confirm new password (optional)" : "Confirm password"}
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
                {formData.password && formData.confirmPassword && formData.password !== formData.confirmPassword && (
                  <p className="text-sm text-red-500">Passwords do not match</p>
                )}
              </div>

              <div className="flex flex-col sm:flex-row sm:justify-end gap-2.5 sm:gap-3 pt-4">
                <Button
                  variant="outline"
                  onClick={() => {
                    setIsDialogOpen(false);
                    setEditingUser(null);
                  }}
                  className="w-full sm:w-auto h-11 border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleSaveUser}
                  className="gradient-primary w-full sm:w-auto h-11"
                >
                  {editingUser ? 'Update User' : 'Add User'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Users List */}
      <Card className="bg-card border-border shadow-sm">
        <div className="p-4 sm:p-6 border-b border-border">
          <h2 className="text-lg sm:text-xl text-foreground">All Users ({users.length})</h2>
        </div>

        <div className="divide-y divide-border">
          {users.map((user) => (
            <div key={user.id} className="p-4 sm:p-6 hover:bg-accent/50 transition-colors">
              <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                {/* User Info Section */}
                <div className="flex items-start sm:items-center gap-3 sm:gap-4 flex-1 min-w-0">
                  <Avatar className="w-12 h-12 sm:w-12 sm:h-12 flex-shrink-0">
                    <AvatarImage src={user.avatar_path} alt={user.first_name} />
                    <AvatarFallback className="bg-blue-600 text-white">
                      {user.first_name[0]}{user.last_name[0]}
                    </AvatarFallback>
                  </Avatar>

                  <div className="flex-1 min-w-0">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-2 mb-1.5 sm:mb-1">
                      <h3 className="text-base sm:text-base text-foreground break-words">
                        {user.first_name} {user.last_name}
                      </h3>
                      <Badge className={
                        user.role === 'admin'
                          ? 'bg-purple-500/20 text-purple-500 border-purple-500/30 w-fit'
                          : 'bg-blue-500/20 text-blue-500 border-blue-500/30 w-fit'
                      }>
                        <Shield className="w-3 h-3 mr-1" />
                        {user.role === 'admin' ? 'Admin' : 'Employee'}
                      </Badge>
                    </div>

                    <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-1.5 sm:gap-4 text-xs sm:text-sm text-muted-foreground">
                      <span className="flex items-center gap-1.5 break-all">
                        <Mail className="w-3 h-3 flex-shrink-0" />
                        <span className="break-all">{user.email}</span>
                      </span>
                      {user.mobile && (
                        <span className="flex items-center gap-1.5">
                          <Phone className="w-3 h-3 flex-shrink-0" />
                          {user.mobile}
                        </span>
                      )}
                      <span className="text-muted-foreground">
                        Joined {formatDateIST(user.created_at)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex sm:flex-row gap-2 sm:gap-2 sm:flex-shrink-0">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleOpenEditDialog(user)}
                    className="flex-1 sm:flex-initial border-blue-500/50 text-blue-500 hover:bg-blue-600 hover:text-white hover:border-blue-600 h-9"
                  >
                    <Edit className="w-4 h-4 sm:mr-0" />
                    <span className="sm:hidden ml-2">Edit</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setDeleteUserId(user.id)}
                    className="flex-1 sm:flex-initial border-red-500/30 text-red-500 hover:bg-red-500/10 h-9"
                  >
                    <Trash2 className="w-4 h-4 sm:mr-0" />
                    <span className="sm:hidden ml-2">Delete</span>
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteUserId !== null} onOpenChange={() => setDeleteUserId(null)}>
        <AlertDialogContent className="bg-card border-border text-foreground">
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              This action cannot be undone. This will permanently delete the user account
              {deleteUserId && (() => {
                const user = users.find(u => u.id === deleteUserId);
                return user ? ` for ${user.first_name} ${user.last_name}` : '';
              })()}
              .
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-muted border-border text-foreground hover:bg-accent">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              Delete User
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
