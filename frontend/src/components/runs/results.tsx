"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileText, MessageSquareWarning, RotateCcw, TriangleAlert, Undo2, X } from "lucide-react";
import { useState } from "react";

import { BigNumber, ListSkeleton, SegmentBar } from "@/components/app/page";
import { MaturityBadge, scoreTone } from "@/components/runs/badges";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { ActionItem, Results, RiskItem, RunDetail } from "@/lib/types";

const PRIORITY: Record<string, string> = {
  critical: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
  high: "border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  low: "border-border bg-muted text-muted-foreground",
};

function riskTone(score: number) {
  return score >= 15 ? "bg-red-500 text-white" : score >= 10 ? "bg-orange-500 text-white" : score >= 5 ? "bg-amber-400 text-amber-950" : "bg-muted text-foreground";
}

function ChangesDialog({ run, onClose }: { run: RunDetail; onClose: () => void }) {
  const [domain, setDomain] = useState(run.domains[0]?.id ?? "");
  const [comment, setComment] = useState("");
  const send = useAction(() => api(`/runs/${run.id}/request-changes`, { body: { run_domain_id: domain, comment } }), {
    invalidate: [["run", run.id], ["runs"]], success: "Sent back for changes", onSuccess: onClose,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request changes</DialogTitle>
          <DialogDescription>The domain goes back to whoever is assigned (or the person who started the assessment) with your comment.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Select value={domain} onValueChange={setDomain}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>{run.domains.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}</SelectContent>
          </Select>
          <Textarea rows={4} placeholder="What needs to change?" value={comment} onChange={(e) => setComment(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => send.mutate(undefined)} disabled={comment.trim().length < 3 || send.isPending}>Send back</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SuggestionToggle({ item, kind, reviewing, runId }: { item: ActionItem | RiskItem; kind: "action-items" | "risks"; reviewing: boolean; runId: string }) {
  const body = (status: string) => kind === "action-items"
    ? { ...(item as ActionItem), priority: (item as ActionItem).priority ?? "medium", owner_id: item.owner?.id ?? null, status }
    : { ...(item as RiskItem), owner_id: item.owner?.id ?? null, status };
  const set = useAction((status: string) => api(`/${kind}/${item.id}`, { method: "PUT", body: body(status) }), { invalidate: [["results", runId]] });
  if (!reviewing) return null;
  return item.status === "dismissed" ? (
    <Button variant="ghost" size="xs" onClick={() => set.mutate("suggested")}><Undo2 /> Restore</Button>
  ) : (
    <Button variant="ghost" size="xs" onClick={() => set.mutate("dismissed")}><X /> Dismiss</Button>
  );
}

export function ResultsView({ run }: { run: RunDetail }) {
  const results = useQuery({ queryKey: ["results", run.id], queryFn: () => api<Results>(`/runs/${run.id}/results`) });
  const [changes, setChanges] = useState(false);
  const approve = useAction(() => api(`/runs/${run.id}/approve`, { method: "POST" }), { invalidate: [["run", run.id], ["runs"], ["results", run.id]], success: "Assessment approved" });
  if (!results.data?.report) return <ListSkeleton />;
  const { report, actions, risks } = results.data;
  const reviewing = run.status === "in_review" && run.can_review;
  const liveActions = actions.filter((a) => a.status !== "dismissed").length;
  const liveRisks = risks.filter((r) => r.status !== "dismissed").length;

  return (
    <div className="space-y-6">
      {run.status === "in_review" && (
        <Alert className="rounded-3xl border-0 bg-card p-5">
          <FileText />
          <AlertTitle>{reviewing ? "Ready for your review" : "Waiting for review"}</AlertTitle>
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{reviewing ? "Check the results, dismiss any suggestions that don't fit, then approve. Anything not dismissed becomes an open action item or risk." : "The person who started this assessment or an admin will review and approve it."}</span>
            {reviewing && (
              <span className="flex shrink-0 gap-2">
                <Button variant="outline" size="sm" onClick={() => setChanges(true)}><RotateCcw /> Request changes</Button>
                <Button size="sm" onClick={() => approve.mutate(undefined)} disabled={approve.isPending}><CheckCircle2 /> Approve</Button>
              </span>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <div className="glass-brand flex flex-col justify-between rounded-3xl p-6 text-black">
          <p className="text-[15px] text-black/70">Overall maturity</p>
          <BigNumber value={report.overall.score?.toFixed(1) ?? "—"} unit="/4" className="my-6 text-7xl" />
          <p className="text-xs leading-relaxed text-black/70">{report.overall.explanation}</p>
        </div>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">Framework coverage</CardTitle>
            <span className="text-xs text-muted-foreground">Clauses at maturity 3 or higher</span>
          </CardHeader>
          <CardContent className="space-y-4">
            {report.frameworks.map((f) => (
              <div key={f.name} className="space-y-2">
                <div className="flex items-end justify-between gap-4 text-sm"><span className="text-muted-foreground">{f.name}</span><span><BigNumber value={f.pct ?? 0} unit="%" className="text-3xl" /> <span className="text-xs text-muted-foreground">{f.covered}/{f.considered} clauses</span></span></div>
                <SegmentBar value={f.pct ?? 0} max={100} />
              </div>
            ))}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="outline" size="sm" asChild><a href={`/api/runs/${run.id}/report.pdf`}><Download /> PDF report</a></Button>
              <Button variant="outline" size="sm" asChild><a href={`/api/runs/${run.id}/report.docx`}><Download /> Word report</a></Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="summary">
        <TabsList>
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="actions">Action items <Badge variant="secondary" className="ml-1">{liveActions}</Badge></TabsTrigger>
          <TabsTrigger value="risks">Risks <Badge variant="secondary" className="ml-1">{liveRisks}</Badge></TabsTrigger>
          <TabsTrigger value="findings">Findings</TabsTrigger>
        </TabsList>

        <TabsContent value="summary" className="space-y-4 pt-2">
          <Card><CardContent><p className="text-sm leading-relaxed">{report.executive_summary}</p></CardContent></Card>
          <div className="grid gap-4 md:grid-cols-2">
            {report.domains.map((d) => (
              <Card key={d.name}>
                <CardHeader className="flex flex-row items-start justify-between gap-3">
                  <CardTitle className="text-base">{d.name}</CardTitle>
                  <span className={`display text-4xl ${scoreTone(d.score)}`}>{d.score?.toFixed(1) ?? "—"}</span>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <p className="text-muted-foreground">{d.summary}</p>
                  {d.weakest_link && <p className="flex items-center gap-1.5 text-xs text-destructive"><TriangleAlert className="size-3.5" /> Includes a requirement rated 0</p>}
                  {!!d.gaps?.length && <ul className="list-disc space-y-1 pl-4 text-xs">{d.gaps.map((g) => <li key={g}>{g}</li>)}</ul>}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="actions" className="pt-2">
          <div className="overflow-hidden rounded-3xl bg-card">
            {actions.map((a) => (
              <div key={a.id} className={`flex gap-4 border-b px-5 py-4 last:border-0 ${a.status === "dismissed" ? "opacity-50" : ""}`}>
                <Badge variant="outline" className={`h-fit shrink-0 capitalize ${PRIORITY[a.priority ?? "low"]}`}>{a.priority}</Badge>
                <div className="min-w-0 flex-1 space-y-1">
                  <p className={`text-sm font-medium ${a.status === "dismissed" ? "line-through" : ""}`}>{a.title}</p>
                  <p className="text-sm text-muted-foreground">{a.description}</p>
                  <p className="font-mono text-xs text-muted-foreground">{a.requirement_keys.join(" · ")}</p>
                </div>
                <SuggestionToggle item={a} kind="action-items" reviewing={reviewing} runId={run.id} />
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="risks" className="pt-2">
          <div className="overflow-hidden rounded-3xl bg-card">
            {risks.map((r) => (
              <div key={r.id} className={`flex gap-4 border-b px-5 py-4 last:border-0 ${r.status === "dismissed" ? "opacity-50" : ""}`}>
                <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold ${riskTone(r.score)}`} title={`Likelihood ${r.likelihood} × impact ${r.impact}`}>{r.score}</span>
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-medium">{r.title}</p>
                  <p className="text-sm text-muted-foreground">{r.description}</p>
                  <p className="text-xs text-muted-foreground">Likelihood {r.likelihood} · Impact {r.impact} · <span className="capitalize">{r.category?.replace("_", " ")}</span> · <span className="font-mono">{r.requirement_keys.join(" · ")}</span></p>
                </div>
                <SuggestionToggle item={r} kind="risks" reviewing={reviewing} runId={run.id} />
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="findings" className="space-y-4 pt-2">
          {report.domains.map((d) => (
            <div key={d.name} className="overflow-hidden rounded-3xl bg-card">
              <div className="flex items-center justify-between border-b bg-muted/40 px-5 py-3">
                <h3 className="font-medium">{d.name}</h3>
                <span className={`font-semibold ${scoreTone(d.score)}`}>{d.score?.toFixed(1) ?? "—"}</span>
              </div>
              {d.requirements.map((r) => (
                <div key={r.key} className="flex gap-4 border-b px-5 py-3 last:border-0">
                  <span className="w-10 shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">{r.key}</span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm">{r.statement}</p>
                    {r.rationale && <p className="text-xs text-muted-foreground">{r.rationale}</p>}
                  </div>
                  <div className="shrink-0"><MaturityBadge rating={r.rating} na={r.na} /></div>
                </div>
              ))}
            </div>
          ))}
        </TabsContent>
      </Tabs>
      {changes && <ChangesDialog run={run} onClose={() => setChanges(false)} />}
      {run.status === "changes_requested" && (
        <Alert><MessageSquareWarning /><AlertDescription>These results will be regenerated after the changes are made and resubmitted.</AlertDescription></Alert>
      )}
    </div>
  );
}
