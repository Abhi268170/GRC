/** A date-only value ("2026-11-30") means that day in the viewer's own time zone, not UTC midnight. */
function parse(value: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return parse(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** A due date is overdue once that whole day has passed. */
export function isOverdue(dueDate: string | null | undefined): boolean {
  if (!dueDate) return false;
  const end = parse(dueDate);
  end.setHours(23, 59, 59, 999);
  return end.getTime() < Date.now();
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

export const APP_NAME = "TrustUp";
