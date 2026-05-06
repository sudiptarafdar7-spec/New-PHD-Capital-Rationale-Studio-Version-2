import { Youtube, Facebook, Instagram, Send, MessageCircle, Globe, Tv } from 'lucide-react';
import type { ReactNode } from 'react';

interface JobTitleProps {
  platform?: string | null;
  channelName?: string | null;
  date?: string | null;
  time?: string | null;
  /** Optional fallback string used when channel/date/time are all missing. */
  fallback?: string | null;
  className?: string;
  iconSize?: number;
}

/** Render the platform brand icon used inside JobTitle. Exported so other
 *  list views (saved rationale, voice typing) can reuse the same palette. */
export function PlatformIcon({ platform, size = 18 }: { platform?: string | null; size?: number }) {
  const p = (platform || '').toLowerCase();
  const cls = `inline-block shrink-0`;
  const style = { width: size, height: size } as const;
  switch (p) {
    case 'youtube':  return <Youtube     className={`${cls} text-red-500`}     style={style} />;
    case 'facebook': return <Facebook    className={`${cls} text-blue-500`}    style={style} />;
    case 'instagram':return <Instagram   className={`${cls} text-pink-500`}    style={style} />;
    case 'telegram': return <Send        className={`${cls} text-sky-500`}     style={style} />;
    case 'whatsapp': return <MessageCircle className={`${cls} text-emerald-500`} style={style} />;
    case 'tv':       return <Tv          className={`${cls} text-amber-500`}   style={style} />;
    default:         return <Globe       className={`${cls} text-slate-400`}   style={style} />;
  }
}

function fmtDate(d?: string | null): string {
  if (!d) return '';
  // Accept "YYYY-MM-DD" or already "DD-MM-YYYY"; also tolerate ISO datetimes.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  const m2 = /^(\d{2})-(\d{2})-(\d{4})/.exec(d);
  if (m2) return `${m2[1]}-${m2[2]}-${m2[3]}`;
  return d;
}

function fmtTime(t?: string | null): string {
  if (!t) return '';
  // Trim seconds/microseconds → HH:MM.
  const m = /^(\d{2}:\d{2})/.exec(t);
  return m ? m[1] : t;
}

/** Unified job-title display: `[icon] Channel - DD-MM-YYYY - HH:MM`.
 *  Missing pieces are dropped so legacy jobs without a time still render
 *  cleanly. Falls back to the raw `fallback` string only when no
 *  structured data is available at all. */
export default function JobTitle({
  platform, channelName, date, time, fallback, className, iconSize = 18,
}: JobTitleProps) {
  const parts: ReactNode[] = [];
  if (channelName && channelName.trim()) parts.push(channelName.trim());
  const d = fmtDate(date);
  if (d) parts.push(d);
  const t = fmtTime(time);
  if (t) parts.push(t);

  if (parts.length === 0 && fallback) {
    return (
      <span className={`inline-flex items-center gap-1.5 ${className || ''}`}>
        <PlatformIcon platform={platform} size={iconSize} />
        <span className="truncate">{fallback}</span>
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-1.5 flex-wrap ${className || ''}`}>
      <PlatformIcon platform={platform} size={iconSize} />
      {parts.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          {i > 0 && <span className="text-muted-foreground">-</span>}
          <span>{p}</span>
        </span>
      ))}
    </span>
  );
}
