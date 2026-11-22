"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CheckCircle2, CircleAlert, GitBranchPlus, Loader2, MoreHorizontal, Pencil, Plus, Settings2, Tags, Trash2, TriangleAlert } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Field } from "@/components/app/field";
import { ListSkeleton, PageHeader } from "@/components/app/page";
import { VersionBadge } from "@/components/app/status";
import { ControlPicker } from "@/components/library/control-picker";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { AssessmentVersionDetail, BuilderDomain, BuilderQuestion } from "@/lib/types";
import { RichText } from "@/components/runs/rich-text";
import { MandatoryBadge } from "@/components/runs/badges";

type Req = { id: string; code: string; statement: string; mandatory: boolean | null; control: string };
type QuestionDialog = { mode: "add"; domain: BuilderDomain } | { mode: "edit"; question: BuilderQuestion } | null;

function QuestionEditor({ state, onClose, onSave, busy }: {
  state: QuestionDialog; onClose: () => void; onSave: (text: string, help: string) => void; busy: boolean;
}) {
  const q = state?.mode === "edit" ? state.question : null;
  const [text, setText] = useState(q?.text ?? "");
  const [help, setHelp] = useState(q?.help_text ?? "");
  return (
    <Dialog open={!!state} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{q ? "Edit question" : `Add a question to ${state?.mode === "add" ? state.domain.name : ""}`}</DialogTitle>
          <DialogDescription>
            The AI {q ? "re-checks" : "works out"} which requirements this question covers when you save.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field label="Question" htmlFor="qtext"><Textarea id="qtext" rows={4} value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <Field label="Help text" htmlFor="qhelp" hint="What a complete answer covers and what evidence helps.">
            <Textarea id="qhelp" rows={2} value={help} onChange={(e) => setHelp(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onSave(text, help)} disabled={text.trim().length < 5 || busy}>
            {busy && <Loader2 className="animate-spin" />} Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TagEditor({ question, requirements, onClose, onSave, busy }: {
  question: BuilderQuestion | null; requirements: Req[]; onClose: () => void; onSave: (ids: string[]) => void; busy: boolean;
}) {
  const [picked, setPicked] = useState(new Set(question?.requirement_ids ?? []));
  return (
    <Dialog open={!!question} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Requirements covered</DialogTitle>
          <DialogDescription className="line-clamp-2">{question?.text}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[50vh] space-y-1 overflow-y-auto">
          {requirements.map((r) => (
            <label key={r.id} className="flex cursor-pointer gap-3 rounded-lg px-2 py-2 hover:bg-muted/50">
              <Checkbox className="mt-0.5" checked={picked.has(r.id)} onCheckedChange={(v) => setPicked((s) => { const n = new Set(s); if (v) n.add(r.id); else n.delete(r.id); return n; })} />
              <span className="w-16 shrink-0 font-mono text-xs text-muted-foreground">{r.code}</span>
              <span className="min-w-0 flex-1 text-sm">{r.statement}</span>
              <MandatoryBadge value={r.mandatory} />
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onSave([...picked])} disabled={busy}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DetailsEditor({ open, detail, onClose }: { open: boolean; detail: AssessmentVersionDetail; onClose: () => void }) {
  const [title, setTitle] = useState(detail.title);
  const [description, setDescription] = useState(detail.description ?? "");
  const save = useAction(() => api(`/assessments/versions/${detail.id}`, { method: "PUT", body: { title, description: description || null } }), {
    invalidate: [["assessment-version", detail.id], ["assessments"]], success: "Saved", onSuccess: onClose,
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Assessment details</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <Field label="Title" htmlFor="t"><Input id="t" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Description" htmlFor="d"><Textarea id="d" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={title.trim().length < 3 || save.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ControlsEditor({ open, detail, onClose }: { open: boolean; detail: AssessmentVersionDetail; onClose: () => void }) {
  const [picked, setPicked] = useState(new Set(detail.domains.flatMap((d) => d.controls.map((c) => c.control_id))));
  const save = useAction(() => api(`/assessments/versions/${detail.id}/controls`, { method: "PUT", body: { control_ids: [...picked] } }), {
    invalidate: [["assessment-version", detail.id], ["assessments"]], success: "Controls updated. Generate questions for anything new.", onSuccess: onClose,
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Controls in this assessment</DialogTitle>
          <DialogDescription>Removing a control removes its requirements from coverage. Questions in removed domains are deleted.</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto pr-1"><ControlPicker value={picked} onChange={setPicked} /></div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={picked.size === 0 || save.isPending}>Save controls</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const ORIGIN_LABEL: Record<BuilderQuestion["origin"], string> = { ai_generated: "AI", ai_generated_edited: "AI · edited", manual: "Manual" };

export default function BuilderPage() {
  const { versionId } = useParams<{ versionId: string }>();
  const router = useRouter();
  const detail = useQuery({
    queryKey: ["assessment-version", versionId],
    queryFn: () => api<AssessmentVersionDetail>(`/assessments/versions/${versionId}`),
    refetchInterval: (q) => (["pending", "processing"].includes(q.state.data?.generation_status ?? "") ? 2500 : false),
  });
  const [questionDialog, setQuestionDialog] = useState<QuestionDialog>(null);
  const [tagging, setTagging] = useState<BuilderQuestion | null>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const [editingControls, setEditingControls] = useState(false);

  const invalidate = [["assessment-version", versionId], ["assessments"]];
  const setData = (d: AssessmentVersionDetail) => detail.refetch().then(() => d);
  const generate = useAction((mode: "all" | "uncovered") => api(`/assessments/versions/${versionId}/generate`, { body: { mode } }), { invalidate });
  const saveQuestion = useAction(({ text, help }: { text: string; help: string }) => {
    if (questionDialog?.mode === "edit") return api<AssessmentVersionDetail>(`/assessments/questions/${questionDialog.question.id}`, { method: "PUT", body: { text, help_text: help || null } });
    return api<AssessmentVersionDetail>(`/assessments/versions/${versionId}/questions`, { body: { assessment_version_domain_id: (questionDialog as { domain: BuilderDomain }).domain.id, text, help_text: help || null } });
  }, { invalidate, success: "Question saved", onSuccess: () => setQuestionDialog(null) });
  const saveTags = useAction((ids: string[]) => api(`/assessments/questions/${tagging!.id}/requirements`, { method: "PUT", body: { requirement_version_ids: ids } }), {
    invalidate, onSuccess: () => setTagging(null),
  });
  const deleteQuestion = useAction((id: string) => api(`/assessments/questions/${id}`, { method: "DELETE" }), { invalidate, success: "Question removed" });
  const reorder = useAction((body: { domain_ids: string[]; questions: Record<string, string[]> }) =>
    api<AssessmentVersionDetail>(`/assessments/versions/${versionId}/order`, { method: "PUT", body }).then(setData), { invalidate });
  const latestControls = useAction(() => api(`/assessments/versions/${versionId}/use-latest-controls`, { method: "POST" }), {
    invalidate, success: "Now using the latest control versions",
  });
  const publish = useAction(() => api(`/assessments/versions/${versionId}/publish`, { method: "POST" }), { invalidate, success: "Published. Tenants can now start this assessment." });
  const newDraft = useAction(() => api<AssessmentVersionDetail>(`/assessments/${detail.data!.assessment_id}/draft`, { method: "POST" }), {
    invalidate, success: "New draft created with the latest published controls", onSuccess: (d) => router.push(`/admin/assessments/${d.id}`),
  });
  const discard = useAction(() => api(`/assessments/versions/${versionId}`, { method: "DELETE" }), {
    invalidate: [["assessments"]], success: "Draft discarded", onSuccess: () => router.replace("/admin/assessments"),
  });

  const requirements = useMemo(() => {
    const map = new Map<string, Req>();
    detail.data?.domains.forEach((d) => d.controls.forEach((c) => c.requirements.forEach((r) => map.set(r.id, { ...r, control: `${c.code} ${c.title}` }))));
    return map;
  }, [detail.data]);

  if (!detail.data) return <ListSkeleton />;
  const d = detail.data;
  const isDraft = d.status === "draft";
  const generating = ["pending", "processing"].includes(d.generation_status);
  const pct = d.coverage.total ? Math.round((d.coverage.covered / d.coverage.total) * 100) : 0;
  const complete = d.coverage.total > 0 && d.coverage.uncovered.length === 0;
  const questionCount = d.domains.reduce((n, x) => n + x.questions.length, 0);
  const canEdit = isDraft && !generating;

  const orderBody = (domains: BuilderDomain[]) => ({
    domain_ids: domains.map((x) => x.id),
    questions: Object.fromEntries(domains.map((x) => [x.id, x.questions.map((q) => q.id)])),
  });
  const moveDomain = (i: number, dir: -1 | 1) => {
    const next = [...d.domains];
    [next[i], next[i + dir]] = [next[i + dir], next[i]];
    reorder.mutate(orderBody(next));
  };
  const moveQuestion = (di: number, qi: number, dir: -1 | 1) => {
    const next = d.domains.map((x) => ({ ...x, questions: [...x.questions] }));
    const qs = next[di].questions;
    [qs[qi], qs[qi + dir]] = [qs[qi + dir], qs[qi]];
    reorder.mutate(orderBody(next));
  };
  const domainRequirements = (dom: BuilderDomain): Req[] => dom.controls.flatMap((c) => c.requirements.map((r) => requirements.get(r.id)!));

  return (
    <>
      <PageHeader
        back={{ href: "/admin/assessments", label: "Assessments" }}
        title={d.title}
        description={d.description}
        meta={<>
          <VersionBadge status={d.status} version={d.version} />
          {d.published_at && <span className="text-sm text-muted-foreground">Published {formatDate(d.published_at)}</span>}
          <span className="text-sm text-muted-foreground">{d.domains.length} domains · {questionCount} question{questionCount === 1 ? "" : "s"}</span>
        </>}
        actions={isDraft ? (
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="More actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setEditingDetails(true)}><Pencil /> Edit details</DropdownMenuItem>
                <DropdownMenuItem disabled={!canEdit} onClick={() => setEditingControls(true)}><Settings2 /> Change controls</DropdownMenuItem>
                <DropdownMenuItem disabled={!canEdit} onClick={() => generate.mutate("all")}>Regenerate all questions</DropdownMenuItem>
                <DropdownMenuSeparator />
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <DropdownMenuItem variant="destructive" disabled={generating} onSelect={(e) => e.preventDefault()}><Trash2 /> Discard draft</DropdownMenuItem>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Discard this draft?</AlertDialogTitle>
                      <AlertDialogDescription>All questions in this draft will be deleted. Published versions are not affected.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => discard.mutate(undefined)}>Discard</AlertDialogAction></AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </DropdownMenuContent>
            </DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <span><Button onClick={() => publish.mutate(undefined)} disabled={!complete || generating || publish.isPending}>Publish v{d.version}</Button></span>
              </TooltipTrigger>
              {!complete && <TooltipContent>Every requirement needs at least one question first</TooltipContent>}
            </Tooltip>
          </>
        ) : d.status === "published" && !d.other_versions.some((v) => v.status === "draft") ? (
          <Button variant="outline" onClick={() => newDraft.mutate(undefined)} disabled={newDraft.isPending}><GitBranchPlus /> Create new version</Button>
        ) : d.other_versions.find((v) => v.status === "draft") ? (
          <Button variant="outline" onClick={() => router.push(`/admin/assessments/${d.other_versions.find((v) => v.status === "draft")!.id}`)}>Open draft</Button>
        ) : null}
      />

      {generating && (
        <Alert className="mb-6 border-primary/30 bg-accent/50">
          <Loader2 className="animate-spin" />
          <AlertTitle>Writing questions</AlertTitle>
          <AlertDescription>The AI is writing one opening question per domain. During an assessment, the guide follows up on each topic. This usually takes under a minute.</AlertDescription>
        </Alert>
      )}
      {isDraft && d.control_updates.length > 0 && (
        <Alert className="mb-6 border-warning/40 bg-warning/10">
          <CircleAlert />
          <AlertTitle>Newer control versions are available</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              {d.control_updates.map((u) => `${u.current} → ${u.latest}`).join(", ")}.
              Using them keeps question links for requirements that didn&apos;t change; the AI rewrites the question of any domain with new or reworded requirements.
            </p>
            <Button size="sm" onClick={() => latestControls.mutate(undefined)} disabled={!canEdit || latestControls.isPending}>
              {latestControls.isPending && <Loader2 className="animate-spin" />} Use latest versions
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {d.generation_status === "failed" && (
        <Alert variant="destructive" className="mb-6">
          <TriangleAlert />
          <AlertTitle>Question generation failed</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            {d.latest_job?.error ?? "Unknown error"}
            <Button size="sm" variant="outline" onClick={() => generate.mutate(questionCount ? "uncovered" : "all")}>Try again</Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_19rem]">
        <div className="min-w-0 space-y-6">
          {d.domains.map((dom, di) => (
            <section key={dom.id} className="overflow-hidden rounded-3xl bg-card">
              <div className="flex items-center gap-3 border-b bg-muted/40 px-5 py-3">
                <span className="flex size-6 items-center justify-center rounded-md bg-background text-xs font-medium shadow-xs">{di + 1}</span>
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-medium">{dom.name}</h2>
                  <p className="truncate text-xs text-muted-foreground">{dom.controls.map((c) => c.code).join(" · ")}</p>
                </div>
                {canEdit && (
                  <div className="flex">
                    <Button variant="ghost" size="icon-sm" disabled={di === 0} onClick={() => moveDomain(di, -1)} aria-label="Move domain up"><ArrowUp /></Button>
                    <Button variant="ghost" size="icon-sm" disabled={di === d.domains.length - 1} onClick={() => moveDomain(di, 1)} aria-label="Move domain down"><ArrowDown /></Button>
                  </div>
                )}
              </div>
              {generating && dom.questions.length === 0 ? (
                <div className="space-y-2 p-5">{[0, 1, 2].map((i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-muted/60" />)}</div>
              ) : (
                <ol>
                  {dom.questions.map((q, qi) => (
                    <li key={q.id} className="group flex gap-4 border-b px-5 py-4 last:border-0">
                      <span className="w-5 shrink-0 pt-0.5 text-right text-xs text-muted-foreground">{qi + 1}</span>
                      <div className="min-w-0 flex-1 space-y-2">
                        <p className="text-sm leading-relaxed">{q.text}</p>
                        {q.help_text && <div className="text-xs text-muted-foreground"><RichText text={q.help_text} /></div>}
                        <div className="flex flex-wrap items-center gap-1.5">
                          {q.requirement_ids.map((rid) => {
                            const r = requirements.get(rid);
                            return r && (
                              <Tooltip key={rid}>
                                <TooltipTrigger asChild><Badge variant="outline" className="cursor-default font-mono font-normal">{r.code}</Badge></TooltipTrigger>
                                <TooltipContent className="max-w-xs">{r.statement}</TooltipContent>
                              </Tooltip>
                            );
                          })}
                          {q.requirement_ids.length === 0 && <Badge variant="destructive">Covers no requirements</Badge>}
                          <span className="text-xs text-muted-foreground">· {ORIGIN_LABEL[q.origin]}</span>
                        </div>
                      </div>
                      {canEdit && (
                        <div className="flex shrink-0 items-start opacity-70 transition group-hover:opacity-100">
                          <Button variant="ghost" size="icon-sm" disabled={qi === 0} onClick={() => moveQuestion(di, qi, -1)} aria-label="Move up"><ArrowUp /></Button>
                          <Button variant="ghost" size="icon-sm" disabled={qi === dom.questions.length - 1} onClick={() => moveQuestion(di, qi, 1)} aria-label="Move down"><ArrowDown /></Button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Question actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => setQuestionDialog({ mode: "edit", question: q })}><Pencil /> Edit</DropdownMenuItem>
                              <DropdownMenuItem onClick={() => setTagging(q)}><Tags /> Adjust requirements</DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem variant="destructive" onClick={() => deleteQuestion.mutate(q.id)}><Trash2 /> Delete</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              )}
              {canEdit && (
                <button onClick={() => setQuestionDialog({ mode: "add", domain: dom })}
                  className="flex w-full items-center gap-2 border-t px-5 py-3 text-sm text-muted-foreground transition hover:bg-muted/40 hover:text-foreground">
                  <Plus className="size-4" /> Add question
                </button>
              )}
            </section>
          ))}
        </div>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:h-fit">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              {complete ? <CheckCircle2 className="size-4 text-success" /> : <CircleAlert className="size-4 text-warning" />} Requirement coverage
            </CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="mb-2 flex items-baseline justify-between">
                  <span className="text-2xl font-semibold">{d.coverage.covered}<span className="text-base font-normal text-muted-foreground">/{d.coverage.total}</span></span>
                  <span className="text-sm text-muted-foreground">{pct}%</span>
                </div>
                <Progress value={pct} />
              </div>
              {complete ? (
                <p className="text-sm text-muted-foreground">Every requirement is covered by at least one question.{isDraft && " Ready to publish."}</p>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">These requirements aren't covered by a question yet (for example, after controls were added). Publishing is blocked until they are.</p>
                  <ul className="max-h-72 space-y-2 overflow-y-auto">
                    {d.coverage.uncovered.map((id) => {
                      const r = requirements.get(id);
                      return r && (
                        <li key={id} className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2">
                          <p className="font-mono text-xs text-muted-foreground">{r.code}</p>
                          <p className="text-xs">{r.statement}</p>
                        </li>
                      );
                    })}
                  </ul>
                  {canEdit && (
                    <Button className="w-full" variant="outline" onClick={() => generate.mutate("uncovered")} disabled={generate.isPending}>
                      Rewrite affected domain questions
                    </Button>
                  )}
                </>
              )}
            </CardContent>
          </Card>
          {d.other_versions.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-sm">Other versions</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {d.other_versions.map((v) => (
                  <button key={v.id} onClick={() => router.push(`/admin/assessments/${v.id}`)} className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-muted">
                    <VersionBadge status={v.status} version={v.version} />
                    <span className="text-xs text-muted-foreground">{v.question_count} questions</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </aside>
      </div>

      {questionDialog && (
        <QuestionEditor key={questionDialog.mode === "edit" ? questionDialog.question.id : questionDialog.domain.id} state={questionDialog}
          onClose={() => setQuestionDialog(null)} busy={saveQuestion.isPending} onSave={(text, help) => saveQuestion.mutate({ text, help })} />
      )}
      {tagging && (
        <TagEditor key={tagging.id} question={tagging} onClose={() => setTagging(null)} busy={saveTags.isPending} onSave={(ids) => saveTags.mutate(ids)}
          requirements={domainRequirements(d.domains.find((x) => x.questions.some((q) => q.id === tagging.id))!)} />
      )}
      {editingDetails && <DetailsEditor open detail={d} onClose={() => setEditingDetails(false)} />}
      {editingControls && <ControlsEditor open detail={d} onClose={() => setEditingControls(false)} />}
    </>
  );
}
