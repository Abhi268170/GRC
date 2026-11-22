import { ArrowUpRight, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Bar, RunStatusBadge, scoreTone } from "@/components/runs/badges";
import { formatDate, initials } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

export function RunRow({ run }: { run: RunSummary }) {
  return (
    <Link href={`/app/runs/${run.id}`} className="group flex items-center gap-5 rounded-3xl bg-card px-5 py-4 transition hover:ring-2 hover:ring-brand/60">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">{initials(run.title)}</span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 truncate text-[15px] font-medium">
          {run.title}
          {run.version_deprecated && (
            <span className="inline-flex items-center gap-1 text-xs font-normal text-warning-foreground dark:text-warning" title="A newer version is available">
              <TriangleAlert className="size-3.5" /> v{run.version}
            </span>
          )}
        </p>
        <p className="text-xs text-muted-foreground">{run.started_by.full_name} · {formatDate(run.started_at)}</p>
      </div>
      <div className="hidden w-48 space-y-1.5 md:block">
        <div className="flex justify-between text-xs text-muted-foreground"><span>{run.domains_completed}/{run.domains_total} domains</span><span>{run.progress}%</span></div>
        <Bar value={run.progress} max={100} />
      </div>
      <div className="hidden w-16 text-right lg:block">
        {run.score !== null && <span className={`display text-2xl ${scoreTone(run.score)}`}>{run.score.toFixed(1)}</span>}
      </div>
      <RunStatusBadge status={run.status} />
      <ArrowUpRight className="size-4 text-muted-foreground transition group-hover:text-foreground" />
    </Link>
  );
}
