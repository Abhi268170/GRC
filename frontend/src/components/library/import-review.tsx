"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronRight, CircleAlert, Download, Loader2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Panel } from "@/components/app/page";
import { VersionBadge } from "@/components/app/status";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { ControlImport, ImportChoices, ImportControl, ImportControlStatus, ImportIssue } from "@/lib/types";

const STATUS: Record<ImportControlStatus, { label: string; className: string }> = {
  new: { label: "New", className: "border-success/30 bg-success/10 text-success" },
  changed: { label: "Changed", className: "border-primary/30 bg-primary/10 text-primary" },
  conflict: { label: "Has a draft", className: "border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning" },
  unchanged: { label: "Unchanged", className: "border-border bg-muted text-muted-foreground" },
  invalid: { label: "Has errors", className: "border-destructive/30 bg-destructive/10 text-destructive" },
};

function StatusBadge({ status }: { status: ImportControlStatus }) {
  return <Badge variant="outline" className={STATUS[status].className}>{STATUS[status].label}</Badge>;
}

export function ImportStatusBadge({ status }: { status: ControlImport["status"] }) {
  const style = status === "applied" ? "border-success/30 bg-success/10 text-success"
    : status === "preview" ? "border-primary/30 bg-primary/10 text-primary" : "border-border bg-muted text-muted-foreground";
  const label = status === "applied" ? "Imported" : status === "preview" ? "Awaiting review" : "Expired";
  return <Badge variant="outline" className={style}>{label}</Badge>;
}

function Counts({ imp }: { imp: ControlImport }) {
  const s = imp.summary;
  const items: [string, number, string][] = [
    ["New", s.new, "text-success"], ["Changed", s.changed, "text-primary"], ["Have a draft", s.conflicts, "text-warning-foreground dark:text-warning"],
    ["Unchanged", s.unchanged, "text-muted-foreground"], ["Errors", s.errors, "text-destructive"], ["Warnings", s.warnings, "text-warning-foreground dark:text-warning"],
  ];
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
      {items.map(([label, n, color]) => (
        <div key={label} className="rounded-2xl bg-card px-4 py-3">
          <p className={`display text-3xl leading-none ${n ? color : "text-muted-foreground/50"}`}>{n}</p>
          <p className="mt-1.5 text-xs text-muted-foreground">{label}</p>
        </div>
      ))}
    </div>
  );
}

function where(i: ImportIssue) {
  if (!i.sheet) return "File";
  return [i.sheet, i.row && `row ${i.row}`, i.column].filter(Boolean).join(" · ");
}

function Issues({ issues, importId }: { issues: ImportIssue[]; importId: string }) {
  const errors = issues.filter((i) => i.level === "error");
  const [tab, setTab] = useState<"error" | "warning">(errors.length ? "error" : "warning");
  if (!issues.length) return null;
  const shown = issues.filter((i) => i.level === tab);
  const fileLevel = issues.length === 1 && !issues[0].sheet;
  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
        <div className="flex gap-1">
          {(["error", "warning"] as const).map((level) => {
            const n = issues.filter((i) => i.level === level).length;
            return (
              <button key={level} type="button" onClick={() => setTab(level)} disabled={!n}
                className={`rounded-lg px-3 py-1.5 text-sm transition disabled:opacity-40 ${tab === level ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground"}`}>
                {level === "error" ? "Errors" : "Warnings"} <span className="ml-1 text-xs text-muted-foreground">{n}</span>
              </button>
            );
          })}
        </div>
        {!fileLevel && (
          <Button variant="outline" size="sm" asChild>
            <a href={`/api/library/imports/${importId}/issues.xlsx`}><Download /> File with problems marked</a>
          </Button>
        )}
      </div>
      <ul className="max-h-[26rem] divide-y overflow-y-auto">
        {shown.map((i, n) => (
          <li key={n} className="flex gap-3 px-5 py-3 text-sm">
            {i.level === "error" ? <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" /> : <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-foreground dark:text-warning" />}
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">{where(i)}{i.value && <> · <span className="font-mono text-foreground/80">{i.value}</span></>}</p>
              <p className="mt-0.5">{i.message}</p>
              {i.suggestion && <p className="mt-1 text-xs text-muted-foreground">Did you mean <span className="font-medium text-foreground">{i.suggestion}</span>?</p>}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Change({ field, before, after }: { field: string; before: string; after: string }) {
  return (
    <div className="grid gap-1 text-xs sm:grid-cols-[10rem_1fr]">
      <p className="font-medium">{field}</p>
      <div className="grid gap-1 sm:grid-cols-2">
        <p className="whitespace-pre-line rounded-lg bg-destructive/5 px-2.5 py-1.5 text-muted-foreground line-through decoration-destructive/40">{before || "—"}</p>
        <p className="whitespace-pre-line rounded-lg bg-success/10 px-2.5 py-1.5">{after || "—"}</p>
      </div>
    </div>
  );
}

function ControlCard({ c, choices, editable, onChoose, onTick }: {
  c: ImportControl; choices: ImportChoices; editable: boolean;
  onChoose: (code: string, choice: "overwrite" | "skip") => void; onTick: (code: string, on: boolean) => void;
}) {
  const needsAttention = (c.status === "conflict" && !choices.conflicts[c.code!]) ||
    c.removals.some((r) => !choices.removals.includes(r.code));
  const [open, setOpen] = useState(needsAttention);
  const skipped = c.status === "conflict" && choices.conflicts[c.code!] === "skip";
  const reqChanges = c.requirements.filter((r) => r.status !== "unchanged");
  const bits = c.status === "new"
    ? [`${c.requirements.length} requirement${c.requirements.length === 1 ? "" : "s"}`]
    : [c.fields.length && `${c.fields.length} field${c.fields.length === 1 ? "" : "s"}`,
      reqChanges.length && `${reqChanges.length} requirement change${reqChanges.length === 1 ? "" : "s"}`,
      c.removals.length && `${c.removals.length} removal${c.removals.length === 1 ? "" : "s"}`].filter(Boolean);
  const code = c.code ?? c.expected_code;

  return (
    <div className={`rounded-3xl bg-card transition-opacity ${skipped ? "opacity-60" : ""}`}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-3 px-5 py-4 text-left">
        <ChevronRight className={`size-4 shrink-0 text-muted-foreground transition-transform duration-300 ease-smooth ${open ? "rotate-90" : ""}`} />
        <span className="w-16 shrink-0 font-mono text-xs text-muted-foreground" title={c.status === "new" ? "Expected code: assigned when imported" : undefined}>
          {code}{c.status === "new" && "*"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">{c.title || <span className="text-muted-foreground">Row {c.row}</span>}</span>
          <span className="block truncate text-xs text-muted-foreground">{c.domain}{bits.length > 0 && ` · ${bits.join(" · ")}`}{skipped && " · skipped"}</span>
        </span>
        {needsAttention && editable && <span className="size-2 shrink-0 rounded-full bg-warning" aria-label="Needs a decision" />}
        <StatusBadge status={c.status} />
      </button>
      <div className={`grid transition-[grid-template-rows] duration-300 ease-smooth ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
        <div className="min-h-0 overflow-hidden" inert={!open}>
          <div className="space-y-5 border-t px-5 py-4">
            {c.status === "conflict" && (
              <div className="rounded-2xl bg-warning/10 p-4">
                <p className="text-sm font-medium">{c.code} already has a draft ({c.base})</p>
                <p className="mt-0.5 text-xs text-muted-foreground">The changes below are compared with that draft. Overwrite it with the file, or skip this control.</p>
                <div className="mt-3 flex gap-2">
                  {(["overwrite", "skip"] as const).map((choice) => (
                    <Button key={choice} size="sm" variant={choices.conflicts[c.code!] === choice ? "default" : "outline"} disabled={!editable}
                      onClick={() => onChoose(c.code!, choice)} aria-pressed={choices.conflicts[c.code!] === choice}>
                      {choices.conflicts[c.code!] === choice && <Check />} {choice === "overwrite" ? "Overwrite draft" : "Skip"}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            {c.status === "invalid" && <p className="text-sm text-destructive">Fix this control&apos;s errors (listed above) to see its changes.</p>}
            {c.base && c.status === "changed" && <p className="text-xs text-muted-foreground">Compared with {c.base}. Importing creates the next version as a draft.</p>}
            {c.status === "new" && <p className="text-xs text-muted-foreground">Created as a draft. *The code is assigned when imported; {c.expected_code} is expected.</p>}

            {c.status !== "new" && c.fields.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Control fields</p>
                {c.fields.map((f) => <Change key={f.field} {...f} />)}
              </div>
            )}

            {(c.status === "new" ? c.requirements.length > 0 : reqChanges.length > 0) && (
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Requirements</p>
                {(c.status === "new" ? c.requirements : reqChanges).map((r, i) => (
                  <div key={i} className="rounded-2xl border px-4 py-3">
                    <p className="flex items-baseline gap-2 text-sm">
                      <span className="shrink-0 font-mono text-xs text-muted-foreground">{r.code ?? `#${r.position}`}</span>
                      <span className="flex-1">{r.statement}</span>
                      {c.status !== "new" && <span className="shrink-0 text-xs text-muted-foreground">
                        {r.status === "added" ? "New" : r.status === "moved" ? `Moved from #${r.moved_from}` : "Edited"}
                      </span>}
                    </p>
                    {r.changes.length > 0 && <div className="mt-3 space-y-2">{r.changes.map((f) => <Change key={f.field} {...f} />)}</div>}
                  </div>
                ))}
              </div>
            )}

            {c.removals.length > 0 && !skipped && (
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Not in the file: removed from the next version</p>
                {c.removals.map((r) => (
                  <label key={r.code} className="flex cursor-pointer items-start gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
                    <Checkbox className="mt-0.5" checked={choices.removals.includes(r.code)} disabled={!editable}
                      onCheckedChange={(v) => onTick(r.code, v === true)} />
                    <span><span className="font-mono text-xs text-muted-foreground">{r.code}</span> {r.statement}
                      <span className="mt-0.5 block text-xs text-muted-foreground">Tick to confirm the removal. Older versions keep it.</span></span>
                  </label>
                ))}
              </div>
            )}

            {c.publish_missing.length > 0 && (
              <p className="text-xs text-muted-foreground"><TriangleAlert className="mr-1 inline size-3.5 text-warning-foreground dark:text-warning" />
                Can&apos;t be published until filled in: {c.publish_missing.join(", ")}.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ImportReview({ imp, onUploadAgain }: { imp: ControlImport; onUploadAgain: () => void }) {
  const qc = useQueryClient();
  const editable = imp.status === "preview";
  const choices: ImportChoices = { conflicts: imp.choices.conflicts ?? {}, removals: imp.choices.removals ?? [] };
  const save = useAction((next: ImportChoices) => api<ControlImport>(`/library/imports/${imp.id}/choices`, { method: "PUT", body: next }), {
    onSuccess: (out) => qc.setQueryData(["control-import", imp.id], out),
  });
  const apply = useAction(() => api<ControlImport>(`/library/imports/${imp.id}/apply`, { method: "POST" }), {
    invalidate: [["controls"], ["domains"], ["control-imports"]], success: "Imported",
    onSuccess: (out) => qc.setQueryData(["control-import", imp.id], out),
  });
  const discard = useAction(() => api(`/library/imports/${imp.id}`, { method: "DELETE" }), {
    invalidate: [["control-imports"]], onSuccess: onUploadAgain,
  });
  const choose = (code: string, c: "overwrite" | "skip") => save.mutate({ ...choices, conflicts: { ...choices.conflicts, [code]: c } });
  const tick = (code: string, on: boolean) => save.mutate({
    ...choices, removals: on ? [...choices.removals, code] : choices.removals.filter((x) => x !== code),
  });

  const controls = imp.report.controls ?? [];
  const listed = controls.filter((c) => c.status !== "unchanged");
  const unchanged = controls.length - listed.length;
  const toImport = controls.filter((c) => c.status === "new" || c.status === "changed" || (c.status === "conflict" && choices.conflicts[c.code!] === "overwrite")).length;

  return (
    <div className="space-y-6 pb-28">
      <Counts imp={imp} />
      {imp.status === "expired" && (
        <Panel className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
          <span>This preview expired or was replaced by a newer upload, so it can&apos;t be imported.</span>
          <Button size="sm" onClick={onUploadAgain}>Upload again</Button>
        </Panel>
      )}
      <Issues issues={imp.report.issues ?? []} importId={imp.id} />
      {listed.length > 0 && (
        <div className="space-y-2">
          {listed.map((c) => <ControlCard key={c.ref + c.row} c={c} choices={choices} editable={editable} onChoose={choose} onTick={tick} />)}
        </div>
      )}
      {unchanged > 0 && <p className="px-1 text-sm text-muted-foreground">{unchanged} control{unchanged === 1 ? " matches" : "s match"} the library and will be skipped.</p>}

      {editable && (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t bg-background/90 backdrop-blur-md">
          <div className="mx-auto flex max-w-[87.5rem] flex-wrap items-center gap-3 px-4 py-3 lg:px-8">
            <div className="min-w-0 flex-1 text-sm">
              {imp.blockers.length ? (
                <ul className="space-y-0.5">{imp.blockers.map((b) => <li key={b} className="flex items-center gap-2"><CircleAlert className="size-4 shrink-0 text-destructive" /> {b}</li>)}</ul>
              ) : (
                <p className="flex items-center gap-2"><Check className="size-4 text-success" /> Ready: {toImport} control{toImport === 1 ? "" : "s"} will be saved as drafts. Nothing is published yet.</p>
              )}
            </div>
            <Button variant="ghost" onClick={() => discard.mutate(undefined)} disabled={discard.isPending}>Cancel import</Button>
            {imp.summary.errors > 0 && <Button variant="outline" onClick={onUploadAgain}>Upload a fixed file</Button>}
            <Button onClick={() => apply.mutate(undefined)} disabled={imp.blockers.length > 0 || apply.isPending || save.isPending}>
              {apply.isPending && <Loader2 className="animate-spin" />} Import {toImport || ""} control{toImport === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ImportDone({ imp }: { imp: ControlImport }) {
  const qc = useQueryClient();
  const [result, setResult] = useState<{ published: string[]; not_published: { code: string; reasons: string[] }[] } | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["control-import", imp.id] });
  const publish = useAction(() => api<{ published: string[]; not_published: { code: string; reasons: string[] }[] }>(`/library/imports/${imp.id}/publish`, { method: "POST" }), {
    invalidate: [["controls"]], onSuccess: (r) => { setResult(r); refresh(); },
  });
  const discard = useAction(() => api(`/library/imports/${imp.id}/drafts`, { method: "DELETE" }), {
    invalidate: [["controls"], ["domains"]], success: "Drafts discarded", onSuccess: () => { setConfirmDiscard(false); refresh(); },
  });
  const drafts = imp.drafts.filter((d) => d.status === "draft");

  return (
    <div className="space-y-6">
      <Panel className="p-6">
        <p className="flex items-center gap-2 text-lg"><Check className="size-5 text-success" /> Imported {imp.applied_at && <span className="text-sm text-muted-foreground">on {formatDate(imp.applied_at)}</span>}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {imp.summary.created ?? 0} new control{imp.summary.created === 1 ? "" : "s"} and {imp.summary.updated ?? 0} updated control{imp.summary.updated === 1 ? "" : "s"} were saved as drafts.
          Publish them to make them available to assessments.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button onClick={() => publish.mutate(undefined)} disabled={!drafts.length || publish.isPending}>
            {publish.isPending && <Loader2 className="animate-spin" />} Publish all ready drafts
          </Button>
          <Button variant="outline" onClick={() => setConfirmDiscard(true)} disabled={!drafts.length}>Discard drafts from this import</Button>
          <Button variant="ghost" asChild><Link href="/admin/library">Go to the library <ArrowRight /></Link></Button>
        </div>
        {result && (
          <div className="mt-5 space-y-2 text-sm">
            {result.published.length > 0 && <p className="flex items-center gap-2"><Check className="size-4 text-success" /> Published {result.published.join(", ")}</p>}
            {result.not_published.map((n) => (
              <p key={n.code} className="flex items-start gap-2"><CircleAlert className="mt-0.5 size-4 shrink-0 text-warning-foreground dark:text-warning" />
                <span><span className="font-mono">{n.code}</span> not published: {n.reasons.join("; ")}.</span></p>
            ))}
          </div>
        )}
      </Panel>
      {imp.drafts.length > 0 && (
        <div className="overflow-hidden rounded-3xl bg-card">
          {imp.drafts.map((d) => (
            <Link key={d.control_id + d.version_code} href={`/admin/library/controls/${d.control_id}`}
              className="flex items-center gap-4 border-b px-5 py-3.5 text-sm transition last:border-0 hover:bg-muted/50">
              <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground">{d.version_code}</span>
              <span className="min-w-0 flex-1 truncate">{d.title}</span>
              <VersionBadge status={d.status} />
              <ChevronRight className="size-4 text-muted-foreground" />
            </Link>
          ))}
        </div>
      )}
      <AlertDialog open={confirmDiscard} onOpenChange={setConfirmDiscard}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard {drafts.length} draft{drafts.length === 1 ? "" : "s"}?</AlertDialogTitle>
            <AlertDialogDescription>Unpublished drafts from this import are removed. New controls that were never published disappear entirely; published versions stay as they are.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={discard.isPending} onClick={(e) => { e.preventDefault(); discard.mutate(undefined); }}>Discard drafts</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
