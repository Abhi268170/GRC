"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Download, FileSpreadsheet, FileUp, Loader2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";

import { ListSkeleton, PageHeader, Panel } from "@/components/app/page";
import { ImportDone, ImportReview, ImportStatusBadge } from "@/components/library/import-review";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { ControlImport, ControlImportListItem } from "@/lib/types";

function Upload({ onDone }: { onDone: (id: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const upload = useAction((file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<ControlImport>("/library/imports", { form });
  }, { invalidate: [["control-imports"]], onSuccess: (imp) => onDone(imp.id) });
  const pick = (file: File | undefined) => file && upload.mutate(file);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <button type="button" onClick={() => input.current?.click()} disabled={upload.isPending}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}
        className={`flex min-h-64 flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed bg-card px-6 py-12 text-center transition ${dragging ? "border-brand bg-brand/5" : "border-border hover:bg-muted/40"}`}>
        {upload.isPending ? <Loader2 className="size-7 animate-spin text-muted-foreground" /> : <FileUp className="size-7 text-muted-foreground" />}
        <span className="text-base font-medium">{upload.isPending ? "Checking the file…" : "Drop the workbook here, or choose a file"}</span>
        <span className="max-w-md text-sm text-muted-foreground">You&apos;ll see every change before anything is saved. Up to 10 MB and 1,000 controls.</span>
      </button>
      <input ref={input} type="file" hidden accept=".xlsx" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      <Panel className="space-y-4 p-6 text-sm">
        <p className="font-medium">Start from a workbook</p>
        <div className="space-y-2">
          <Button variant="outline" className="w-full justify-start" asChild><a href="/api/library/export"><Download /> Export the library</a></Button>
          <Button variant="outline" className="w-full justify-start" asChild><a href="/api/library/import-template"><FileSpreadsheet /> Empty template</a></Button>
        </div>
        <ul className="list-disc space-y-1.5 pl-4 text-muted-foreground">
          <li>Edit an export and import it again to update controls. Each changed control gets a new draft version.</li>
          <li>Leave the code blank to add a new control.</li>
          <li>Controls not in the file are left alone.</li>
          <li>Any error stops the whole import, so nothing is half done.</li>
        </ul>
      </Panel>
    </div>
  );
}

function History({ onOpen }: { onOpen: (id: string) => void }) {
  const list = useQuery({ queryKey: ["control-imports"], queryFn: () => api<ControlImportListItem[]>("/library/imports") });
  if (list.isLoading) return <ListSkeleton rows={2} />;
  if (!list.data?.length) return null;
  return (
    <section className="space-y-3">
      <h2 className="px-1 text-sm text-muted-foreground">Earlier imports</h2>
      <div className="overflow-hidden rounded-3xl bg-card">
        {list.data.map((i) => (
          <button key={i.id} type="button" onClick={() => onOpen(i.id)}
            className="flex w-full items-center gap-4 border-b px-5 py-3.5 text-left text-sm transition last:border-0 hover:bg-muted/50">
            <FileSpreadsheet className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              <span className="block truncate">{i.filename}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {formatDate(i.created_at)} · {i.created_by}
                {i.status === "applied" ? ` · ${i.summary.created ?? 0} new, ${i.summary.updated ?? 0} updated`
                  : i.summary.errors ? ` · ${i.summary.errors} error${i.summary.errors === 1 ? "" : "s"}` : ""}
              </span>
            </span>
            <ImportStatusBadge status={i.status} />
            <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
          </button>
        ))}
      </div>
    </section>
  );
}

function ImportPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const id = params.get("id");
  const open = (next: string | null) => router.replace(next ? `${pathname}?id=${next}` : pathname, { scroll: false });
  const imp = useQuery({ queryKey: ["control-import", id], queryFn: () => api<ControlImport>(`/library/imports/${id}`), enabled: !!id });

  return (
    <>
      <PageHeader
        back={{ href: "/admin/library", label: "Control library" }}
        title="Import controls"
        description="Add or update controls from the Excel workbook. Imported controls are saved as drafts for you to review and publish."
        meta={imp.data && <><span className="text-sm text-muted-foreground">{imp.data.filename}</span><ImportStatusBadge status={imp.data.status} /></>}
      />
      {!id ? (
        <div className="space-y-8">
          <Upload onDone={(next) => { qc.removeQueries({ queryKey: ["control-import", next] }); open(next); }} />
          <History onOpen={open} />
        </div>
      ) : imp.isLoading ? <ListSkeleton rows={4} /> : imp.data ? (
        imp.data.status === "applied" ? <ImportDone imp={imp.data} /> : <ImportReview imp={imp.data} onUploadAgain={() => open(null)} />
      ) : (
        <Panel className="p-6 text-sm">This import couldn&apos;t be found. <Button variant="link" className="px-1" onClick={() => open(null)}>Start a new one</Button></Panel>
      )}
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<ListSkeleton />}><ImportPage /></Suspense>;
}
