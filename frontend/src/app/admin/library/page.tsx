"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download, FileUp, Layers, MoreHorizontal, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Field } from "@/components/app/field";
import { EmptyState, ListSkeleton, PageHeader } from "@/components/app/page";
import { FrameworkBadge, VersionBadge } from "@/components/app/status";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { ControlSummary, Domain } from "@/lib/types";

type DomainDialog = { mode: "create" } | { mode: "edit"; domain: Domain } | null;

function DomainEditor({ state, onClose }: { state: DomainDialog; onClose: () => void }) {
  const editing = state?.mode === "edit" ? state.domain : null;
  const current = editing?.draft ?? editing?.published;
  const [abbreviation, setAbbreviation] = useState("");
  const [name, setName] = useState(current?.name ?? "");
  const [description, setDescription] = useState(current?.description ?? "");

  const save = useAction(
    async () => {
      if (!editing) return api("/library/domains", { body: { abbreviation, name, description: description || null } });
      if (!editing.draft) await api(`/library/domains/${editing.id}/draft`, { method: "POST" });
      return api(`/library/domains/${editing.id}/draft`, { method: "PUT", body: { name, description: description || null } });
    },
    { invalidate: [["domains"]], success: editing ? "Draft saved" : "Domain created as a draft", onSuccess: onClose },
  );

  return (
    <Dialog open={!!state} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "Edit domain" : "New domain"}</DialogTitle>
          <DialogDescription>
            {editing?.published && !editing.draft ? "Saving creates a new draft version. Publish it to make it live." : "Domains group related controls in assessments."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {!editing && (
            <Field label="Abbreviation" htmlFor="dcode" hint="2 to 6 capital letters, e.g. IAM. It starts every control code in the domain and can't change later.">
              <Input id="dcode" className="max-w-40 font-mono" maxLength={6} value={abbreviation} onChange={(e) => setAbbreviation(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))} />
            </Field>
          )}
          <Field label="Name" htmlFor="dname">
            <Input id="dname" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description" htmlFor="ddesc">
            <Textarea id="ddesc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={save.isPending || name.trim().length < 2 || (!editing && abbreviation.length < 2)}>
            Save draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function LibraryPage() {
  const domains = useQuery({ queryKey: ["domains"], queryFn: () => api<Domain[]>("/library/domains") });
  const controls = useQuery({ queryKey: ["controls"], queryFn: () => api<ControlSummary[]>("/library/controls") });
  const [selected, setSelected] = useState<string | "all">("all");
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<DomainDialog>(null);

  const publishDomain = useAction((id: string) => api(`/library/domains/${id}/publish`, { method: "POST" }), {
    invalidate: [["domains"]], success: "Domain published",
  });
  const discardDomain = useAction((id: string) => api(`/library/domains/${id}/draft`, { method: "DELETE" }), {
    invalidate: [["domains"]], success: "Draft discarded",
  });

  const domainName = useMemo(() => {
    const map = new Map<string, string>();
    domains.data?.forEach((d) => map.set(d.id, (d.published ?? d.draft)!.name));
    return map;
  }, [domains.data]);

  const visible = (controls.data ?? []).filter(
    (c) => (selected === "all" || c.domain_id === selected) &&
      (!query || `${c.code} ${c.title}`.toLowerCase().includes(query.toLowerCase())),
  );

  return (
    <>
      <PageHeader
        title="Control library"
        description="Domains group controls; controls contain the testable requirements that map to framework clauses."
        actions={
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline"><Download /> Export <ChevronDown className="opacity-60" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuItem asChild><a href="/api/library/export">All domains (published)</a></DropdownMenuItem>
                {selected !== "all" && (
                  <DropdownMenuItem asChild>
                    <a href={`/api/library/export?domain_id=${selected}`}>Only {domains.data?.find((d) => d.id === selected)?.abbreviation} (published)</a>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem asChild><a href="/api/library/export?include_drafts=true">All domains, drafts where there are</a></DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild><a href="/api/library/import-template">Empty import template</a></DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="outline" asChild><Link href="/admin/library/import"><FileUp /> Import</Link></Button>
            <Button variant="outline" onClick={() => setDialog({ mode: "create" })}><Plus /> Domain</Button>
            <Button asChild><Link href="/admin/library/controls/new"><Plus /> Control</Link></Button>
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr] lg:items-start">
        {/* The domain list scrolls on its own: capped on small screens, and sticky below the header on large ones
            so it stays in view while the control list scrolls. */}
        <aside className="flex max-h-80 flex-col gap-1 lg:sticky lg:top-24 lg:max-h-[calc(100dvh-7.5rem)]">
          <button
            onClick={() => setSelected("all")}
            className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${selected === "all" ? "bg-accent font-medium text-accent-foreground" : "hover:bg-muted"}`}
          >
            All domains <span className="text-xs text-muted-foreground">{controls.data?.length ?? ""}</span>
          </button>
          <div className="-mr-2 min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-2 [scrollbar-width:thin]">
          {domains.isLoading && <ListSkeleton rows={5} />}
          {domains.data?.map((d) => {
            const v = d.published ?? d.draft!;
            return (
              <div key={d.id} className={`group flex items-center rounded-lg transition ${selected === d.id ? "bg-accent text-accent-foreground" : "hover:bg-muted"}`}>
                <button onClick={() => setSelected(d.id)} className="min-w-0 flex-1 px-3 py-2 text-left">
                  <p className={`flex gap-2 text-sm ${selected === d.id ? "font-medium" : ""}`}><span className="w-8 shrink-0 font-mono text-xs leading-5 text-muted-foreground">{d.abbreviation}</span><span className="truncate">{v.name}</span></p>
                  <p className="flex items-center gap-1.5 pl-10 text-xs text-muted-foreground">
                    {d.control_count} controls
                    {d.draft && <span className="text-warning-foreground dark:text-warning">· draft</span>}
                  </p>
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" className="mr-1 opacity-60 group-hover:opacity-100" aria-label="Domain actions">
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => setDialog({ mode: "edit", domain: d })}>Edit</DropdownMenuItem>
                    {d.draft && <DropdownMenuItem onClick={() => publishDomain.mutate(d.id)}>Publish draft</DropdownMenuItem>}
                    {d.draft && <DropdownMenuItem variant="destructive" onClick={() => discardDomain.mutate(d.id)}>Discard draft</DropdownMenuItem>}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            );
          })}
          </div>
        </aside>

        <section className="min-w-0 space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Search controls by code or title" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          {controls.isLoading ? (
            <ListSkeleton />
          ) : visible.length === 0 ? (
            <EmptyState icon={Layers} title="No controls here yet" text="Create a control to start building this domain."
              action={<Button asChild size="sm"><Link href="/admin/library/controls/new"><Plus /> New control</Link></Button>} />
          ) : (
            <div className="overflow-hidden rounded-3xl bg-card">
              {visible.map((c) => (
                <Link key={c.id} href={`/admin/library/controls/${c.id}`}
                  className="flex items-center gap-4 border-b px-5 py-4 transition last:border-0 hover:bg-muted/50">
                  <span className="hidden w-24 shrink-0 font-mono text-xs text-muted-foreground sm:block">{c.version_code}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{c.title}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      <span className="font-mono sm:hidden">{c.version_code} · </span>{domainName.get(c.domain_id)}{c.area && ` · ${c.area}`} · {c.requirement_count} requirements
                    </p>
                  </div>
                  <div className="hidden shrink-0 gap-1.5 md:flex">{c.frameworks.map((f) => <FrameworkBadge key={f} code={f} />)}</div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <VersionBadge status={c.status} version={c.version} />
                    {c.has_draft && c.status === "published" && <VersionBadge status="draft" />}
                    {c.imported && <Badge variant="outline" className="text-muted-foreground" title="This draft came from an Excel import">Imported</Badge>}
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
      {dialog && <DomainEditor key={dialog.mode === "edit" ? dialog.domain.id : "new"} state={dialog} onClose={() => setDialog(null)} />}
    </>
  );
}
