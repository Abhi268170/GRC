"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronLeft, Circle, CircleDot, ListChecks, MessagesSquare, RotateCcw, Scale } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Bar, DomainStatusBadge } from "@/components/runs/badges";
import { Chat, type LiveTurn } from "@/components/runs/chat";
import { type RequirementInput, RequirementSheet, RequirementsRail } from "@/components/runs/requirements";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, errorMessage, streamPost } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { Evaluation, EvidenceFile, QuestionState, RequirementState, Workspace } from "@/lib/types";

function QuestionList({ questions, current }: { questions: QuestionState[]; current: string | null }) {
  const base = questions.filter((q) => q.kind === "base");
  const row = (q: QuestionState, label: string, nested: boolean) => {
    const active = q.id === current;
    const done = q.status !== "pending" && !active;
    const Icon = done ? CheckCircle2 : active ? CircleDot : Circle;
    return (
      <div key={q.id} className={`flex gap-2.5 rounded-2xl px-3 py-2.5 text-xs ${nested ? "ml-4" : ""} ${active ? "bg-accent text-accent-foreground" : ""}`}>
        <Icon className={`mt-0.5 size-3.5 shrink-0 ${done ? "text-success" : active ? "text-primary" : "text-muted-foreground"}`} />
        <span className={`line-clamp-3 ${q.status === "pending" && !active ? "text-muted-foreground" : ""}`}>
          <span className="text-muted-foreground">{label} </span>{q.status === "skipped_na" ? <s>{q.text}</s> : q.text}
        </span>
      </div>
    );
  };
  return (
    <div className="space-y-1 p-3">
      {base.map((q, i) => (
        <div key={q.id} className="space-y-1">
          {row(q, base.length > 1 ? `${i + 1}.` : "", false)}
          {questions.filter((f) => f.kind === "follow_up" && f.parent_id === q.id).map((f, j) => row(f, `Follow-up ${j + 1}:`, true))}
        </div>
      ))}
    </div>
  );
}

type Tab = "chat" | "ratings" | "questions";

export default function DomainWorkspace() {
  const { id, domainId } = useParams<{ id: string; domainId: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const key = ["workspace", id, domainId];
  const ws = useQuery({
    queryKey: key,
    queryFn: () => api<Workspace>(`/runs/${id}/domains/${domainId}`),
    // Poll while evidence is being read or background analysis is updating other requirements.
    refetchInterval: (q) => (q.state.data && (q.state.data.analysis_pending || q.state.data.evidence.some((e) => ["pending", "processing"].includes(e.processing_status))) ? 2500 : false),
  });
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [tab, setTab] = useState<Tab>("chat");
  const [confirming, setConfirming] = useState(false);
  const [openReq, setOpenReq] = useState<string | null>(null);
  // The requirements rail is collapsed by design; remember the viewer's choice.
  // (The rail only renders after the workspace loads in the browser, so reading storage here is safe.)
  const [railOpen, setRailOpen] = useState(() => {
    try { return typeof window !== "undefined" && localStorage.getItem("trustup.rail") === "open"; } catch { return false; }
  });
  const toggleRail = () => setRailOpen((o) => {
    try { localStorage.setItem("trustup.rail", o ? "closed" : "open"); } catch { /* storage unavailable */ }
    return !o;
  });
  const set = (w: Workspace) => qc.setQueryData(key, w);

  const saveRequirement = useAction(({ r, v }: { r: RequirementState; v: RequirementInput }) => api<Workspace>(`/runs/${id}/requirements/${r.id}`, { method: "PUT", body: v }), {
    onSuccess: (w) => { set(w); setOpenReq(null); toast.success("Saved. Checking other requirements in the background."); },
  });
  const verify = useAction((e: Evaluation) => api<Workspace>(`/runs/${id}/evaluations/${e.id}`, { method: "PUT", body: { rating: e.rating, is_na: e.is_na, na_reason: e.na_reason } }), {
    onSuccess: (w) => { set(w); setOpenReq(null); },
  });
  const markNa = useAction(({ q, reason }: { q: string; reason: string }) => api<Workspace>(`/runs/${id}/questions/${q}/na`, { body: { reason } }), { onSuccess: set });
  const complete = useAction(() => api(`/runs/${id}/domains/${domainId}/complete`, { method: "POST" }), {
    invalidate: [["run", id], ["runs"]], success: "Domain completed", onSuccess: () => router.push(`/app/runs/${id}`),
  });
  const reopen = useAction(() => api(`/runs/${id}/domains/${domainId}/reopen`, { method: "POST" }), { invalidate: [key, ["run", id]] });

  // Leaving or reloading while the guide is answering cancels the turn and loses the message.
  useEffect(() => {
    if (!live) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [live]);

  if (!ws.data) {
    return <div className="grid h-[calc(100vh-4.6rem)] gap-3 p-3 lg:grid-cols-[1fr_23rem]"><Skeleton className="h-full rounded-3xl" /><Skeleton className="h-full rounded-3xl" /></div>;
  }
  const w = ws.data;
  const allConfirmed = w.requirements.every((r) => r.evaluation && ["verified", "overridden"].includes(r.evaluation.status));
  const canComplete = w.editable && allConfirmed;

  async function send(text: string, evidence: string[]): Promise<boolean> {
    setLive({ userText: text, reply: "", status: null });
    let failed: string | null = null;
    try {
      await streamPost(`/runs/${id}/domains/${domainId}/messages/stream`, { content: text, evidence_ids: evidence }, (e) => {
        if (e.type === "text") setLive((l) => l && { ...l, reply: l.reply + e.delta, status: null });
        else if (e.type === "status") setLive((l) => l && { ...l, status: e.text });
        else if (e.type === "error") failed = e.message;
      });
    } catch (e) {
      failed = errorMessage(e);
    }
    if (failed) toast.error(failed);
    await ws.refetch(); // saved messages, ratings and the next question
    setLive(null);
    return !failed;
  }


  async function upload(file: File): Promise<EvidenceFile | undefined> {
    const form = new FormData();
    form.append("file", file);
    try {
      const ev = await api<EvidenceFile>(`/runs/${id}/evidence`, { form });
      await ws.refetch();
      return ev;
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function confirmAll() {
    setConfirming(true);
    try {
      for (const r of w.requirements) {
        const e = r.evaluation;
        if (e?.status === "ai_suggested") set(await api<Workspace>(`/runs/${id}/evaluations/${e.id}`, { method: "PUT", body: { rating: e.rating, is_na: e.is_na, na_reason: e.na_reason } }));
      }
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setConfirming(false);
    }
  }

  const headerAction = w.domain.status === "completed" ? (
    w.domain.can_work && ["in_progress", "changes_requested"].includes(w.run_status)
      ? <Button variant="outline" size="sm" onClick={() => reopen.mutate(undefined)}><RotateCcw /> Reopen</Button> : null
  ) : w.editable ? (
    <Tooltip>
      <TooltipTrigger asChild>
        <span><Button size="sm" disabled={!canComplete || complete.isPending} onClick={() => complete.mutate(undefined)}><CheckCircle2 /> Complete domain</Button></span>
      </TooltipTrigger>
      {!canComplete && <TooltipContent>Every requirement needs a confirmed rating</TooltipContent>}
    </Tooltip>
  ) : null;

  const opened = w.requirements.find((r) => r.id === openReq) ?? null;
  const rail = (expanded: boolean) => (
    <RequirementsRail requirements={w.requirements} expanded={expanded} onToggle={toggleRail} onOpen={(r) => setOpenReq(r.id)}
      analysisPending={w.analysis_pending} editable={w.editable} onConfirmAll={confirmAll} confirming={confirming} />
  );
  const rated = w.requirements.filter((r) => r.evaluation && r.evaluation.status !== "awaiting_ai").length;
  const total = w.requirements.length;

  return (
    <div className="flex h-[calc(100vh-4.6rem)] flex-col gap-3 p-3">
      <div className="flex items-center gap-4 rounded-3xl bg-card px-4 py-3 sm:px-5">
        <Link href={`/app/runs/${id}`} className="flex size-9 items-center justify-center rounded-full bg-muted text-muted-foreground hover:text-foreground" aria-label="Back to assessment"><ChevronLeft className="size-4" /></Link>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-medium tracking-tight">{w.domain.name}</p>
          <div className="flex items-center gap-2"><Bar value={rated} max={total} className="w-24 shrink-0" /><span className="whitespace-nowrap text-xs text-muted-foreground">{rated}/{total} requirements rated</span></div>
        </div>
        <DomainStatusBadge status={w.domain.status} />
        {headerAction}
      </div>
      <div className="flex rounded-full bg-card p-1 lg:hidden">
        {([["chat", "Conversation", MessagesSquare], ["ratings", "Requirements", Scale], ["questions", "Outline", ListChecks]] as const).map(([t, label, Icon]) => (
          <button key={t} onClick={() => setTab(t)} className={`flex flex-1 items-center justify-center gap-1.5 rounded-full py-2 text-xs font-medium ${tab === t ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}>
            <Icon className="size-3.5" />{label}
          </button>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[1fr_auto] xl:grid-cols-[17rem_1fr_auto]">
        <aside className={`min-h-0 overflow-y-auto rounded-3xl bg-card ${tab === "questions" ? "block" : "hidden"} xl:block`}>
          <p className="px-5 pt-5 text-[15px] text-muted-foreground">Conversation outline</p>
          <QuestionList questions={w.questions} current={w.current_question_id} />
        </aside>
        <section className={`min-h-0 overflow-hidden rounded-3xl bg-card ${tab === "chat" ? "block" : "hidden"} lg:block`}>
          <Chat ws={w} live={live} onSend={send} onUpload={upload} naBusy={markNa.isPending} onNa={(q, reason) => markNa.mutate({ q, reason })} />
        </section>
        <aside className={`min-h-0 overflow-hidden rounded-3xl bg-card ${tab === "ratings" ? "block" : "hidden"} lg:block`}>
          <div className="h-full lg:hidden">{rail(true)}</div>
          <div className="hidden h-full lg:block">{rail(railOpen)}</div>
        </aside>
      </div>
      <RequirementSheet requirement={opened} runId={id} evidence={w.evidence} editable={w.editable} aiPaused={w.ai_paused}
        busy={saveRequirement.isPending || verify.isPending} onClose={() => setOpenReq(null)}
        onSave={(r, v) => saveRequirement.mutate({ r, v })} onConfirm={(e) => verify.mutate(e)} onUpload={upload} />
    </div>
  );
}
