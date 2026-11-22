"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Lock, MessageSquareWarning, Send } from "lucide-react";
import Link from "next/link";

import { Bar, DomainStatusBadge } from "@/components/runs/badges";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { useAction, useMe } from "@/lib/hooks";
import type { RunDetail, User } from "@/lib/types";

export function DomainsView({ run }: { run: RunDetail }) {
  const { data: me } = useMe();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users"), enabled: run.can_review });
  const invalidate = [["run", run.id], ["runs"]];
  const assign = useAction(({ domain, user }: { domain: string; user: string | null }) =>
    api(`/runs/${run.id}/domains/${domain}/assignee`, { method: "PUT", body: { user_id: user } }), { invalidate, success: "Assignment saved" });
  const submit = useAction(() => api(`/runs/${run.id}/submit`, { method: "POST" }), { invalidate });
  const allDone = run.domains.every((d) => d.status === "completed");

  return (
    <div className="space-y-6">
      {run.status === "changes_requested" && (
        <Alert variant="destructive">
          <MessageSquareWarning />
          <AlertTitle>Changes were requested</AlertTitle>
          <AlertDescription>Open the highlighted domains to see the reviewer's comments, update your answers, complete them again, and resubmit.</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {run.domains.map((d, i) => {
          const mine = d.assignee?.id === me?.user.id;
          return (
            <div key={d.id} className={`flex flex-col rounded-3xl bg-card p-5 ${d.status === "changes_requested" ? "border-destructive/40" : ""}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs text-muted-foreground">Domain {i + 1}</p>
                  <h3 className="truncate font-medium">{d.name}</h3>
                </div>
                <DomainStatusBadge status={d.status} />
              </div>
              <div className="mt-4 space-y-3 text-xs">
                <div className="space-y-1.5">
                  <div className="flex justify-between text-muted-foreground"><span>Requirements rated</span><span>{d.requirements_rated}/{d.requirements_total}</span></div>
                  <Bar value={d.requirements_rated} max={d.requirements_total} />
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-muted-foreground"><span>Ratings confirmed</span><span>{d.requirements_verified}/{d.requirements_total}</span></div>
                  <Bar value={d.requirements_verified} max={d.requirements_total} />
                </div>
              </div>
              {d.open_comments > 0 && <p className="mt-3 text-xs text-destructive">{d.open_comments} reviewer comment{d.open_comments > 1 ? "s" : ""} to address</p>}
              <div className="mt-5 flex items-center gap-2 pt-1">
                {run.can_review ? (
                  <Select value={d.assignee?.id ?? "none"} onValueChange={(v) => assign.mutate({ domain: d.id, user: v === "none" ? null : v })}>
                    <SelectTrigger size="sm" className="min-w-0 flex-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Unassigned (anyone)</SelectItem>
                      {users.data?.filter((u) => u.is_active).map((u) => <SelectItem key={u.id} value={u.id}>{u.full_name}{u.id === me?.user.id ? " (you)" : ""}</SelectItem>)}
                    </SelectContent>
                  </Select>
                ) : (
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{d.assignee ? (mine ? "Assigned to you" : `Assigned to ${d.assignee.full_name}`) : "Unassigned"}</span>
                )}
                {d.can_work ? (
                  <Button size="sm" asChild variant={d.status === "completed" ? "outline" : "default"}>
                    <Link href={`/app/runs/${run.id}/domains/${d.id}`}>
                      {d.status === "completed" ? <><CheckCircle2 /> View</> : d.status === "not_started" ? <>Start <ArrowRight /></> : <>Continue <ArrowRight /></>}
                    </Link>
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" asChild><Link href={`/app/runs/${run.id}/domains/${d.id}`}><Lock /> View</Link></Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex flex-col items-center justify-between gap-4 rounded-3xl bg-card p-5 sm:flex-row">
        <div>
          <p className="font-medium">{allDone ? "Every domain is complete" : "Submit when every domain is complete"}</p>
          <p className="text-sm text-muted-foreground">The AI then calculates your scores and drafts action items, risks and the report for review.</p>
        </div>
        <Button onClick={() => submit.mutate(undefined)} disabled={!allDone || submit.isPending}><Send /> {run.status === "changes_requested" ? "Resubmit" : "Submit for review"}</Button>
      </div>
    </div>
  );
}
