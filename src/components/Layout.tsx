import React, { useState } from 'react';
import { Menu, Bell, Moon, Sun, LogOut, User, Activity, FileText, ChevronDown, BarChart3 } from 'lucide-react';
import { useAuth } from '../lib/auth-context';
import Sidebar from './Sidebar';
import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';
import logo from '../assets/phd-logo.webp';

interface LayoutProps {
  children: React.ReactNode;
  currentPage?: string;
  onNavigate: (page: string) => void;
}

export default function Layout({ children, currentPage, onNavigate }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [darkMode, setDarkMode] = useState(true);
  const { user, logout } = useAuth();

  // Toggle dark mode
  const toggleDarkMode = () => {
    setDarkMode(!darkMode);
    if (darkMode) {
      document.documentElement.classList.remove('dark');
    } else {
      document.documentElement.classList.add('dark');
    }
  };

  // Initialize dark mode on mount
  React.useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    }
  }, []);

  const handleLogout = () => {
    logout();
    onNavigate('login');
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--background)' }}>
      {/* Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        currentPage={currentPage}
        onNavigate={onNavigate}
        isCollapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-14 sm:h-16 glass-strong border-b border-glass-border flex items-center justify-between px-3 sm:px-4 lg:px-6 shrink-0 shadow-sm">
          {/* Left Section */}
          <div className="flex items-center gap-2 sm:gap-4 min-w-0">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden p-1.5 sm:p-2 hover:bg-accent rounded-lg transition-colors shrink-0"
              aria-label="Toggle menu"
            >
              <Menu className="w-5 h-5 text-foreground" />
            </button>
            

          </div>

          {/* Right Section */}
          <div className="flex items-center gap-1 sm:gap-2 shrink-0">
            <button
              onClick={toggleDarkMode}
              className="p-1.5 sm:p-2 hover:bg-accent rounded-lg transition-colors"
              aria-label="Toggle theme"
            >
              {darkMode ? (
                <Sun className="w-4 h-4 sm:w-5 sm:h-5 text-foreground" />
              ) : (
                <Moon className="w-4 h-4 sm:w-5 sm:h-5 text-foreground" />
              )}
            </button>



            {/* User Menu */}
            <DropdownMenu>
              <DropdownMenuTrigger className="flex items-center gap-1.5 sm:gap-2 p-1 sm:p-1.5 hover:bg-accent rounded-lg transition-colors">
                <Avatar className="w-7 h-7 sm:w-8 sm:h-8">
                  <AvatarImage src={user?.avatar_path} alt={user?.first_name} />
                  <AvatarFallback className="bg-blue-600 text-white text-xs sm:text-sm">
                    {user?.first_name?.[0]}{user?.last_name?.[0]}
                  </AvatarFallback>
                </Avatar>
                <span className="hidden md:inline text-foreground text-sm truncate max-w-[120px] lg:max-w-none">
                  {user?.first_name} {user?.last_name}
                </span>
                <ChevronDown className="w-3 h-3 sm:w-4 sm:h-4 text-muted-foreground hidden md:inline" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <div className="flex flex-col">
                    <span>{user?.first_name} {user?.last_name}</span>
                    <span className="text-xs text-muted-foreground">{user?.email}</span>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem 
                  onClick={() => onNavigate('activity-log')}
                  className="cursor-pointer"
                >
                  <Activity className="mr-2 h-4 w-4" />
                  Activity Log
                </DropdownMenuItem>
                <DropdownMenuItem 
                  onClick={() => onNavigate('saved-rationale')}
                  className="cursor-pointer"
                >
                  <FileText className="mr-2 h-4 w-4" />
                  Saved Rationale
                </DropdownMenuItem>
                <DropdownMenuItem 
                  onClick={() => onNavigate('profile')}
                  className="cursor-pointer"
                >
                  <User className="mr-2 h-4 w-4" />
                  Profile
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem 
                  onClick={handleLogout}
                  variant="destructive"
                  className="cursor-pointer"
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Logout
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto bg-background">
          {children}
        </main>
      </div>
    </div>
  );
}
