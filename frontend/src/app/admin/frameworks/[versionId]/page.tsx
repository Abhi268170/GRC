"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Loader2, RefreshCw, Search, Trash2, TriangleAlert } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { ListSkeleton, PageHeader } from "@/components/app/page";
import { VersionBadge } from "@/components/app/status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { Clause, FrameworkVersionDetail } from "@/lib/types";

type EditableClause = Clause & { parent_ref: string | null };

export default function FrameworkVersionPage() {
  const { versionId } = useParams<{ versionId: string }>();
  const router = useRouter();
  const detail = useQuery({
    queryKey: ["framework-version", versionId],
    queryFn: () => api<FrameworkVersionDetail>(`/frameworks/versions/${versionId}`),
    refetchInterval: (q) => (["pending", "processing"].includes(q.state.data?.version.parse_status ?? "") ? 3000 : false),
  });
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const invalidate = [["framework-version", versionId], ["frameworks"]];
  const saveClauses = useAction((clauses: EditableClause[]) => api(`/frameworks/versions/${versionId}/clauses`, {
    method: "PUT",
    body: clauses.map((c) => ({ ref: c.ref, title: c.title, description: c.description, parent_ref: c.parent_ref, is_assessable: c.is_assessable })),
  }), { invalidate });
  const publish = useAction(() => api(`/frameworks/versions/${versionId}/publish`, { method: "POST" }), { invalidate, success: "Framework version published" });
  const reparse = useAction(() => api(`/frameworks/versions/${versionId}/reparse`, { method: "POST" }), { invalidate, success: "Parsing again" });
  const discard = useAction(() => api(`/frameworks/versions/${versionId}`, { method: "DELETE" }), {
    invalidate: [["frameworks"]], success: detail.data?.version.status === "draft" ? "Draft discarded" : "Version deleted", onSuccess: () => router.replace("/admin/frameworks"),
  });

  const clauses: EditableClause[] = useMemo(() => {
    const byId = new Map(detail.data?.clauses.map((c) => [c.id, c]));
    return (detail.data?.clauses ?? []).map((c) => ({ ...c, parent_ref: c.parent_id ? byId.get(c.parent_id)?.ref ?? null : null }));
  }, [detail.data]);

  const visible = useMemo(() => {
    if (query) {
      const q = query.toLowerCase();
      return clauses.filter((c) => c.ref.toLowerCase().includes(q) || c.title.toLowerCase().includes(q));
    }
    const hidden = new Set<string>();
    return clauses.filter((c) => {
      if (c.parent_id && (hidden.has(c.parent_id) || collapsed.has(c.parent_id))) { hidden.add(c.id); return false; }
      return true;
    });
  }, [clauses, query, collapsed]);

  if (!detail.data) return <ListSkeleton />;
  const { framework, version } = detail.data;
  const isDraft = version.status === "draft";
  const parsing = ["pending", "processing"].includes(version.parse_status);
  const hasChildren = new Set(clauses.map((c) => c.parent_id).filter(Boolean));
  const assessable = clauses.filter((c) => c.is_assessable).length;

  const update = (id: string, patch: Partial<EditableClause>) => saveClauses.mutate(clauses.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const remove = (id: string) => {
    const drop = new Set([id]);
    clauses.forEach((c) => { if (c.parent_id && drop.has(c.parent_id)) drop.add(c.id); });
    saveClauses.mutate(clauses.filter((c) => !drop.has(c.id)));
  };

  return (
    <>
      <PageHeader
        back={{ href: "/admin/frameworks", label: "Frameworks" }}
        title={`${framework.name} ${version.version_label}`}
        meta={<>
          <VersionBadge status={version.status} version={version.version} />
          {!parsing && <span className="text-sm text-muted-foreground">{clauses.length} clauses · {assessable} assessable</span>}
        </>}
        actions={isDraft ? (
          <>
            <AlertDialog>
              <AlertDialogTrigger asChild><Button variant="ghost" disabled={parsing}>Discard</Button></AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Discard this draft version?</AlertDialogTitle>
                  <AlertDialogDescription>The uploaded document and the extracted clauses will be removed.</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => discard.mutate(undefined)}>Discard</AlertDialogAction></AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            {version.has_source && <Button variant="outline" onClick={() => reparse.mutate(undefined)} disabled={parsing || reparse.isPending}><RefreshCw /> Re-parse</Button>}
            <Button onClick={() => publish.mutate(undefined)} disabled={parsing || clauses.length === 0 || publish.isPending}>Publish</Button>
          </>
        ) : (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="ghost" disabled={version.mapped_requirements > 0}
                title={version.mapped_requirements > 0 ? `${version.mapped_requirements} requirements map to this version's clauses, so it can't be deleted` : undefined}>
                <Trash2 /> Delete version
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete {framework.name} {version.version_label}?</AlertDialogTitle>
                <AlertDialogDescription>Its clauses and uploaded document will be removed. No requirement maps to it. This can&apos;t be undone.</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction variant="destructive" onClick={() => discard.mutate(undefined)}>Delete version</AlertDialogAction></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      />

      {parsing && (
        <div className="flex flex-col items-center gap-3 rounded-3xl bg-card px-6 py-16 text-center">
          <p className="font-medium">Reading the document</p>
          <p className="max-w-sm text-sm text-muted-foreground">The AI is extracting chapters, sections and clauses. Large standards can take a few minutes.</p>
          <Loader2 className="mt-2 size-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {version.parse_status === "failed" && (
        <Alert variant="destructive" className="mb-6">
          <TriangleAlert />
          <AlertTitle>Parsing failed</AlertTitle>
          <AlertDescription>{version.parse_error}</AlertDescription>
        </Alert>
      )}

      {!parsing && clauses.length > 0 && (
        <>
          {isDraft && (
            <Alert className="mb-4">
              <AlertTitle>Review the AI's extraction</AlertTitle>
              <AlertDescription>Check titles and structure, remove anything that isn't a real clause, and mark grouping headings as not assessable. Changes save immediately.</AlertDescription>
            </Alert>
          )}
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search clauses" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="overflow-hidden rounded-3xl bg-card">
            <div className="grid grid-cols-[1fr_auto] gap-4 border-b bg-muted/40 px-5 py-2 text-xs font-medium text-muted-foreground">
              <span>Clause</span><span>{isDraft ? "Assessable" : "Mapped requirements"}</span>
            </div>
            {visible.map((c) => (
              <div key={c.id} className="group grid grid-cols-[1fr_auto] items-center gap-4 border-b px-5 py-2.5 last:border-0">
                <div className="flex min-w-0 items-start gap-2" style={{ paddingLeft: query ? 0 : c.level * 20 }}>
                  {hasChildren.has(c.id) && !query ? (
                    <button className="mt-0.5 rounded p-0.5 hover:bg-muted" onClick={() => setCollapsed((s) => { const n = new Set(s); if (n.has(c.id)) n.delete(c.id); else n.add(c.id); return n; })}
                      aria-label={collapsed.has(c.id) ? "Expand" : "Collapse"}>
                      <ChevronRight className={`size-3.5 transition ${collapsed.has(c.id) ? "" : "rotate-90"}`} />
                    </button>
                  ) : <span className="w-4.5 shrink-0" />}
                  <span className={`shrink-0 font-mono text-xs ${c.is_assessable ? "text-primary" : "text-muted-foreground"}`}>{c.ref}</span>
                  <span className={`text-sm ${c.is_assessable ? "" : "font-medium"}`}>{c.title}</span>
                </div>
                <div className="flex items-center gap-2">
                  {isDraft ? (
                    <>
                      <Switch checked={c.is_assessable} onCheckedChange={(v) => update(c.id, { is_assessable: v })} disabled={saveClauses.isPending} aria-label="Assessable" />
                      <Button variant="ghost" size="icon-xs" className="opacity-0 group-hover:opacity-100" onClick={() => remove(c.id)} aria-label="Remove clause"><Trash2 /></Button>
                    </>
                  ) : c.is_assessable ? (
                    <Badge variant={c.mapped_requirements ? "secondary" : "outline"} className="font-mono">{c.mapped_requirements}</Badge>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}
