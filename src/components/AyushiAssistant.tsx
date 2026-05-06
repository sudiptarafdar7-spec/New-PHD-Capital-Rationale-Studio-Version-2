/**
 * Ayushi — the floating in-app AI assistant.
 *
 * Three superpowers:
 *  1. Chat with GPT-4o that knows the app inside-out (system docs are
 *     embedded server-side in backend/services/assistant_doc.py).
 *  2. Job-aware diagnosis: pulls the user's running / failed jobs and
 *     lets them pick one for a plain-English explanation + fix steps.
 *  3. On-screen tour: the assistant can return `actions` like
 *     navigate / highlight / wait, which this component executes by
 *     calling onNavigate(...) and rendering a spotlight overlay around
 *     `[data-tour="..."]` elements.
 *
 * Auto-failure detection: every 30s we poll /assistant/active-jobs.
 * If a new failed job appears, we pulse the avatar and (on first
 * appearance) auto-open the chat with a job-picker pre-loaded.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Send, X, Sparkles, AlertTriangle, Briefcase, RefreshCw, Compass } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { API_ENDPOINTS, getAuthHeaders } from '../lib/api-config';
import { useAuth } from '../lib/auth-context';
import avatarSrc from '../assets/ayushi.webp';

type ChatRole = 'user' | 'assistant';
interface ChatMessage {
  role: ChatRole;
  content: string;
  // When the assistant proposes an on-screen tour, the actions live on
  // the message so the user can press "Start tour" at their leisure
  // (rather than having the tour run automatically). Cleared after the
  // user starts the tour so the button only appears once.
  pendingActions?: ChatAction[];
}

// Tiny "pop" click sound synthesized on the fly so the widget feels
// alive without shipping any audio asset. Uses a single shared
// AudioContext that's lazily created on the first user gesture (so
// browsers don't block it).
let _ayushiAudioCtx: AudioContext | null = null;
function playPop() {
  try {
    if (typeof window === 'undefined') return;
    if (!_ayushiAudioCtx) {
      const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!Ctx) return;
      _ayushiAudioCtx = new Ctx();
    }
    const ctx = _ayushiAudioCtx!;
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    // Quick downward chirp = satisfying "pop".
    osc.frequency.setValueAtTime(880, now);
    osc.frequency.exponentialRampToValueAtTime(220, now + 0.09);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.18, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.12);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.13);
  } catch {
    /* silent — sound is a nice-to-have */
  }
}

interface ActiveJob {
  jobId: string;
  tool: string;
  status: string;
  title: string;
  hasError: boolean;
}

interface ChatAction {
  type: 'navigate' | 'highlight' | 'wait';
  page?: string;
  selector?: string;
  text?: string;
  ms?: number;
}

// Tiny markdown helpers — we let react-markdown do bold/italic/lists
// but force a tight, dark-mode-friendly look.
function MD({ children }: { children: string }) {
  return (
    <div style={{ fontSize: 13.5, lineHeight: 1.5 }}>
      <ReactMarkdown
        components={{
          p: ({ children }) => <p style={{ margin: '0 0 6px 0' }}>{children}</p>,
          ul: ({ children }) => <ul style={{ margin: '4px 0 6px 18px', padding: 0 }}>{children}</ul>,
          ol: ({ children }) => <ol style={{ margin: '4px 0 6px 20px', padding: 0 }}>{children}</ol>,
          li: ({ children }) => <li style={{ margin: '2px 0' }}>{children}</li>,
          strong: ({ children }) => <strong style={{ color: '#fff', fontWeight: 600 }}>{children}</strong>,
          em: ({ children }) => <em style={{ color: '#cbd5e1' }}>{children}</em>,
          code: ({ children }) => (
            <code style={{ background: '#0b1220', padding: '1px 5px', borderRadius: 4, fontSize: 12 }}>{children}</code>
          ),
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" style={{ color: '#34d399' }}>{children}</a>
          ),
          h1: ({ children }) => <div style={{ fontSize: 14, fontWeight: 700, margin: '4px 0' }}>{children}</div>,
          h2: ({ children }) => <div style={{ fontSize: 13.5, fontWeight: 700, margin: '4px 0' }}>{children}</div>,
          h3: ({ children }) => <div style={{ fontSize: 13, fontWeight: 700, margin: '4px 0' }}>{children}</div>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

interface ChatResponse {
  message: string;
  actions: ChatAction[];
  suggestions: string[];
}

interface Props {
  currentPage?: string;
  onNavigate: (page: string) => void;
}

const PRESETS = [
  'Chart not generating',
  'Stock name not matching',
  'How do I make a rationale from a YouTube URL?',
  'My transcript job is stuck',
  'Help with one of my jobs',
];

const TOOL_LABEL: Record<string, string> = {
  bulk_rationale: 'Bulk Rationale',
  premium_rationale: 'Premium Rationale',
  manual_rationale: 'Manual Rationale',
  ai_transcribe: 'AI Transcribe',
  voice_typing: 'Voice Typing',
  generate_chart: 'Generate Chart',
};
const labelTool = (t: string) => TOOL_LABEL[t] || t;

// ---------------------------------------------------------------------------
// Spotlight overlay — full-screen dim + animated cutout + step-bubble
// with Next / Prev / Skip controls. All sizing is inline-styled so it
// survives any Tailwind v4 purge.
// ---------------------------------------------------------------------------
interface Spotlight {
  rect: DOMRect;
  text: string;
  step: number;       // 1-indexed
  total: number;
  onNext: () => void;
  onSkip: () => void;
  isLast: boolean;
}

function SpotlightLayer({ spot }: { spot: Spotlight | null }) {
  if (!spot) return null;
  const pad = 10;
  const x = Math.max(0, spot.rect.left - pad);
  const y = Math.max(0, spot.rect.top - pad);
  const w = spot.rect.width + pad * 2;
  const h = spot.rect.height + pad * 2;

  // Position the bubble below if there's room, else above.
  const bubbleW = 320;
  const bubbleH = 150;
  const below = y + h + bubbleH + 16 < window.innerHeight;
  const bubbleTop = below ? y + h + 14 : Math.max(8, y - bubbleH - 14);
  const bubbleLeft = Math.min(Math.max(8, x + w / 2 - bubbleW / 2), window.innerWidth - bubbleW - 8);

  // Arrow points down at element if bubble is above, up if bubble is below.
  const arrowOnTop = below; // arrow on the bubble's top edge

  const dimStyle: React.CSSProperties = { position: 'absolute', background: 'rgba(2,6,23,0.72)', backdropFilter: 'blur(2px)' };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9998, pointerEvents: 'none' }}>
      {/* Four dim panels around the cutout (clicks pass through) */}
      <div style={{ ...dimStyle, left: 0, top: 0, right: 0, height: y }} />
      <div style={{ ...dimStyle, left: 0, top: y, width: x, height: h }} />
      <div style={{ ...dimStyle, left: x + w, top: y, right: 0, height: h }} />
      <div style={{ ...dimStyle, left: 0, top: y + h, right: 0, bottom: 0 }} />

      {/* Animated emerald ring around the cutout */}
      <div
        style={{
          position: 'absolute', left: x, top: y, width: w, height: h,
          borderRadius: 12, border: '3px solid #34d399',
          boxShadow: '0 0 0 4px rgba(52,211,153,0.25), 0 0 40px 6px rgba(52,211,153,0.55)',
          animation: 'ayushiRing 1.4s ease-in-out infinite',
        }}
      />
      {/* Outer pulsing halo (separate so it can ping outward) */}
      <div
        style={{
          position: 'absolute', left: x - 6, top: y - 6, width: w + 12, height: h + 12,
          borderRadius: 16, border: '2px solid rgba(52,211,153,0.6)',
          animation: 'ayushiHalo 1.6s ease-out infinite',
          pointerEvents: 'none',
        }}
      />

      {/* Bouncing arrow pointing at element */}
      <div
        style={{
          position: 'absolute',
          left: x + w / 2 - 14,
          top: arrowOnTop ? y - 38 : y + h + 6,
          color: '#34d399',
          animation: arrowOnTop ? 'ayushiArrowDown 1s ease-in-out infinite' : 'ayushiArrowUp 1s ease-in-out infinite',
          filter: 'drop-shadow(0 0 6px rgba(52,211,153,0.7))',
        }}
      >
        <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
          {arrowOnTop
            ? <path d="M12 21l-7-9h4V3h6v9h4z" stroke="white" strokeWidth="1.2" />
            : <path d="M12 3l7 9h-4v9H9v-9H5z" stroke="white" strokeWidth="1.2" />}
        </svg>
      </div>

      {/* Step bubble */}
      <div
        style={{
          position: 'absolute', left: bubbleLeft, top: bubbleTop,
          width: bubbleW, pointerEvents: 'auto',
          background: '#0f172a', border: '1px solid #34d399',
          borderRadius: 14, color: '#e2e8f0',
          boxShadow: '0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(52,211,153,0.25)',
          padding: '12px 14px',
        }}
      >
        {/* tiny tick connecting bubble to element */}
        <div
          style={{
            position: 'absolute', left: Math.max(12, Math.min(bubbleW - 24, x + w / 2 - bubbleLeft - 6)),
            [arrowOnTop ? 'top' : 'bottom']: -7,
            width: 12, height: 12, transform: 'rotate(45deg)',
            background: '#0f172a', borderLeft: '1px solid #34d399', borderTop: '1px solid #34d399',
            ...(arrowOnTop ? {} : { borderLeft: 'none', borderTop: 'none', borderRight: '1px solid #34d399', borderBottom: '1px solid #34d399' }),
          }}
        />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#34d399', fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>
            <Sparkles style={{ width: 12, height: 12 }} />
            Step {spot.step} of {spot.total}
          </div>
          <button
            onClick={spot.onSkip}
            style={{ background: 'transparent', border: 'none', color: '#94a3b8', fontSize: 11, cursor: 'pointer', padding: 0 }}
          >
            Skip tour
          </button>
        </div>
        <div style={{ fontSize: 13.5, lineHeight: 1.45, color: '#f1f5f9', marginBottom: 12 }}>
          {spot.text || 'Click here to continue'}
        </div>
        {/* Progress bar */}
        <div style={{ height: 4, background: '#1e293b', borderRadius: 999, overflow: 'hidden', marginBottom: 10 }}>
          <div
            style={{
              width: `${(spot.step / spot.total) * 100}%`,
              height: '100%', background: 'linear-gradient(90deg,#10b981,#34d399)',
              transition: 'width 300ms ease',
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={spot.onNext}
            style={{
              fontSize: 12, padding: '6px 14px', borderRadius: 8,
              background: 'linear-gradient(135deg,#10b981,#059669)', border: 'none', color: 'white',
              fontWeight: 600, cursor: 'pointer', boxShadow: '0 4px 12px rgba(16,185,129,0.4)',
            }}
          >
            {spot.isLast ? 'Done' : 'Next →'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function AyushiAssistant({ currentPage, onNavigate }: Props) {
  const { token, isAuthenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([]);
  const [failedCount, setFailedCount] = useState(0);
  const [showJobPicker, setShowJobPicker] = useState(false);
  const [jobContextId, setJobContextId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>(PRESETS);
  const [spot, setSpot] = useState<Spotlight | null>(null);
  const previouslyFailedRef = useRef<Set<string>>(new Set());
  const greetedRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // ---- Active-jobs polling for failure detection -------------------------
  const fetchActive = useCallback(async () => {
    if (!isAuthenticated || !token) return;
    try {
      const r = await fetch(API_ENDPOINTS.assistant.activeJobs, {
        headers: getAuthHeaders(token),
      });
      if (!r.ok) return;
      const data = await r.json();
      const jobs: ActiveJob[] = data.jobs || [];
      setActiveJobs(jobs);
      setFailedCount(data.failedCount || 0);

      // Detect newly-failed jobs (ones we haven't seen fail before).
      const seen = previouslyFailedRef.current;
      const newlyFailed = jobs.filter(
        (j) => (j.hasError || j.status === 'failed') && !seen.has(j.jobId),
      );
      newlyFailed.forEach((j) => seen.add(j.jobId));

      if (newlyFailed.length > 0 && !open && greetedRef.current) {
        // Auto-open with the first newly failed job pre-selected.
        const j = newlyFailed[0];
        setOpen(true);
        setJobContextId(j.jobId);
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `I noticed your **${labelTool(j.tool)}** job "${j.title}" just failed. Want me to take a look?`,
          },
        ]);
        setSuggestions(['Yes, what went wrong?', 'How do I fix it?']);
      }
    } catch {
      /* swallow — it's a poll */
    }
  }, [isAuthenticated, token, open]);

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchActive();
    const id = setInterval(fetchActive, 30_000);
    return () => clearInterval(id);
  }, [isAuthenticated, fetchActive]);

  // ---- Greet on first open ----------------------------------------------
  useEffect(() => {
    if (open && !greetedRef.current) {
      greetedRef.current = true;
      setMessages([
        {
          role: 'assistant',
          content:
            "Hi, I'm Ayushi 👋 I can help you build rationales, fix stuck jobs, or walk you through any feature. What do you need?",
        },
      ]);
    }
  }, [open]);

  // ---- Auto-scroll chat --------------------------------------------------
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  // ---- Tour engine -------------------------------------------------------
  // Step-by-step: navigate/wait actions execute inline, but each highlight
  // becomes a tour "step" that waits for the user to click Next/Skip.
  const tourCancelRef = useRef<{ cancelled: boolean }>({ cancelled: false });

  const runActions = useCallback(
    async (actions: ChatAction[]) => {
      tourCancelRef.current.cancelled = false;
      const cancel = tourCancelRef.current;

      // Count only highlight actions that have a selector — those are the
      // ones that will actually become a tour step. This keeps the
      // "Step X of Y" counter accurate even if the LLM emits an empty
      // highlight by mistake.
      const totalSteps = actions.filter(
        (a) => a.type === 'highlight' && !!a.selector,
      ).length;
      let currentHighlight = 0;

      // Auto-collapse the chat panel during the tour so it doesn't cover
      // the spotlight target. We re-open it when the tour ends.
      const wasOpen = open;
      if (totalSteps > 0) setOpen(false);

      const cleanup = () => {
        setSpot(null);
        if (wasOpen) setTimeout(() => setOpen(true), 200);
      };

      for (let i = 0; i < actions.length; i++) {
        if (cancel.cancelled) break;
        const a = actions[i];

        if (a.type === 'navigate' && a.page) {
          onNavigate(a.page);
          await new Promise((r) => setTimeout(r, 450));
          continue;
        }
        if (a.type === 'wait') {
          await new Promise((r) => setTimeout(r, Math.min(a.ms || 400, 5000)));
          continue;
        }
        if (a.type === 'highlight' && a.selector) {
          // Wait for target to mount.
          let el: HTMLElement | null = null;
          for (let t = 0; t < 15; t++) {
            if (cancel.cancelled) break;
            el = document.querySelector(a.selector) as HTMLElement | null;
            if (el) break;
            await new Promise((r) => setTimeout(r, 150));
          }
          if (!el || cancel.cancelled) continue;

          el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
          await new Promise((r) => setTimeout(r, 350));
          if (cancel.cancelled) break;

          currentHighlight += 1;
          const stepIdx = currentHighlight;
          const isLast = stepIdx === totalSteps;

          // Promise resolves when:
          //   - user clicks "Next" / "Done" in the bubble    -> 'next'
          //   - user clicks "Skip tour"                       -> 'skip'
          //   - user clicks the highlighted element itself    -> 'next'
          //     (so the tour follows the user's natural action)
          const userAction = await new Promise<'next' | 'skip'>((resolve) => {
            let onResize: (() => void) | null = null;
            let onElClick: ((e: Event) => void) | null = null;
            const settle = (val: 'next' | 'skip') => {
              if (onResize) {
                window.removeEventListener('resize', onResize);
                window.removeEventListener('scroll', onResize, true);
              }
              if (onElClick && el) {
                el.removeEventListener('click', onElClick, true);
              }
              resolve(val);
            };
            const recompute = () => {
              if (!el) return;
              const rect = el.getBoundingClientRect();
              setSpot({
                rect,
                text: a.text || 'Click here',
                step: stepIdx,
                total: totalSteps,
                isLast,
                onNext: () => { playPop(); settle('next'); },
                onSkip: () => { playPop(); settle('skip'); },
              });
            };
            recompute();
            // Keep the spotlight in sync if the user scrolls/resizes.
            onResize = () => recompute();
            window.addEventListener('resize', onResize);
            window.addEventListener('scroll', onResize, true);
            // Advance the tour the moment the user clicks the
            // highlighted element. We listen in capture phase so the
            // click still goes through to the original handler.
            onElClick = () => {
              playPop();
              // Tiny delay so the element's own click handler fires
              // and any navigation kicks in before we ask for the
              // next step (which usually targets the new page).
              setTimeout(() => settle('next'), 50);
            };
            el.addEventListener('click', onElClick, true);
          });

          if (userAction === 'skip') {
            cancel.cancelled = true;
            break;
          }
        }
      }

      cleanup();
    },
    [onNavigate, open],
  );

  // ---- Send to backend ---------------------------------------------------
  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy || !token) return;
      const next: ChatMessage[] = [...messages, { role: 'user', content: trimmed }];
      setMessages(next);
      setInput('');
      setBusy(true);
      try {
        const r = await fetch(API_ENDPOINTS.assistant.chat, {
          method: 'POST',
          headers: getAuthHeaders(token),
          body: JSON.stringify({
            messages: next,
            currentPage,
            jobContextId,
          }),
        });
        const data: ChatResponse = await r.json();
        // Attach any proposed on-screen tour to the message itself so the
        // chat shows a "Start tour" button — we never auto-run anymore.
        const hasTour = !!data.actions?.length;
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.message,
            pendingActions: hasTour ? data.actions : undefined,
          },
        ]);
        setSuggestions(data.suggestions?.length ? data.suggestions : []);
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: "Sorry, I couldn't reach the server. Try again in a moment." },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, currentPage, jobContextId, messages, runActions, token],
  );

  // Pre-set click handler — supports special "pick a job" preset
  const onPreset = (p: string) => {
    if (/help with one of my jobs/i.test(p)) {
      setShowJobPicker(true);
      return;
    }
    send(p);
  };

  const pickJob = (j: ActiveJob) => {
    setJobContextId(j.jobId);
    setShowJobPicker(false);
    send(`Please diagnose my ${labelTool(j.tool)} job: "${j.title}". What went wrong and what should I do?`);
  };

  const headerJob = useMemo(() => {
    if (!jobContextId) return null;
    return activeJobs.find((j) => j.jobId === jobContextId) || null;
  }, [activeJobs, jobContextId]);

  if (!isAuthenticated) return null;

  return (
    <>
      {/* Inline keyframes so we don't have to touch tailwind config */}
      <style>{`
        @keyframes ayushiPing {
          0%   { transform: scale(1); opacity: .9; }
          80%, 100% { transform: scale(2.2); opacity: 0; }
        }
        @keyframes ayushiRing {
          0%, 100% { box-shadow: 0 0 0 4px rgba(52,211,153,0.25), 0 0 40px 6px rgba(52,211,153,0.55); }
          50%      { box-shadow: 0 0 0 8px rgba(52,211,153,0.45), 0 0 60px 12px rgba(52,211,153,0.85); }
        }
        @keyframes ayushiHalo {
          0%   { transform: scale(1);    opacity: 0.7; }
          100% { transform: scale(1.18); opacity: 0;   }
        }
        @keyframes ayushiArrowDown {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(8px); }
        }
        @keyframes ayushiArrowUp {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-8px); }
        }
      `}</style>

      <SpotlightLayer spot={spot} />

      {/* Floating bubble */}
      {!open && (
        <button
          onClick={() => { playPop(); setOpen(true); }}
          aria-label="Open Ayushi assistant"
          style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 9990, padding: 0, background: 'transparent', border: 'none', cursor: 'pointer' }}
          className="group"
        >
          <div style={{ position: 'relative', width: 56, height: 56 }}>
            <img
              src={avatarSrc}
              alt="Ayushi"
              style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover', boxShadow: '0 8px 30px rgba(16,185,129,0.45)', outline: '2px solid #34d399', display: 'block' }}
              className="transition-transform group-hover:scale-105"
            />
            {/* Live green dot (solid) */}
            <span style={{ position: 'absolute', bottom: 2, right: 2, width: 14, height: 14, borderRadius: '50%', background: '#34d399', boxShadow: '0 0 0 2px #020617' }} />
            {/* Live green dot (pulsing ring) */}
            <span
              style={{ position: 'absolute', bottom: 2, right: 2, width: 14, height: 14, borderRadius: '50%', background: '#34d399', animation: 'ayushiPing 1.6s cubic-bezier(0,0,0.2,1) infinite' }}
            />
            {/* Failure badge */}
            {failedCount > 0 && (
              <span style={{ position: 'absolute', top: -4, left: -4, minWidth: 20, height: 20, padding: '0 6px', borderRadius: 999, background: '#ef4444', color: '#fff', fontSize: 11, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 0 2px #020617' }}>
                {failedCount}
              </span>
            )}
          </div>
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div
          style={{
            position: 'fixed', bottom: 20, right: 20, zIndex: 9990,
            width: 360, maxWidth: 'calc(100vw - 24px)',
            height: 560, maxHeight: 'calc(100vh - 40px)',
            background: '#0f172a',  // solid slate-900 — never transparent
            border: '1px solid #334155',
            borderRadius: 16,
            boxShadow: '0 20px 60px rgba(0,0,0,0.55)',
            overflow: 'hidden',
          }}
          className="flex flex-col">
          {/* Header */}
          <div
            style={{ background: '#0f172a', borderBottom: '1px solid #334155' }}
            className="flex items-center gap-3 px-4 py-3">
            <div className="relative shrink-0">
              <img src={avatarSrc} alt="Ayushi" className="w-10 h-10 rounded-full object-cover ring-2 ring-emerald-400" />
              <span className="absolute bottom-0 right-0 block w-3 h-3 rounded-full bg-emerald-400 ring-2 ring-slate-900" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-slate-100 text-sm font-medium leading-tight">Ayushi</div>
              <div className="text-emerald-400 text-[11px] leading-tight">Live • here to help</div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-slate-200"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Active job context chip */}
          {headerJob && (
            <div className="flex items-center gap-2 px-4 py-2 bg-slate-800/60 border-b border-slate-700 text-xs text-slate-300">
              <Briefcase className="w-3.5 h-3.5 text-emerald-300" />
              <span className="truncate flex-1">
                {labelTool(headerJob.tool)}: {headerJob.title}
              </span>
              <button
                onClick={() => setJobContextId(null)}
                className="text-slate-400 hover:text-slate-200"
                title="Clear job context"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Failed-jobs banner (if any AND we don't already have a job context) */}
          {!headerJob && failedCount > 0 && (
            <button
              onClick={() => setShowJobPicker(true)}
              className="flex items-center gap-2 px-4 py-2 bg-red-950/40 border-b border-red-900/60 text-xs text-red-200 hover:bg-red-950/60 text-left"
            >
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span className="flex-1">
                {failedCount} job{failedCount > 1 ? 's' : ''} need{failedCount > 1 ? '' : 's'} attention. Tap to diagnose.
              </span>
            </button>
          )}

          {/* Body */}
          <div
            ref={scrollRef}
            style={{ background: '#0f172a' }}
            className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.map((m, i) => {
              const isUser = m.role === 'user';
              const stepCount = m.pendingActions?.filter(
                (a) => a.type === 'highlight' && !!a.selector,
              ).length || 0;
              return (
                <div key={i} className={isUser ? 'flex justify-end' : 'flex justify-start'}>
                  <div
                    style={
                      isUser
                        ? { background: '#059669', color: '#fff' }
                        : { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' }
                    }
                    className={
                      isUser
                        ? 'max-w-[85%] rounded-2xl rounded-br-sm px-3 py-2 text-sm whitespace-pre-wrap'
                        : 'max-w-[90%] rounded-2xl rounded-bl-sm px-3 py-2 text-sm'
                    }
                  >
                    {isUser ? m.content : <MD>{m.content}</MD>}
                    {!isUser && m.pendingActions && stepCount > 0 && (
                      <button
                        onClick={() => {
                          playPop();
                          const actions = m.pendingActions!;
                          // Remove the button so it's a one-shot. Match
                          // by reference identity rather than array
                          // index so a re-rendered list can't clear the
                          // wrong message.
                          setMessages((prev) =>
                            prev.map((mm) =>
                              mm.pendingActions === actions
                                ? { ...mm, pendingActions: undefined }
                                : mm,
                            ),
                          );
                          runActions(actions);
                        }}
                        style={{
                          marginTop: 10,
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '6px 12px',
                          borderRadius: 999,
                          background: 'linear-gradient(135deg,#10b981,#059669)',
                          border: 'none',
                          color: 'white',
                          fontWeight: 600,
                          fontSize: 12,
                          cursor: 'pointer',
                          boxShadow: '0 4px 12px rgba(16,185,129,0.4)',
                        }}
                      >
                        <Compass style={{ width: 14, height: 14 }} />
                        Start tour · {stepCount} step{stepCount === 1 ? '' : 's'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            {busy && (
              <div className="flex justify-start">
                <div className="rounded-2xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-400 inline-flex items-center gap-2">
                  <RefreshCw className="w-3 h-3 animate-spin" /> Ayushi is thinking…
                </div>
              </div>
            )}

            {/* Job picker popover */}
            {showJobPicker && (
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-2 space-y-1">
                <div className="px-2 py-1 text-xs text-slate-400 uppercase tracking-wide">
                  Pick a job for me to diagnose
                </div>
                {activeJobs.length === 0 && (
                  <div className="px-2 py-2 text-sm text-slate-400">
                    You don't have any active jobs right now.
                  </div>
                )}
                {activeJobs.map((j) => (
                  <button
                    key={j.jobId}
                    onClick={() => { playPop(); pickJob(j); }}
                    className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-slate-700 text-sm text-slate-100 flex items-center gap-2"
                  >
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${
                        j.hasError || j.status === 'failed'
                          ? 'bg-red-400'
                          : j.status.startsWith('awaiting')
                          ? 'bg-amber-400'
                          : 'bg-emerald-400 animate-pulse'
                      }`}
                    />
                    <span className="flex-1 truncate">
                      <span className="text-slate-300">{labelTool(j.tool)}</span>
                      <span className="text-slate-500"> · {j.status}</span>
                      <div className="text-xs text-slate-400 truncate">{j.title}</div>
                    </span>
                  </button>
                ))}
                <button
                  onClick={() => setShowJobPicker(false)}
                  className="w-full text-center text-xs text-slate-400 hover:text-slate-200 py-1"
                >
                  Close
                </button>
              </div>
            )}
          </div>

          {/* Suggestion chips */}
          {!busy && suggestions.length > 0 && (
            <div
              style={{ background: '#0f172a' }}
              className="px-3 pt-2 flex flex-wrap gap-1.5"
            >
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => { playPop(); onPreset(s); }}
                  className="text-xs px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            style={{ background: '#0f172a', borderTop: '1px solid #334155' }}
            className="p-3 flex items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask me anything…"
              className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              onClick={() => { if (!busy && input.trim()) playPop(); }}
              className="p-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label="Send"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      )}
    </>
  );
}
