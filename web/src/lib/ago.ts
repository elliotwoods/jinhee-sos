/** "just now", "4 min ago", "3 h ago", "2 days ago" relative to `now`. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

/** Short absolute UTC time for tooltips and secondary text. */
export const utc = (iso: string) => iso.slice(0, 16).replace("T", " ") + " UTC";
