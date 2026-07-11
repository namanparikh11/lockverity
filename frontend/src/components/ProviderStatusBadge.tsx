type Tone = "ok" | "warn" | "danger" | "muted" | "info" | "unknown";

const TONE_CLASSES: Record<Tone, string> = {
  unknown: "bg-ink-100 text-ink-700 border-ink-200",
  info: "bg-accent-50 text-accent-700 border-accent-200",
  ok: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warn: "bg-amber-50 text-amber-700 border-amber-200",
  danger: "bg-rose-50 text-rose-700 border-rose-200",
  muted: "bg-ink-50 text-ink-500 border-ink-200",
};

function toneFor(status: string): Tone {
  switch (status) {
    case "available":
    case "cached":
      return "ok";
    case "partial":
      return "warn";
    case "rate_limited":
      return "warn";
    case "unavailable":
      return "danger";
    case "not_requested":
    case "unknown":
      return "muted";
    default:
      return "unknown";
  }
}

export function ProviderStatusBadge({ status }: { status: string }) {
  const tone = toneFor(status);
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
      aria-label={`Provider status: ${status}`}
    >
      {status}
    </span>
  );
}
