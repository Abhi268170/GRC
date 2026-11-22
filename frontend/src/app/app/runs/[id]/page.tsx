"use client";

import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { useParams } from "next/navigation";

import { ListSkeleton, PageHeader } from "@/components/app/page";
import { Bar, RunStatusBadge } from "@/components/runs/badges";
import { DomainsView } from "@/components/runs/domains";
import { IntakeView, Working } from "@/components/runs/intake";
import { ResultsView } from "@/components/runs/results";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { RunDetail } from "@/lib/types";

const BUSY = (r?: RunDetail) =>
  !!r && (r.status === "generating_outputs" || (r.status === "intake" && ["generating", "tailoring"].includes(r.intake?.status ?? "generating")));

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const run = useQuery({
    queryKey: ["run", id],
    queryFn: () => api<RunDetail>(`/runs/${id}`),
    refetchInterval: (q) => (BUSY(q.state.data) ? 2500 : false),
  });
  if (!run.data) return <ListSkeleton />;
  const r = run.data;
  const showResults = ["in_review", "approved"].includes(r.status);

  return (
    <>
      <PageHeader
        back={{ href: "/app/runs", label: "My assessments" }}
        title={r.title}
        description={r.status === "intake" ? r.assessment_description : undefined}
        meta={<>
          <RunStatusBadge status={r.status} />
          <span className="text-sm text-muted-foreground">v{r.version} · started by {r.started_by.full_name} on {formatDate(r.started_at)}</span>
          {r.approved_at && <span className="text-sm text-muted-foreground">· approved {formatDate(r.approved_at)}</span>}
        </>}
        actions={!showResults && r.status !== "intake" && (
          <div className="w-48 space-y-1.5">
            <div className="flex justify-between text-xs text-muted-foreground"><span>Ratings confirmed</span><span>{r.progress}%</span></div>
            <Bar value={r.progress} max={100} />
          </div>
        )}
      />
      {r.version_deprecated && (
        <Alert className="mb-6 border-warning/40 bg-warning/10">
          <TriangleAlert />
          <AlertTitle>A newer version of this assessment is available</AlertTitle>
          <AlertDescription>You can finish this one on version {r.version}. Your next run of this assessment will use the latest version.</AlertDescription>
        </Alert>
      )}
      {r.status === "intake" && <IntakeView key={r.intake?.status} run={r} />}
      {(r.status === "in_progress" || r.status === "changes_requested") && <DomainsView run={r} />}
      {r.status === "generating_outputs" && (
        <Working title="Preparing your results" text="Calculating scores and framework coverage, then drafting action items, risks and the report. This takes a minute or two." />
      )}
      {r.outputs_job_status === "failed" && r.status === "in_progress" && (
        <Alert variant="destructive" className="mt-6"><TriangleAlert /><AlertTitle>Results couldn't be generated</AlertTitle><AlertDescription>{r.outputs_job_error} Submit again to retry.</AlertDescription></Alert>
      )}
      {showResults && <ResultsView run={r} />}
    </>
  );
}
