"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, History, Pencil } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { ListSkeleton, PageHeader } from "@/components/app/page";
import { MandatoryBadge } from "@/components/runs/badges";
import { FrameworkBadge, VersionBadge } from "@/components/app/status";
import { ControlEditor, type ControlDraft, draftFrom, isValid, missingForPublish, toPayload } from "@/components/library/control-editor";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { CONTROL_MULTI_FIELDS, CONTROL_TEXT_FIELDS } from "@/lib/types";
import type { ControlDetail, ControlVersion, Domain, Option, Requirement } from "@/lib/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[11rem_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

const Chips = ({ items }: { items: Option[] }) =>
  items.length ? (
    <span className="flex flex-wrap gap-1.5">{items.map((o) => <span key={o.id} className="rounded-md bg-muted px-2.5 py-0.5 text-xs">{o.label}</span>)}</span>
  ) : <span className="text-muted-foreground">Not set</span>;

/** Collapsed: code, statement, badge and a summary. Expanded: guidance, evidence, templates and clauses. */
function RequirementCard({ r, n }: { r: Requirement; n: number }) {
  const [open, setOpen] = useState(false);
  const bits = [`${r.evidence.length} evidence line${r.evidence.length === 1 ? "" : "s"}`,
    `${r.action_templates.length + r.risk_templates.length} template${r.action_templates.length + r.risk_templates.length === 1 ? "" : "s"}`,
    `${r.clauses.length} clause${r.clauses.length === 1 ? "" : "s"}`];
  return (
    <div className="rounded-3xl bg-card">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-3 px-5 py-4 text-left">
        <ChevronRight className={`size-4 shrink-0 text-muted-foreground transition-transform duration-300 ease-smooth ${open ? "rotate-90" : ""}`} />
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-medium">{n}</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="shrink-0 font-mono text-xs text-muted-foreground">{r.code}</span>
            <span className={`text-sm ${open ? "" : "truncate"}`}>{r.statement}</span>
          </span>
          {!open && <span className="mt-0.5 block text-xs text-muted-foreground">{bits.join(" · ")}</span>}
        </span>
        <MandatoryBadge value={r.mandatory} />
      </button>
      <div className={`grid transition-[grid-template-rows] duration-300 ease-smooth ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
        <div className="min-h-0 overflow-hidden" inert={!open}>
          <div className="space-y-3 border-t px-5 py-4 pl-[4.75rem]">
            <p className="text-xs"><span className="font-medium">How to meet it:</span> <span className="text-muted-foreground">{r.guidance}</span></p>
            {r.evidence.length > 0 && (
              <div className="text-xs">
                <p className="font-medium">Evidence</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">{r.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
              </div>
            )}
            {(r.action_templates.length > 0 || r.risk_templates.length > 0) && (
              <div className="grid gap-3 text-xs sm:grid-cols-2">
                {([["Action item templates", r.action_templates], ["Risk templates", r.risk_templates]] as const).map(([label, ts]) => ts.length > 0 && (
                  <div key={label}>
                    <p className="font-medium">{label}</p>
                    <ul className="mt-1 space-y-1">
                      {ts.map((t, i) => <li key={i}><span>{t.title}</span><span className="text-muted-foreground"> · {t.description}</span></li>)}
                    </ul>
                  </div>
                ))}
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {r.clauses.map((c) => (
                <span key={c.id} title={c.title} className="inline-flex items-center gap-1 rounded-md border bg-muted/50 py-0.5 pl-1 pr-2 text-xs">
                  <FrameworkBadge code={c.framework_code} /><span className="font-mono">{c.ref}</span>
                </span>
              ))}
              {r.clauses.length === 0 && <span className="text-xs text-muted-foreground">Not mapped to a framework</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReadView({ cv, domainName }: { cv: ControlVersion; domainName: string }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardContent>
          <dl className="divide-y">
            <Row label="Domain">{domainName}</Row>
            <Row label="Area">{cv.area?.label ?? <span className="text-muted-foreground">Not set</span>}</Row>
            <Row label="Organisational role">{cv.responsible_role ? `${cv.responsible_role.name} (${cv.responsible_role.abbreviation})` : <span className="text-muted-foreground">Not set</span>}</Row>
            <Row label="Company risk exposure">{cv.company_risk_exposure?.label ?? <span className="text-muted-foreground">Not set</span>}</Row>
            {CONTROL_MULTI_FIELDS.map(([f, , label]) => <Row key={f} label={label}><Chips items={cv[f]} /></Row>)}
          </dl>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <dl className="divide-y">
            {CONTROL_TEXT_FIELDS.map(([f, label]) => (
              <Row key={f} label={label}>{cv[f] ? <span className="whitespace-pre-line">{cv[f]}</span> : <span className="text-muted-foreground">Not set</span>}</Row>
            ))}
          </dl>
        </CardContent>
      </Card>
      <h2 className="pt-2 font-medium">Requirements</h2>
      <div className="space-y-2">
        {cv.requirements.map((r, i) => <RequirementCard key={r.requirement_id} r={r} n={i + 1} />)}
      </div>
    </div>
  );
}

function DraftEditor({ control, domains, onDirty }: { control: ControlDetail; domains: Domain[]; onDirty: (d: ControlDraft | null) => void }) {
  const [draft, setDraft] = useState<ControlDraft>(() => draftFrom(control.draft));
  return <ControlEditor value={draft} onChange={(d) => { setDraft(d); onDirty(d); }} domains={domains} domainLocked={control.domain_locked} code={control.code} />;
}

export default function ControlPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const control = useQuery({ queryKey: ["control", id], queryFn: () => api<ControlDetail>(`/library/controls/${id}`) });
  const domains = useQuery({ queryKey: ["domains"], queryFn: () => api<Domain[]>("/library/domains") });
  // Unsaved edits; null means the editor shows the saved draft.
  const [edits, setEdits] = useState<ControlDraft | null>(null);
  const dirty = edits !== null;
  const current = (): ControlDraft => edits ?? draftFrom(control.data!.draft);

  const invalidate = [["control", id], ["controls"], ["domains"]];
  const startDraft = useAction(() => api(`/library/controls/${id}/draft`, { method: "POST" }), { invalidate, success: "Draft created from the published version" });
  const save = useAction(() => api(`/library/controls/${id}/draft`, { method: "PUT", body: toPayload(current()) }), {
    invalidate, success: "Draft saved", onSuccess: () => setEdits(null),
  });
  const publish = useAction(async () => {
    if (dirty) await api(`/library/controls/${id}/draft`, { method: "PUT", body: toPayload(current()) });
    return api(`/library/controls/${id}/publish`, { method: "POST" });
  }, { invalidate, success: "Published. New assessments will use this version.", onSuccess: () => setEdits(null) });
  const discard = useAction(() => api(`/library/controls/${id}/draft`, { method: "DELETE" }), {
    invalidate, success: "Draft discarded",
    onSuccess: () => { setEdits(null); if (!control.data?.published) router.replace("/admin/library"); },
  });

  if (!control.data) return <ListSkeleton />;
  const c = control.data;
  const shown = c.draft ?? c.published!;
  const valid = c.draft ? isValid(current()) : false;
  const missing = c.draft ? missingForPublish(current()) : [];
  const domainName = (id: string) => { const d = domains.data?.find((x) => x.id === id); return d ? (d.published ?? d.draft)!.name : ""; };
  return (
    <>
      <PageHeader
        back={{ href: "/admin/library", label: "Control library" }}
        title={<span className="flex items-center gap-3"><span className="font-mono text-lg text-muted-foreground">{shown.version_code}</span>{shown.title}</span>}
        meta={<>
          {c.published && <VersionBadge status="published" version={c.published.version} />}
          {c.draft && <VersionBadge status="draft" version={c.draft.version} />}
        </>}
        actions={c.draft ? (
          <>
            <AlertDialog>
              <AlertDialogTrigger asChild><Button variant="ghost">Discard draft</Button></AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Discard this draft?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {c.published ? "The published version stays live and unchanged." : "This control has never been published, so it will be deleted."}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep editing</AlertDialogCancel>
                  <AlertDialogAction onClick={() => discard.mutate(undefined)}>Discard</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <Button variant="outline" onClick={() => save.mutate(undefined)} disabled={!dirty || !valid || save.isPending}>Save draft</Button>
            <Button onClick={() => publish.mutate(undefined)} disabled={!valid || missing.length > 0 || publish.isPending}>Publish {c.draft.version_code}</Button>
          </>
        ) : (
          <Button onClick={() => startDraft.mutate(undefined)} disabled={startDraft.isPending}><Pencil /> Edit</Button>
        )}
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_17rem]">
        <div className="min-w-0">
          {c.draft ? (
            <DraftEditor key={c.draft.id} control={c} domains={domains.data ?? []} onDirty={setEdits} />
          ) : (
            <ReadView cv={c.published!} domainName={domainName(c.published!.domain_id)} />
          )}
        </div>
        <div className="space-y-4 lg:sticky lg:top-24 lg:h-fit">
        {c.draft && (
          <Card className="h-fit">
            <CardHeader><CardTitle className="text-sm">{missing.length ? "Before publishing" : "Ready to publish"}</CardTitle></CardHeader>
            <CardContent>
              {missing.length ? (
                <ul className="space-y-1.5 text-sm">
                  {missing.map((m) => <li key={m} className="flex items-center gap-2"><span className="size-1.5 rounded-full bg-muted-foreground/50" />{m}</li>)}
                </ul>
              ) : <p className="text-sm text-muted-foreground">Everything required is filled in.</p>}
            </CardContent>
          </Card>
        )}
        <Card className="h-fit">
          <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><History className="size-4" /> Version history</CardTitle></CardHeader>
          <CardContent>
            <ol className="space-y-3">
              {c.versions.map((v) => (
                <li key={v.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2"><span className="font-mono text-xs">{v.version_code}</span><VersionBadge status={v.status} /></span>
                  <span className="text-xs text-muted-foreground">{v.published_at ? formatDate(v.published_at) : "unpublished"}</span>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-xs text-muted-foreground">Published versions never change. Assessments keep using the version they were built with.</p>
          </CardContent>
        </Card>
        </div>
      </div>
    </>
  );
}
