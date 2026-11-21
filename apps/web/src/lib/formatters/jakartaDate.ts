const JAKARTA_TZ = "Asia/Jakarta";

/**
 * Return current calendar date in Asia/Jakarta (YYYY-MM-DD).
 * Never hardcodes past dates or converts local calendar days to UTC midnight.
 */
export function getJakartaTodayISO(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: JAKARTA_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const y = parts.find((p) => p.type === "year")?.value ?? "2026";
  const m = parts.find((p) => p.type === "month")?.value ?? "01";
  const d = parts.find((p) => p.type === "day")?.value ?? "01";
  return `${y}-${m}-${d}`;
}

export function toJakartaDateInputValue(isoOrDate?: string | null): string {
  if (!isoOrDate) return getJakartaTodayISO();
  const trimmed = isoOrDate.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return getJakartaTodayISO();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: JAKARTA_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parsed);
  const y = parts.find((p) => p.type === "year")?.value ?? "2026";
  const m = parts.find((p) => p.type === "month")?.value ?? "01";
  const d = parts.find((p) => p.type === "day")?.value ?? "01";
  return `${y}-${m}-${d}`;
}

export function formatJakartaDate(isoOrDate?: string | null): string {
  if (!isoOrDate) return "Belum dicatat";
  const trimmed = isoOrDate.trim();
  const d = /^\d{4}-\d{2}-\d{2}$/.test(trimmed)
    ? new Date(`${trimmed}T08:00:00+07:00`)
    : new Date(trimmed);
  if (Number.isNaN(d.getTime())) return isoOrDate;
  return new Intl.DateTimeFormat("id-ID", {
    timeZone: JAKARTA_TZ,
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(d);
}

export function formatJakartaDateTime(iso?: string | null): string {
  if (!iso) return "Belum dicatat";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    new Intl.DateTimeFormat("id-ID", {
      timeZone: JAKARTA_TZ,
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d) + " WIB"
  );
}
