"use client";

import { ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, ChevronLeft, Circle, FileText, Loader2, MessagesSquare, Pencil } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { FrameworkBadge } from "@/components/app/status";
import { Bar, DomainStatusBadge, MandatoryBadge, MaturityBadge } from "@/components/runs/badges";
import { allConfirmed, CompleteOrReopen, useDomainWorkspace } from "@/components/runs/domain-actions";
import { isConfirmed, RequirementSheet, statusText } from "@/components/runs/requirements";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import type { Evaluation, RequirementState, Workspace } from "@/lib/types";

/** What the list says about one requirement: a mark and a few words. */
function listStatus(e: Evaluation | null): { label: string; mark: React.ReactNode; tone: string } {
  if (isConfirmed(e)) return { label: statusText(e).label, mark: <CheckCircle2 className="size-4 text-success" />, tone: "text-success" };
  if (e?.status === "awaiting_ai") return { label: "AI is rating this…", mark: <Loader2 className="size-4 animate-spin text-muted-foreground" />, tone: "text-muted-foreground" };
  if (e?.status === "ai_suggested") return { label: "To check", mark: <span className="m-[3px] size-2.5 rounded-full bg-brand" />, tone: "text-accent-foreground" };
  return { label: "Not rated yet", mark: <Circle className="size-4 text-muted-foreground/50" />, tone: "text-muted-foreground" };
}

/** The next requirement after `from` that a person still has to look at (wraps around); null when none is left. */
function nextToCheck(requirements: RequirementState[], from: number): RequirementState | null {
  for (let i = 1; i <= requirements.length; i++) {
    const r = requirements[(from + i) % requirements.length];
    if (!isConfirmed(r.evaluation)) return r;
  }
  return null;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

/** One requirement in full: what it asks, what was said, the rating with its reasons, the evidence. */
function Detail({ r, w, runId, position }: { r: RequirementState; w: Workspace; runId: string; position: string }) {
  const e = r.evaluation;
  const st = statusText(e);
  // The answers recorded in the conversation (as the guide noted them) on the questions that cover this requirement.
  const said = w.questions.filter((q) => q.answer && q.requirement_keys.includes(r.key));
  const files = new Map<string, { name: string; excerpts: string[] }>();
  for (const c of e?.citations ?? []) {
    if (!c.evidence_id) continue;
    const f = files.get(c.evidence_id) ?? { name: c.evidence_filename ?? "Evidence", excerpts: [] };
    if (c.excerpt) f.excerpts.push(c.excerpt);
    files.set(c.evidence_id, f);
  }
  return (
    <div className="mx-auto max-w-3xl space-y-7 p-6 sm:p-8">
      <div className="space-y-3">
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{position}</span>·<span className="font-mono">{r.key}</span>· {r.control}<MandatoryBadge value={r.mandatory} />
        </p>
        <h2 className="text-2xl font-normal leading-snug tracking-tight">{r.statement}</h2>
        {(r.guidance || r.evidence.length > 0 || r.clauses.length > 0) && (
          <Collapsible>
            <CollapsibleTrigger className="group inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              What this asks for <ChevronDown className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3 space-y-3 rounded-2xl bg-muted px-4 py-3 text-sm">
              {r.guidance && <div><p className="font-medium">How to meet it</p><p className="mt-0.5">{r.guidance}</p></div>}
              {r.evidence.length > 0 && (
                <div>
                  <p className="font-medium">What good evidence looks like</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">{r.evidence.map((x, i) => <li key={i}>{x}</li>)}</ul>
                </div>
              )}
              {r.clauses.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {r.clauses.map((c) => (
                    <span key={c.framework_code + c.ref} title={c.title} className="inline-flex items-center gap-1 rounded-md bg-card py-0.5 pl-1 pr-2.5 text-xs">
                      <FrameworkBadge code={c.framework_code} /><span className="font-mono">{c.ref}</span>
                    </span>
                  ))}
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>

      <Section title="Rating">
        {e ? (
          <div className={`rounded-3xl p-5 ${isConfirmed(e) ? "bg-muted" : "bg-accent/60"}`}>
            <div className="flex flex-wrap items-center gap-2">
              {e.status !== "awaiting_ai" && <MaturityBadge rating={e.rating} na={e.is_na} />}
              <span className={`inline-flex items-center gap-1 text-xs ${st.tone}`}>{st.icon}{st.label}</span>
            </div>
            {e.rationale && <p className="mt-3 text-sm leading-relaxed">{e.rationale}</p>}
            {e.is_na && e.na_reason && <p className="mt-2 text-sm text-muted-foreground">Why it doesn&apos;t apply: {e.na_reason}</p>}
            {e.status === "overridden" && (e.ai_rating !== null || e.ai_is_na) && (
              <p className="mt-2 text-xs text-muted-foreground">The AI had suggested {e.ai_is_na ? "N/A" : e.ai_rating}.</p>
            )}
          </div>
        ) : (
          <p className="rounded-3xl bg-muted p-5 text-sm text-muted-foreground">
            No rating yet. Answer it in the conversation, or give your answer and rating here.
          </p>
        )}
      </Section>

      <Section title="From the conversation">
        {said.length === 0 && !e?.answer && <p className="text-sm text-muted-foreground">Nothing recorded for this requirement yet.</p>}
        <div className="space-y-2">
          {said.map((q) => (
            <div key={q.id} className="rounded-2xl bg-muted px-4 py-3">
              <p className="text-xs text-muted-foreground">{q.text}</p>
              <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed">{q.answer}</p>
            </div>
          ))}
          {e?.answer && (
            <div className="rounded-2xl bg-muted px-4 py-3">
              <p className="text-xs text-muted-foreground">Answer given for this requirement</p>
              <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed">{e.answer}</p>
            </div>
          )}
        </div>
      </Section>

      <Section title="Evidence">
        {files.size === 0 ? <p className="text-sm text-muted-foreground">{e ? "No file was used for this rating." : "No evidence yet."}</p> : (
          <div className="space-y-2">
            {[...files].map(([fileId, f]) => (
              <div key={fileId} className="rounded-2xl bg-muted px-4 py-3">
                <a href={`/api/runs/${runId}/evidence/${fileId}/file`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium hover:opacity-70">
                  <FileText className="size-4" />{f.name}
                </a>
                {f.excerpts.map((x, i) => <p key={i} className="mt-1.5 border-l-2 border-border pl-3 text-sm text-muted-foreground">{x}</p>)}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

export default function DomainReview() {
  const { id, domainId } = useParams<{ id: string; domainId: string }>();
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const domain = useDomainWorkspace(id, domainId, () => setEditing(null));
  const { ws, saveRequirement, verify, complete, upload } = domain;
  const back = `/app/runs/${id}/domains/${domainId}`;

  if (!ws.data) {
    return <div className="grid h-[calc(100vh-4.6rem)] gap-3 p-3 lg:grid-cols-[21rem_1fr]"><Skeleton className="hidden h-full rounded-3xl lg:block" /><Skeleton className="h-full rounded-3xl" /></div>;
  }
  const w = ws.data;
  const reqs = w.requirements;
  const confirmed = reqs.filter((r) => isConfirmed(r.evaluation)).length;
  // Until the person picks one, start at the first requirement that still needs a look.
  const current = reqs.find((r) => r.id === selected) ?? reqs.find((r) => !isConfirmed(r.evaluation)) ?? reqs[0];
  const index = current ? reqs.indexOf(current) : -1;
  const done = allConfirmed(w);
  const e = current?.evaluation ?? null;
  const left = reqs.length - confirmed;

  const go = (step: number) => setSelected(reqs[(index + step + reqs.length) % reqs.length].id);
  const edit = () => { setSelected(current.id); setEditing(current.id); };
  const confirmAndNext = (ev: Evaluation) => verify.mutate(ev, {
    onSuccess: (updated) => setSelected((nextToCheck(updated.requirements, index) ?? current).id),
  });

  return (
    <div className="flex h-[calc(100vh-4.6rem)] flex-col gap-3 p-3">
      <div className="flex items-center gap-4 rounded-3xl bg-card px-4 py-3 sm:px-5">
        <Link href={back} className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground hover:text-foreground" aria-label="Back to the conversation"><ChevronLeft className="size-4" /></Link>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-medium tracking-tight"><span className="font-normal text-muted-foreground">Review · </span>{w.domain.name}</p>
          <div className="flex items-center gap-2"><Bar value={confirmed} max={reqs.length} className="hidden w-24 shrink-0 sm:flex" /><span className="whitespace-nowrap text-xs text-muted-foreground">{confirmed}/{reqs.length} confirmed</span></div>
        </div>
        <span className="hidden sm:inline-flex"><DomainStatusBadge status={w.domain.status} /></span>
        <Button variant="outline" size="sm" asChild className="hidden sm:inline-flex"><Link href={back}><MessagesSquare /> Conversation</Link></Button>
        <CompleteOrReopen w={w} domain={domain} />
      </div>

      {!current ? (
        <div className="flex flex-1 items-center justify-center rounded-3xl bg-card text-sm text-muted-foreground">This domain has no requirements.</div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[21rem_1fr]">
          {/* Phones and tablets: the list becomes a strip of the requirement numbers. */}
          <nav aria-label="Requirements" className="flex gap-1.5 overflow-x-auto rounded-xl bg-card p-1.5 lg:hidden">
            {reqs.map((r) => {
              const s = listStatus(r.evaluation);
              return (
                <button key={r.id} onClick={() => setSelected(r.id)} aria-current={r.id === current.id} aria-label={`${r.key}: ${s.label}`}
                  className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-mono text-xs ${r.id === current.id ? "bg-primary text-primary-foreground [&_svg]:text-current" : "text-muted-foreground"}`}>
                  <span className="flex size-4 items-center justify-center">{s.mark}</span>{r.key}
                </button>
              );
            })}
          </nav>
          <nav aria-label="Requirements" className="hidden min-h-0 flex-col rounded-3xl bg-card lg:flex">
            <div className="px-5 pb-3 pt-5">
              <p className="text-[15px] text-muted-foreground">Requirements</p>
              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                {w.analysis_pending ? <><Loader2 className="size-3 animate-spin" /> Checking other requirements…</>
                  : done ? "All confirmed." : `${left} still to ${w.editable ? "confirm" : "be confirmed"}.`}
              </p>
            </div>
            <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3">
              {reqs.map((r) => {
                const s = listStatus(r.evaluation);
                const active = r.id === current.id;
                return (
                  <button key={r.id} onClick={() => setSelected(r.id)} aria-current={active}
                    className={`flex w-full gap-2.5 rounded-2xl p-3 text-left transition ${active ? "bg-accent ring-2 ring-brand/60" : "hover:bg-muted"}`}>
                    <span className="flex size-4 shrink-0 items-center justify-center pt-1">{s.mark}</span>
                    <span className="min-w-0 flex-1">
                      <span className="line-clamp-2 text-xs leading-relaxed"><span className="font-mono text-muted-foreground">{r.key} </span>{r.statement}</span>
                      <span className="mt-1.5 flex items-center gap-1.5">
                        {r.evaluation && r.evaluation.status !== "awaiting_ai" && <MaturityBadge rating={r.evaluation.rating} na={r.evaluation.is_na} compact />}
                        <span className={`text-[11px] ${s.tone}`}>{s.label}</span>
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </nav>

          <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl bg-card">
            {/* The key resets the scroll position when another requirement is shown. */}
            <div key={current.id} className="min-h-0 flex-1 overflow-y-auto">
              <Detail r={current} w={w} runId={id} position={`Requirement ${index + 1} of ${reqs.length}`} />
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t p-3 sm:px-5">
              <Button variant="ghost" size="icon" onClick={() => go(-1)} disabled={reqs.length < 2} aria-label="Previous requirement"><ArrowLeft /></Button>
              <Button variant="ghost" size="icon" onClick={() => go(1)} disabled={reqs.length < 2} aria-label="Next requirement"><ArrowRight /></Button>
              <span className="mr-auto" />
              {w.editable && (
                <>
                  {e?.status === "awaiting_ai" ? <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> AI is rating this…</span> : (
                    <Button variant={e ? "outline" : "default"} onClick={edit} aria-label={e ? "Change" : undefined}><Pencil />{e ? <span className="hidden sm:inline">Change</span> : "Answer or rate"}</Button>
                  )}
                  {e?.status === "ai_suggested" && (
                    <Button onClick={() => confirmAndNext(e)} disabled={verify.isPending}>
                      {verify.isPending ? <Loader2 className="animate-spin" /> : <Check />} {left > 1 ? "Confirm and next" : "Confirm"}
                    </Button>
                  )}
                  {isConfirmed(e) && (done
                    ? <Button onClick={() => complete.mutate(undefined)} disabled={complete.isPending}><CheckCircle2 /> Complete domain</Button>
                    : <Button onClick={() => setSelected((nextToCheck(reqs, index) ?? current).id)}>Next to check <ArrowRight /></Button>)}
                </>
              )}
            </div>
          </section>
        </div>
      )}

      <RequirementSheet requirement={reqs.find((r) => r.id === editing) ?? null} runId={id} evidence={w.evidence} editable={w.editable} aiPaused={w.ai_paused}
        busy={saveRequirement.isPending || verify.isPending} onClose={() => setEditing(null)}
        onSave={(r, v) => saveRequirement.mutate({ r, v })} onConfirm={(ev) => verify.mutate(ev)} onUpload={upload} />
    </div>
  );
}
