"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Layers, ListChecks, MessageSquareText, Plus, Users } from "lucide-react";
import Link from "next/link";

import { EmptyState, ListSkeleton, PageHeader } from "@/components/app/page";
import { VersionBadge } from "@/components/app/status";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { AssessmentListItem } from "@/lib/types";

export default function AssessmentsPage() {
  const list = useQuery({ queryKey: ["assessments"], queryFn: () => api<AssessmentListItem[]>("/assessments") });
  return (
    <>
      <PageHeader
        title="Assessments"
        description="Pick controls, let the AI write the questions, review, and publish. Published assessments are available to every tenant."
        actions={<Button asChild><Link href="/admin/assessments/new"><Plus /> New assessment</Link></Button>}
      />
      {list.isLoading ? <ListSkeleton rows={3} /> : !list.data?.length ? (
        <EmptyState icon={ClipboardList} title="No assessments yet" text="Create one from the controls in your library."
          action={<Button asChild><Link href="/admin/assessments/new"><Plus /> New assessment</Link></Button>} />
      ) : (
        <div className="grid gap-4">
          {list.data.map((a) => {
            const main = a.published ?? a.draft!;
            return (
              <div key={a.id} className="rounded-3xl bg-card p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 space-y-1.5">
                    <Link href={`/admin/assessments/${main.id}`} className="font-medium hover:opacity-70">{main.title}</Link>
                    {main.description && <p className="line-clamp-2 text-sm text-muted-foreground">{main.description}</p>}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs text-muted-foreground">
                      <span className="inline-flex items-center gap-1"><Layers className="size-3.5" /> {main.domain_count} domains</span>
                      <span className="inline-flex items-center gap-1"><ListChecks className="size-3.5" /> {main.control_count} controls</span>
                      <span className="inline-flex items-center gap-1"><MessageSquareText className="size-3.5" /> {main.question_count} questions</span>
                      <span className="inline-flex items-center gap-1"><Users className="size-3.5" /> {a.run_count} runs</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
                    {a.published && (
                      <Link href={`/admin/assessments/${a.published.id}`} className="flex items-center gap-2">
                        <VersionBadge status="published" version={a.published.version} />
                        <span className="text-xs text-muted-foreground">{formatDate(a.published.published_at)}</span>
                      </Link>
                    )}
                    {a.draft && (
                      <Link href={`/admin/assessments/${a.draft.id}`}><VersionBadge status="draft" version={a.draft.version} /></Link>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
