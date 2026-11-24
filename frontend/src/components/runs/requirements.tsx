"use client";

import { Check, ChevronsLeft, ChevronsRight, FileText, Loader2, Paperclip, Plus, UserCheck, X } from "lucide-react";
import { useRef, useState } from "react";

import { FrameworkBadge } from "@/components/app/status";
import { MandatoryBadge, MATURITY_LABEL, MaturityBadge } from "@/components/runs/badges";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Evaluation, EvidenceFile, RequirementState } from "@/lib/types";

export type RequirementInput = { answer: string | null; rating: number | null; is_na: boolean; na_reason: string | null; evidence_ids: string[] };

/** A person has set or accepted the rating. */
export const isConfirmed = (e: Evaluation | null) => !!e && (e.status === "verified" || e.status === "overridden");

export function statusText(e: Evaluation | null): { label: string; tone: string; icon: React.ReactNode } {
  if (!e) return { label: "Not rated yet", tone: "text-muted-foreground", icon: null };
  if (e.status === "awaiting_ai") return { label: "AI is rating this…", tone: "text-accent-foreground", icon: <Loader2 className="size-3 animate-spin" /> };
  if (e.status === "ai_suggested") return { label: "AI suggestion", tone: "text-accent-foreground", icon: null };
  const who = e.verified_by ? ` by ${e.verified_by.full_name.split(" ")[0]}` : "";
  const label = e.ai_rating === null && !e.ai_is_na ? "Rated" : e.status === "overridden" ? "Adjusted" : "Verified";
  return { label: `${label}${who}`, tone: "text-success", icon: <UserCheck className="size-3" /> };
}

/** Status dot used in the collapsed rail. */
function Dot({ e }: { e: Evaluation | null }) {
  const cls = !e ? "border-2 border-muted-foreground/30 bg-transparent"
    : e.status === "awaiting_ai" ? "animate-pulse bg-brand/60"
    : e.status === "ai_suggested" ? "bg-brand"
    : "bg-primary";
  return <span className={`size-2.5 rounded-full ${cls}`} />;
}

/** Requirements side panel: a slim rail by default, expandable to compact cards. Click opens the detail sheet. */
export function RequirementsRail({ requirements, expanded, onToggle, onOpen, analysisPending, editable, onConfirmAll, confirming }: {
  requirements: RequirementState[]; expanded: boolean; analysisPending: boolean; editable: boolean; confirming: boolean;
  onToggle: () => void; onOpen: (r: RequirementState) => void; onConfirmAll: () => void;
}) {
  const confirmed = requirements.filter((r) => isConfirmed(r.evaluation)).length;
  const suggested = requirements.filter((r) => r.evaluation?.status === "ai_suggested").length;

  // One panel whose width animates; the collapsed and expanded views are layered and cross-fade, so the
  // neighbouring chat panel resizes smoothly instead of the content swapping in a single frame.
  const collapsedView = (
        <div className="flex h-full w-16 flex-col items-center gap-3 py-4">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" onClick={onToggle} aria-label="Show requirements"><ChevronsLeft /></Button>
            </TooltipTrigger>
            <TooltipContent side="left">Show requirements</TooltipContent>
          </Tooltip>
          <div className="text-center leading-tight">
            <p className="text-lg font-light">{confirmed}</p>
            <p className="text-[10px] text-muted-foreground">of {requirements.length}</p>
          </div>
          {analysisPending && <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Checking other requirements" />}
          <div className="flex min-h-0 flex-1 flex-col items-center gap-1 overflow-y-auto px-1">
            {requirements.map((r) => (
              <Tooltip key={r.id}>
                <TooltipTrigger asChild>
                  <button onClick={() => onOpen(r)} className="flex w-12 flex-col items-center gap-1 rounded-xl py-1.5 hover:bg-muted" aria-label={`${r.key}: ${statusText(r.evaluation).label}`}>
                    <Dot e={r.evaluation} />
                    <span className="font-mono text-[10px] text-muted-foreground">{r.key}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="left" className="max-w-xs">{r.statement}</TooltipContent>
              </Tooltip>
            ))}
          </div>
        </div>
  );
  const expandedView = (
      <div className="flex h-full w-[22rem] flex-col">
        <div className="flex items-start justify-between gap-2 px-5 pb-2 pt-5">
          <div>
            <p className="text-[15px] text-muted-foreground">Requirements</p>
            <p className="display mt-1 text-3xl">{confirmed}<span className="text-sm tracking-normal text-muted-foreground">/{requirements.length} confirmed</span></p>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onToggle} aria-label="Collapse requirements"><ChevronsRight /></Button>
        </div>
        <div className="flex items-center justify-between gap-2 px-5 pb-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">{analysisPending && <><Loader2 className="size-3 animate-spin" /> Checking other requirements…</>}</span>
          {editable && suggested > 1 && (
            <Button size="xs" variant="outline" onClick={onConfirmAll} disabled={confirming}>{confirming ? <Loader2 className="animate-spin" /> : <Check />} Confirm all {suggested}</Button>
          )}
        </div>
        <div className="flex-1 space-y-1.5 overflow-y-auto px-3 pb-3">
          {requirements.map((r) => {
            const st = statusText(r.evaluation);
            return (
              <button key={r.id} onClick={() => onOpen(r)}
                className={`w-full rounded-2xl p-3 text-left transition hover:ring-2 hover:ring-brand/50 ${r.evaluation?.status === "ai_suggested" ? "bg-accent/60" : "bg-muted/60"}`}>
                <div className="flex items-start gap-2">
                  <span className="pt-0.5 font-mono text-[11px] text-muted-foreground">{r.key}</span>
                  <p className="line-clamp-2 min-w-0 flex-1 text-xs leading-relaxed">{r.statement}</p>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {r.evaluation && r.evaluation.status !== "awaiting_ai" && <MaturityBadge rating={r.evaluation.rating} na={r.evaluation.is_na} compact />}
                  <span className={`inline-flex items-center gap-1 text-[11px] ${st.tone}`}>{st.icon}{st.label}</span>
                  {r.mandatory && <span className="ml-auto"><MandatoryBadge value={r.mandatory} /></span>}
                </div>
              </button>
            );
          })}
        </div>
      </div>
  );
  return (
    <div className={`relative h-full overflow-hidden transition-[width] duration-350 ease-smooth ${expanded ? "w-[22rem]" : "w-16"}`}>
      <div inert={expanded} aria-hidden={expanded}
        className={`absolute inset-y-0 left-0 transition-opacity ${expanded ? "pointer-events-none opacity-0 duration-150" : "opacity-100 delay-150 duration-200"}`}>
        {collapsedView}
      </div>
      <div inert={!expanded} aria-hidden={!expanded}
        className={`absolute inset-y-0 left-0 transition-[opacity,transform] ${expanded ? "translate-x-0 opacity-100 delay-100 duration-300" : "pointer-events-none translate-x-3 opacity-0 duration-150"}`}>
        {expandedView}
      </div>
    </div>
  );
}

/** Rating choice: 0-4, N/A, or "let AI rate" (null). */
function RatingPicker({ value, onChange, allowAi }: { value: number | "na" | null; onChange: (v: number | "na" | null) => void; allowAi: boolean }) {
  const opt = (v: number | "na", label: string, title: string) => (
    <button key={String(v)} type="button" title={title} onClick={() => onChange(value === v ? null : v)}
      className={`h-10 rounded-lg text-sm font-medium transition ${value === v ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70"}`}>{label}</button>
  );
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-6 gap-1.5">
        {[0, 1, 2, 3, 4].map((n) => opt(n, String(n), MATURITY_LABEL[n]))}
        {opt("na", "N/A", "Not applicable")}
      </div>
      <p className="text-xs text-muted-foreground">
        {value === null ? (allowAi ? "No rating chosen: the AI will rate it from your answer and evidence." : "Choose a rating.")
          : value === "na" ? "Not applicable to your company. Say why below." : `${value} · ${MATURITY_LABEL[value]}`}
      </p>
    </div>
  );
}

/** Opened from the rail: the requirement with its answer, rating and evidence fields. */
export function RequirementSheet({ requirement, runId, evidence, editable, aiPaused, onClose, onSave, onConfirm, onUpload, busy }: {
  requirement: RequirementState | null; runId: string; evidence: EvidenceFile[]; editable: boolean; aiPaused: boolean; busy: boolean;
  onClose: () => void; onSave: (r: RequirementState, v: RequirementInput) => void; onConfirm: (e: Evaluation) => void;
  onUpload: (f: File) => Promise<EvidenceFile | undefined>;
}) {
  return (
    <Sheet open={!!requirement} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-xl">
        {requirement && (
          <SheetBody key={requirement.id} r={requirement} runId={runId} evidence={evidence} editable={editable}
            aiPaused={aiPaused} busy={busy} onSave={onSave} onConfirm={onConfirm} onUpload={onUpload} />
        )}
      </SheetContent>
    </Sheet>
  );
}

function SheetBody({ r, runId, evidence, editable, aiPaused, busy, onSave, onConfirm, onUpload }: {
  r: RequirementState; runId: string; evidence: EvidenceFile[]; editable: boolean; aiPaused: boolean; busy: boolean;
  onSave: (r: RequirementState, v: RequirementInput) => void; onConfirm: (e: Evaluation) => void; onUpload: (f: File) => Promise<EvidenceFile | undefined>;
}) {
  const e = r.evaluation;
  const [answer, setAnswer] = useState(e?.answer ?? "");
  const [rating, setRating] = useState<number | "na" | null>(e && e.status !== "awaiting_ai" ? (e.is_na ? "na" : e.rating) : null);
  const [naReason, setNaReason] = useState(e?.na_reason ?? "");
  const [added, setAdded] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const byId = new Map(evidence.map((x) => [x.id, x]));
  const cited = new Set((e?.citations ?? []).map((c) => c.evidence_id).filter(Boolean) as string[]);
  const st = statusText(e);

  const original = { answer: e?.answer ?? "", rating: e && e.status !== "awaiting_ai" ? (e.is_na ? "na" : e.rating) : null, na: e?.na_reason ?? "" };
  const changed = answer !== original.answer || rating !== original.rating || naReason !== original.na || added.length > 0;
  // A file that isn't known yet is still uploading. One that failed is not "processing": it never will be ready.
  const processing = added.some((id) => ["pending", "processing", undefined].includes(byId.get(id)?.processing_status));
  const unreadable = added.some((id) => byId.get(id)?.processing_status === "failed");
  const canAskAi = rating === null && (answer.trim() || added.length) && !aiPaused;
  const canSave = rating !== null ? (rating !== "na" || naReason.trim().length >= 3) : canAskAi;

  const save = () => onSave(r, {
    answer: answer.trim() || null, rating: typeof rating === "number" ? rating : null, is_na: rating === "na",
    na_reason: rating === "na" ? naReason.trim() : null, evidence_ids: added,
  });

  return (
    <div className="flex min-h-full flex-col">
      <div className="space-y-4 p-6 pb-4">
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground"><span className="font-mono">{r.key}</span>· {r.control}<MandatoryBadge value={r.mandatory} /></p>
        <SheetTitle className="text-xl font-normal leading-snug tracking-tight">{r.statement}</SheetTitle>
        <SheetDescription className="sr-only">Answer, rate and attach evidence for this requirement.</SheetDescription>
        <div className="space-y-3 rounded-2xl bg-muted px-4 py-3 text-sm">
          {r.guidance && <div><p className="font-medium">How to meet it</p><p className="mt-0.5">{r.guidance}</p></div>}
          {r.evidence.length > 0 && (
            <div>
              <p className="font-medium">What good evidence looks like</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">{r.evidence.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          )}
        </div>
        {r.clauses.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {r.clauses.map((c) => (
              <span key={c.framework_code + c.ref} title={c.title} className="inline-flex items-center gap-1 rounded-md bg-muted py-0.5 pl-1 pr-2.5 text-xs">
                <FrameworkBadge code={c.framework_code} /><span className="font-mono">{c.ref}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {e && (
        <div className={`mx-6 rounded-3xl p-5 ${e.status === "ai_suggested" || e.status === "awaiting_ai" ? "bg-accent/60" : "bg-muted"}`}>
          <div className="flex flex-wrap items-center gap-2">
            {e.status !== "awaiting_ai" && <MaturityBadge rating={e.rating} na={e.is_na} />}
            <span className={`inline-flex items-center gap-1 text-xs ${st.tone}`}>{st.icon}{st.label}</span>
          </div>
          <p className="mt-3 text-sm leading-relaxed">{e.rationale}</p>
          {e.status === "overridden" && (e.ai_rating !== null || e.ai_is_na) && (
            <p className="mt-2 text-xs text-muted-foreground">The AI had suggested {e.ai_is_na ? "N/A" : e.ai_rating}.</p>
          )}
          {cited.size > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {[...cited].map((id) => (
                <a key={id} href={`/api/runs/${runId}/evidence/${id}/file`} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-card px-3 py-1 text-xs hover:opacity-70">
                  <FileText className="size-3.5" />{byId.get(id)?.filename ?? "Evidence"}
                </a>
              ))}
            </div>
          )}
          {editable && e.status === "ai_suggested" && !changed && (
            <Button className="mt-4" size="sm" onClick={() => onConfirm(e)} disabled={busy}><Check /> Confirm AI rating</Button>
          )}
        </div>
      )}

      {editable ? (
        <div className="flex-1 space-y-6 p-6">
          <div className="space-y-2">
            <Label htmlFor="req-answer">Your answer</Label>
            <Textarea id="req-answer" rows={4} maxLength={4000} value={answer} onChange={(ev) => setAnswer(ev.target.value)}
              placeholder="Describe what your company does for this requirement." />
          </div>
          <div className="space-y-2">
            <Label>Rating</Label>
            <RatingPicker value={rating} onChange={setRating} allowAi={!aiPaused} />
            {rating === "na" && <Textarea rows={2} value={naReason} onChange={(ev) => setNaReason(ev.target.value)} placeholder="Why doesn't this apply?" />}
          </div>
          <div className="space-y-2">
            <Label>Evidence</Label>
            <div className="flex flex-wrap gap-1.5">
              {added.map((id) => {
                const f = byId.get(id);
                return (
                  <span key={id} className="inline-flex items-center gap-1.5 rounded-lg bg-muted py-1.5 pl-3 pr-1.5 text-xs">
                    {f?.processing_status === "ready" ? <FileText className="size-3.5" /> : f?.processing_status === "failed" ? <X className="size-3.5 text-destructive" /> : <Loader2 className="size-3.5 animate-spin" />}
                    <span className="max-w-48 truncate">{f?.filename ?? "Uploading…"}</span>
                    <button onClick={() => setAdded((a) => a.filter((x) => x !== id))} className="rounded-sm p-0.5 hover:bg-card" aria-label="Remove"><X className="size-3" /></button>
                  </span>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" disabled={uploading || aiPaused} onClick={() => fileInput.current?.click()}>
                {uploading ? <Loader2 className="animate-spin" /> : <Paperclip />} Upload file
              </Button>
              <input ref={fileInput} type="file" hidden accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg" onChange={async (ev) => {
                const f = ev.target.files?.[0];
                ev.target.value = "";
                if (!f) return;
                setUploading(true);
                const up = await onUpload(f);
                setUploading(false);
                if (up) setAdded((a) => (a.includes(up.id) ? a : [...a, up.id]));
              }} />
              {evidence.some((x) => !cited.has(x.id) && !added.includes(x.id)) && (
                <Popover>
                  <PopoverTrigger asChild><Button variant="outline" size="sm"><Plus /> Choose uploaded</Button></PopoverTrigger>
                  <PopoverContent align="start" className="w-80 p-1">
                    {evidence.filter((x) => !cited.has(x.id) && !added.includes(x.id)).map((x) => (
                      <button key={x.id} onClick={() => setAdded((a) => [...a, x.id])}
                        className="flex w-full items-start gap-2 rounded-[6px] px-2.5 py-2 text-left text-sm hover:bg-accent">
                        <FileText className="mt-0.5 size-4 shrink-0" />
                        <span className="min-w-0"><span className="block truncate">{x.filename}</span>
                          {x.summary && <span className="line-clamp-2 text-xs text-muted-foreground">{x.summary}</span>}</span>
                      </button>
                    ))}
                  </PopoverContent>
                </Popover>
              )}
            </div>
          </div>
        </div>
      ) : (
        <p className="p-6 text-sm text-muted-foreground">{e?.answer ? <>Answer: {e.answer}</> : "This requirement can't be edited right now."}</p>
      )}

      {editable && (
        <div className="sticky bottom-0 space-y-2 border-t bg-popover p-4">
          <Button className="w-full" size="lg" onClick={save} disabled={!changed || !canSave || busy || processing || unreadable}>
            {busy ? <Loader2 className="animate-spin" /> : rating === null ? null : <Check />}
            {rating === null ? "Ask AI to rate" : "Save rating"}
          </Button>
          <p className="text-center text-[11px] text-muted-foreground">
            {unreadable ? "One file couldn't be read. Remove it, or upload it again, to continue." : processing ? "Waiting for the evidence to be read…" : "Your answer and evidence are also checked against the other open requirements, in the background."}
          </p>
        </div>
      )}
    </div>
  );
}
