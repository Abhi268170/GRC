import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import type { DomainStatus, RunStatus } from "@/lib/types";

export const MATURITY_LABEL: Record<number, string> = { 0: "Non-existent", 1: "Initial", 2: "Defined", 3: "Managed", 4: "Optimized" };

const MATURITY_STYLE: Record<number, string> = {
  0: "bg-red-500/12 text-red-700 border-red-500/25 dark:text-red-300",
  1: "bg-orange-500/12 text-orange-700 border-orange-500/25 dark:text-orange-300",
  2: "bg-amber-500/15 text-amber-800 border-amber-500/30 dark:text-amber-300",
  3: "bg-emerald-500/12 text-emerald-700 border-emerald-500/25 dark:text-emerald-300",
  4: "bg-teal-500/15 text-teal-700 border-teal-500/30 dark:text-teal-300",
};

export function MaturityBadge({ rating, na, compact }: { rating: number | null; na?: boolean; compact?: boolean }) {
  if (na) return <Badge variant="outline" className="bg-muted text-muted-foreground">N/A</Badge>;
  if (rating === null || rating === undefined) return <Badge variant="outline" className="text-muted-foreground">Not rated</Badge>;
  return (
    <Badge variant="outline" className={`gap-1 ${MATURITY_STYLE[rating]}`}>
      <span className="font-semibold">{rating}</span>{!compact && <span className="font-normal">{MATURITY_LABEL[rating]}</span>}
    </Badge>
  );
}

export function scoreTone(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score < 1.5) return "text-red-600 dark:text-red-400";
  if (score < 2.5) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

const RUN_STATUS: Record<RunStatus, { label: string; cls: string }> = {
  intake: { label: "Getting started", cls: "bg-accent text-accent-foreground border-transparent" },
  in_progress: { label: "In progress", cls: "bg-accent text-accent-foreground border-transparent" },
  generating_outputs: { label: "Preparing results", cls: "bg-accent text-accent-foreground border-transparent" },
  in_review: { label: "In review", cls: "border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning" },
  changes_requested: { label: "Changes requested", cls: "border-destructive/30 bg-destructive/10 text-destructive" },
  approved: { label: "Approved", cls: "border-success/30 bg-success/10 text-success" },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const s = RUN_STATUS[status];
  return <Badge variant="outline" className={s.cls}>{s.label}</Badge>;
}

const DOMAIN_STATUS: Record<DomainStatus, { label: string; cls: string }> = {
  not_started: { label: "Not started", cls: "text-muted-foreground" },
  in_progress: { label: "In progress", cls: "bg-accent text-accent-foreground border-transparent" },
  completed: { label: "Completed", cls: "border-success/30 bg-success/10 text-success" },
  changes_requested: { label: "Changes requested", cls: "border-destructive/30 bg-destructive/10 text-destructive" },
};

export function DomainStatusBadge({ status }: { status: DomainStatus }) {
  const s = DOMAIN_STATUS[status];
  return <Badge variant="outline" className={s.cls}>{s.label}</Badge>;
}

export function Bar({ value, max, className = "" }: { value: number; max: number; className?: string }) {
  const pct = max ? Math.round((value / max) * 100) : 0;
  return (
    <div className={cn("flex h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <div className="h-full rounded-l-full bg-primary transition-[width] duration-500 ease-smooth" style={{ width: `${pct}%` }} />
      {pct > 0 && pct < 100 && <div className="h-full w-1 bg-brand" />}
    </div>
  );
}

/** Shown on requirements marked mandatory or optional in the library (nothing when not set). */
export function MandatoryBadge({ value }: { value: boolean | null }) {
  if (value === null) return null;
  return value
    ? <span className="rounded-full bg-primary px-2 py-0.5 text-[11px] font-medium text-primary-foreground">Mandatory</span>
    : <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">Optional</span>;
}
