"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import Link from "next/link";

import { EmptyState, ListSkeleton, PageHeader } from "@/components/app/page";
import { RunRow } from "@/components/runs/run-row";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

export default function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<RunSummary[]>("/runs") });
  return (
    <>
      <PageHeader eyebrow="Assessments" title="My assessments" description="Everything your company has started, in progress or completed."
        actions={<Button asChild variant="outline"><Link href="/app/assessments">Start a new one</Link></Button>} />
      {runs.isLoading ? <ListSkeleton /> : !runs.data?.length ? (
        <EmptyState icon={ClipboardCheck} title="No assessments yet" text="Pick one from the catalog to get started."
          action={<Button asChild><Link href="/app/assessments">Browse the catalog</Link></Button>} />
      ) : (
        <div className="space-y-2">{runs.data.map((r) => <RunRow key={r.id} run={r} />)}</div>
      )}
    </>
  );
}
