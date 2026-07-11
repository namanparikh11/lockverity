/**
 * Format an ISO 8601 timestamp as a human-friendly relative phrase.
 *
 * The output is intentionally coarse - this is for at-a-glance
 * display in tables and detail headers. Exact times are still
 * available as a tooltip.
 */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diffMs = Date.now() - date.getTime();
  const abs = Math.abs(diffMs);
  const future = diffMs < 0;
  const minutes = Math.round(abs / 60_000);
  if (minutes < 1) return future ? "in seconds" : "just now";
  if (minutes < 60) return future ? `in ${minutes}m` : `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return future ? `in ${hours}h` : `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return future ? `in ${days}d` : `${days}d ago`;
  return date.toISOString().slice(0, 10);
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toISOString().replace("T", " ").replace(/\..*$/, " UTC");
}
