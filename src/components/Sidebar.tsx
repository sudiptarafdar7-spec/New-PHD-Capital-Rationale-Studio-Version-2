import React, { useEffect, useState } from 'react';
import { 
  LayoutDashboard, 
  Video, 
  FileSpreadsheet, 
  PenTool, 
  Layers,
  BarChart3,
  FileText, 
  User, 
  Key, 
  Users, 
  FileCode, 
  Upload,
  Play,
  X,
  ChevronLeft,
  ChevronRight,
  Radio,
  Mic,
  Sparkles,
  Wifi
} from 'lucide-react';
import { useAuth } from '../lib/auth-context';
import { cn } from './ui/utils';
import { API_ENDPOINTS } from '../lib/api-config';
import defaultLogo from '../assets/phd-logo.webp';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  currentPage?: string;
  onNavigate: (page: string) => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  badge?: string;
  adminOnly?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

export default function Sidebar({ isOpen, onClose, currentPage, onNavigate, isCollapsed = false, onToggleCollapse }: SidebarProps) {
  const { user, token } = useAuth();
  const [logoSrc, setLogoSrc] = useState<string>(defaultLogo);

  // Pull the company logo uploaded under Upload Files → Company Logo
  // and use it as the sidebar brand logo. Falls back to the bundled PHD
  // Capital logo if no upload exists or the fetch fails.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    (async () => {
      try {
        const listRes = await fetch(API_ENDPOINTS.uploadedFiles.getAll, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!listRes.ok) return;
        const data = await listRes.json();
        const companyLogo = Array.isArray(data)
          ? data.find((f: any) => f.file_type === 'companyLogo')
          : null;
        if (!companyLogo?.id) return;
        const fileRes = await fetch(API_ENDPOINTS.uploadedFiles.download(companyLogo.id), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!fileRes.ok) return;
        const blob = await fileRes.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) setLogoSrc(objectUrl);
      } catch {
        /* keep default logo */
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token]);
  const isAdmin = user?.role === 'admin';

  const navSections: NavSection[] = [
    {
      title: 'Overview',
      items: [
        { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
      ],
    },
    {
      title: 'Media Presence',
      items: [
        { id: 'media-presence', label: 'Media Presence', icon: <Radio className="w-5 h-5" /> },
      ],
    },
    {
      title: 'Transcript Tools',
      items: [
        { id: 'voice-typing', label: 'Voice Typing', icon: <Mic className="w-5 h-5" /> },
        { id: 'ai-transcribe', label: 'AI Transcribe', icon: <Sparkles className="w-5 h-5" /> },
      ],
    },
    {
      title: 'Rationale Tools',
      items: [
        { id: 'bulk-rationale', label: 'Bulk Rationale', icon: <Layers className="w-5 h-5" /> },
        { id: 'premium-rationale', label: 'Premium Rationale', icon: <FileSpreadsheet className="w-5 h-5" /> },
        { id: 'manual-rationale', label: 'Manual Rationale', icon: <PenTool className="w-5 h-5" /> },
      ],
    },
    {
      title: 'Other Tools',
      items: [
        { id: 'generate-chart', label: 'Generate Chart', icon: <BarChart3 className="w-5 h-5" /> },
      ],
    },
    {
      title: 'Management',
      items: [
        { id: 'saved-rationale', label: 'Saved Rationale', icon: <FileText className="w-5 h-5" /> },
        { id: 'profile', label: 'View Profile', icon: <User className="w-5 h-5" /> },
      ],
    },
    {
      title: 'Administration',
      items: [
        { id: 'users', label: 'Users', icon: <Users className="w-5 h-5" />, adminOnly: true },
        { id: 'api-keys', label: 'API Keys', icon: <Key className="w-5 h-5" />, adminOnly: true },
        { id: 'pdf-template', label: 'PDF Template', icon: <FileCode className="w-5 h-5" />, adminOnly: true },
        { id: 'upload-files', label: 'Upload Required Files', icon: <Upload className="w-5 h-5" />, adminOnly: true },
        { id: 'channel-logos', label: 'Manage Platform', icon: <Play className="w-5 h-5" />, adminOnly: true },
      ],
    },
  ];

  const handleNavigate = (page: string) => {
    onNavigate(page);
    onClose();
  };

  const NavButton = ({ item }: { item: NavItem }) => {
    const button = (
      <button
        data-tour={`nav-${item.id}`}
        onClick={() => handleNavigate(item.id)}
        className={cn(
          "w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-all duration-200 text-left group",
          currentPage === item.id
            ? "bg-primary/15 text-primary shadow-sm glow-primary"
            : "text-foreground/80 hover:bg-accent hover:text-foreground",
          isCollapsed && "justify-center"
        )}
      >
        <div className={cn("flex items-center gap-3", isCollapsed && "gap-0")}>
          {item.icon}
          {!isCollapsed && <span className="truncate">{item.label}</span>}
        </div>
        {!isCollapsed && item.badge && (
          <span className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 rounded shrink-0">
            {item.badge}
          </span>
        )}
      </button>
    );

    if (isCollapsed) {
      return (
        <TooltipProvider delayDuration={0}>
          <Tooltip>
            <TooltipTrigger asChild>
              {button}
            </TooltipTrigger>
            <TooltipContent side="right" className="flex items-center gap-2">
              {item.label}
              {item.badge && (
                <span className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 rounded">
                  {item.badge}
                </span>
              )}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      );
    }

    return button;
  };

  return (
    <>
      {/* Backdrop for mobile */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed lg:relative inset-y-0 left-0 z-50 glass-strong border-r border-glass-border transition-all duration-300 flex flex-col shadow-xl",
          isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
          isCollapsed ? "lg:w-20 w-64" : "w-64"
        )}
      >
        {/* Header with Logo and Collapse Button */}
        <div className={cn(
          "flex items-center justify-between p-4 border-b border-border shrink-0",
          isCollapsed && "lg:justify-center lg:p-3"
        )}>
          {!isCollapsed && (
            <div className="flex items-center gap-3 w-full">
              <div className="bg-gradient-to-br from-slate-900 to-slate-800 rounded-lg p-1.5 shrink-0 flex items-center justify-center h-11 w-11">
                <img src={logoSrc} alt="Company logo" className="max-h-full max-w-full object-contain" />
              </div>
              <div className="lg:block hidden min-w-0">
                <h2 className="text-foreground font-medium text-sm truncate">Rationale Studio</h2>
              </div>
            </div>
          )}
          
          {isCollapsed && (
            <div className="lg:flex hidden bg-gradient-to-br from-slate-900 to-slate-800 rounded-lg p-1.5 items-center justify-center h-11 w-11">
              <img src={logoSrc} alt="Company logo" className="max-h-full max-w-full object-contain" />
            </div>
          )}

          {/* Desktop Collapse Toggle */}
          <button
            onClick={onToggleCollapse}
            className="hidden lg:flex p-1.5 hover:bg-accent rounded-lg transition-colors shrink-0"
            aria-label="Toggle sidebar"
          >
            {isCollapsed ? (
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronLeft className="w-4 h-4 text-muted-foreground" />
            )}
          </button>

          {/* Mobile Close Button */}
          <button
            onClick={onClose}
            className="lg:hidden p-2 hover:bg-accent rounded-lg transition-colors"
            aria-label="Close menu"
          >
            <X className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>

        {/* Sidebar Content */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden py-4 px-3">
          <nav className="space-y-6">
            {navSections.map((section) => {
              const visibleItems = section.items.filter(
                item => !item.adminOnly || (item.adminOnly && isAdmin)
              );

              if (visibleItems.length === 0) return null;

              return (
                <div key={section.title}>
                  {!isCollapsed && (
                    <h3 className="px-3 mb-2 text-xs uppercase tracking-wider text-muted-foreground/80 truncate">
                      {section.title}
                    </h3>
                  )}
                  {isCollapsed && (
                    <div className="h-px bg-border mx-2 mb-2" />
                  )}
                  <ul className="space-y-1">
                    {visibleItems.map((item) => (
                      <li key={item.id}>
                        <NavButton item={item} />
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </nav>
        </div>

        {/* Footer */}
        <div className={cn(
          "p-4 border-t border-border shrink-0",
          isCollapsed && "lg:p-2"
        )}>
          {!isCollapsed && (
            <p className="text-xs text-muted-foreground text-center">
              © 2025 PHD CAPITAL
            </p>
          )}
          {isCollapsed && (
            <p className="text-xs text-muted-foreground text-center hidden lg:block">
              © 2025
            </p>
          )}
        </div>
      </aside>
    </>
  );
}
