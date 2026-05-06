/**
 * Extract a YouTube video ID from any of the URL formats YouTube ships.
 * Returns '' if the URL doesn't contain a recognisable 11-char video id.
 *
 * Supports: watch?v=, youtu.be, /live/, /embed/, /v/, /shorts/.
 */
export function extractVideoId(url: string): string {
  if (!url) return '';

  const patterns = [
    /(?:youtube\.com\/watch\?(?:.*&)?v=)([a-zA-Z0-9_-]{11})/,
    /(?:youtu\.be\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/live\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/,
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match && match[1]) return match[1];
  }
  return '';
}

/**
 * Build a safe, embeddable YouTube URL from any YouTube URL.
 *
 * **CRITICAL**: returns '' if the input is not a valid YouTube URL we can
 * embed. Callers MUST treat '' as "no embed possible" and render a
 * fallback (e.g. an "Open on YouTube" link) instead of an iframe — an
 * iframe with `src=""` (or a relative URL the browser can't resolve)
 * silently loads the *parent document's URL*, which in our SPA means the
 * Dashboard renders inside the player. That was the source of the
 * "video card is showing the dashboard" bug.
 */
export function getYouTubeEmbedUrl(
  url?: string | null,
  opts: { autoplay?: boolean } = {},
): string {
  if (!url) return '';
  const id = extractVideoId(url);
  if (!id) return '';
  const params = new URLSearchParams({ rel: '0' });
  if (opts.autoplay) params.set('autoplay', '1');
  return `https://www.youtube.com/embed/${id}?${params.toString()}`;
}
