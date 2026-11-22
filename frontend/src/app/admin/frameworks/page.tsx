"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronRight, FileUp, Loader2, MoreHorizontal, Plus, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { Field } from "@/components/app/field";
import { EmptyState, ListSkeleton, PageHeader } from "@/components/app/page";
import { VersionBadge } from "@/components/app/status";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { Framework } from "@/lib/types";

function NewFrameworkDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [publisher, setPublisher] = useState("");
  const create = useAction(() => api("/frameworks", { body: { code, name, publisher: publisher || null } }), {
    invalidate: [["frameworks"]], success: "Framework added. Upload its document next.", onSuccess: onClose,
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a framework</DialogTitle>
          <DialogDescription>Then upload its source document and the AI will extract the clause structure.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field label="Name" htmlFor="fname"><Input id="fname" placeholder="e.g. SOC 2 Trust Services Criteria" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Code" htmlFor="fcode"><Input id="fcode" placeholder="SOC2" value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ""))} /></Field>
            <Field label="Publisher" htmlFor="fpub"><Input id="fpub" placeholder="AICPA" value={publisher} onChange={(e) => setPublisher(e.target.value)} /></Field>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => create.mutate(undefined)} disabled={code.length < 2 || name.length < 2 || create.isPending}>Add framework</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UploadDialog({ framework, onClose }: { framework: Framework | null; onClose: () => void }) {
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const upload = useAction(() => {
    const form = new FormData();
    form.append("version_label", label);
    form.append("file", file!);
    return api(`/frameworks/${framework!.id}/versions`, { form });
  }, { invalidate: [["frameworks"]], success: "Uploaded. The AI is reading the document.", onSuccess: onClose });

  return (
    <Dialog open={!!framework} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload a version of {framework?.name}</DialogTitle>
          <DialogDescription>PDF, Word, Excel, CSV, Markdown or text. You'll review the extracted clauses before publishing.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field label="Version label" htmlFor="vlabel" hint="As the publisher names it, e.g. 2022 or 2.0">
            <Input id="vlabel" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <button type="button" onClick={() => input.current?.click()}
            className="flex w-full flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-8 text-center transition hover:bg-muted/50">
            <FileUp className="size-6 text-muted-foreground" />
            <span className="text-sm font-medium">{file ? file.name : "Choose a file"}</span>
            <span className="text-xs text-muted-foreground">{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "Up to 30 MB"}</span>
          </button>
          <input ref={input} type="file" hidden accept=".pdf,.docx,.xlsx,.csv,.md,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => upload.mutate(undefined)} disabled={!file || !label || upload.isPending}>
            {upload.isPending && <Loader2 className="animate-spin" />} Upload & parse
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function FrameworksPage() {
  const frameworks = useQuery({
    queryKey: ["frameworks"],
    queryFn: () => api<Framework[]>("/frameworks"),
    refetchInterval: (q) => (q.state.data?.some((f) => f.versions.some((v) => ["pending", "processing"].includes(v.parse_status))) ? 3000 : false),
  });
  const [adding, setAdding] = useState(false);
  const [uploading, setUploading] = useState<Framework | null>(null);
  const [deleting, setDeleting] = useState<Framework | null>(null);
  const remove = useAction((f: Framework) => api(`/frameworks/${f.id}`, { method: "DELETE" }), {
    invalidate: [["frameworks"]], success: "Framework deleted", onSuccess: () => setDeleting(null),
  });

  return (
    <>
      <PageHeader
        title="Frameworks"
        description="Standards and regulations. Requirements in the control library map to their clauses, which powers framework coverage for tenants."
        actions={<Button onClick={() => setAdding(true)}><Plus /> Add framework</Button>}
      />
      {frameworks.isLoading ? <ListSkeleton rows={3} /> : !frameworks.data?.length ? (
        <EmptyState icon={BookOpen} title="No frameworks yet" action={<Button onClick={() => setAdding(true)}><Plus /> Add framework</Button>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {frameworks.data.map((f) => {
            const hasDraft = f.versions.some((v) => v.status === "draft");
            return (
              <Card key={f.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-4">
                  <div className="space-y-1">
                    <CardTitle className="text-base">{f.name}</CardTitle>
                    <CardDescription>{f.publisher ?? "—"} · <span className="font-mono">{f.code}</span></CardDescription>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button variant="outline" size="sm" onClick={() => setUploading(f)} disabled={hasDraft} title={hasDraft ? "Publish or discard the current draft first" : undefined}>
                      <FileUp /> New version
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`${f.name} actions`}><MoreHorizontal /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-64">
                        <DropdownMenuItem variant="destructive" disabled={f.mapped_requirements > 0} onClick={() => setDeleting(f)}>
                          <Trash2 /> Delete framework
                        </DropdownMenuItem>
                        {f.mapped_requirements > 0 && (
                          <p className="px-2 pb-1.5 text-xs text-muted-foreground">
                            {f.mapped_requirements} requirement{f.mapped_requirements !== 1 && "s"} map to its clauses, so it can&apos;t be deleted.
                          </p>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  {f.versions.length === 0 && <p className="text-sm text-muted-foreground">No versions yet. Upload the framework document to get started.</p>}
                  {f.versions.map((v) => (
                    <Link key={v.id} href={`/admin/frameworks/${v.id}`}
                      className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition hover:bg-muted/50">
                      <span className="font-medium">{v.version_label}</span>
                      <VersionBadge status={v.status} />
                      <span className="flex-1 truncate text-xs text-muted-foreground">
                        {["pending", "processing"].includes(v.parse_status) ? (
                          <span className="inline-flex items-center gap-1.5 text-primary"><Loader2 className="size-3 animate-spin" /> AI is extracting clauses…</span>
                        ) : v.parse_status === "failed" ? (
                          <span className="inline-flex items-center gap-1.5 text-destructive"><TriangleAlert className="size-3" /> Parsing failed</span>
                        ) : (
                          <>{v.clause_count} clauses{v.published_at && ` · ${formatDate(v.published_at)}`}</>
                        )}
                      </span>
                      <ChevronRight className="size-4 text-muted-foreground" />
                    </Link>
                  ))}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
      <NewFrameworkDialog open={adding} onClose={() => setAdding(false)} />
      <UploadDialog key={uploading?.id ?? "none"} framework={uploading} onClose={() => setUploading(null)} />
      <AlertDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              All {deleting?.versions.length} version{deleting?.versions.length !== 1 && "s"}, their clauses and uploaded documents will be removed. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={remove.isPending} onClick={(e) => { e.preventDefault(); if (deleting) remove.mutate(deleting); }}>Delete framework</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
