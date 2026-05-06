// Centralised date/time helpers — everything is rendered in
// Indian Standard Time (Asia/Kolkata) to keep the UI consistent
// across the studio.

const IST_TZ = 'Asia/Kolkata';
const LOCALE = 'en-IN';

const toDate = (input: string | number | Date | null | undefined): Date | null => {
  if (input === null || input === undefined || input === '') return null;
  const d = input instanceof Date ? input : new Date(input);
  return isNaN(d.getTime()) ? null : d;
};

/**
 * Format a date+time in IST. Example: "12 Mar 2026, 3:45 PM IST".
 */
export const formatIST = (
  input: string | number | Date | null | undefined,
  opts: Intl.DateTimeFormatOptions = {},
): string => {
  const d = toDate(input);
  if (!d) return '—';
  const formatted = new Intl.DateTimeFormat(LOCALE, {
    timeZone: IST_TZ,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    ...opts,
  }).format(d);
  return `${formatted} IST`;
};

/**
 * Format a date only in IST. Example: "12 Mar 2026".
 */
export const formatDateIST = (
  input: string | number | Date | null | undefined,
): string => {
  const d = toDate(input);
  if (!d) return '—';
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone: IST_TZ,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(d);
};

/**
 * Format a time only in IST. Example: "3:45 PM IST".
 */
export const formatTimeIST = (
  input: string | number | Date | null | undefined,
): string => {
  const d = toDate(input);
  if (!d) return '—';
  const t = new Intl.DateTimeFormat(LOCALE, {
    timeZone: IST_TZ,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(d);
  return `${t} IST`;
};

/**
 * Short relative-friendly date in IST. Example: "Today, 3:45 PM IST",
 * "Yesterday, 9:00 AM IST", or full date+time for older values.
 */
export const formatRelativeIST = (
  input: string | number | Date | null | undefined,
): string => {
  const d = toDate(input);
  if (!d) return '—';
  const now = new Date();
  const istNow = new Date(now.toLocaleString('en-US', { timeZone: IST_TZ }));
  const istThen = new Date(d.toLocaleString('en-US', { timeZone: IST_TZ }));
  const sameDay =
    istNow.getFullYear() === istThen.getFullYear() &&
    istNow.getMonth() === istThen.getMonth() &&
    istNow.getDate() === istThen.getDate();
  const yesterday = new Date(istNow);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday =
    yesterday.getFullYear() === istThen.getFullYear() &&
    yesterday.getMonth() === istThen.getMonth() &&
    yesterday.getDate() === istThen.getDate();
  if (sameDay) return `Today, ${formatTimeIST(d)}`;
  if (isYesterday) return `Yesterday, ${formatTimeIST(d)}`;
  return formatIST(d);
};
