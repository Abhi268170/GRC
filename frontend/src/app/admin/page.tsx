"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, BookOpen, ClipboardList, FileEdit, Layers, Library, Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader, Panel, PanelTitle, Stat } from "@/components/app/page";
import { FrameworkBadge, VersionBadge } from "@/components/app/status";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import type { AssessmentListItem, ControlSummary, Domain, Framework } from "@/lib/types";

export default function AdminOverview() {
  const { data: me } = useMe();
  const domains = useQuery({ queryKey: ["domains"], queryFn: () => api<Domain[]>("/library/domains") });
  const controls = useQuery({ queryKey: ["controls"], queryFn: () => api<ControlSummary[]>("/library/controls") });
  const frameworks = useQuery({ queryKey: ["frameworks"], queryFn: () => api<Framework[]>("/frameworks") });
  const assessments = useQuery({ queryKey: ["assessments"], queryFn: () => api<AssessmentListItem[]>("/assessments") });

  const ctrl = controls.data ?? [];
  const requirements = ctrl.reduce((n, c) => n + c.requirement_count, 0);
  const mapped = ctrl.filter((c) => c.frameworks.length > 0).length;
  const published = (assessments.data ?? []).filter((a) => a.published);
  const drafts = [
    ...ctrl.filter((c) => c.has_draft).map((c) => ({ label: `${c.code} ${c.title}`, kind: "Control", href: `/admin/library/controls/${c.id}` })),
    ...(domains.data ?? []).filter((d) => d.draft).map((d) => ({ label: d.draft!.name, kind: "Domain", href: "/admin/library" })),
    ...(assessments.data ?? []).filter((a) => a.draft).map((a) => ({ label: a.draft!.title, kind: "Assessment", href: `/admin/assessments/${a.draft!.id}` })),
    ...(frameworks.data ?? []).flatMap((f) => f.versions.filter((v) => v.status === "draft").map((v) => ({ label: `${f.name} ${v.version_label}`, kind: "Framework", href: `/admin/frameworks/${v.id}` }))),
  ];

  return (
    <>
      <div className="mb-6 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <PageHeader eyebrow={`Welcome back, ${me?.user.full_name.split(" ")[0] ?? ""}`} title="Content overview" />
        <Link href="/admin/library" className="glass-brand group block w-full max-w-md rounded-3xl p-6 text-black transition hover:-translate-y-0.5 lg:mb-8">
          <div className="flex items-center justify-between text-sm"><span>Library health</span><ArrowUpRight className="size-4" /></div>
          <p className="mt-6 text-2xl leading-snug">
            <b className="font-medium">{mapped} of {ctrl.length}</b> controls map to a framework, covering <b className="font-medium">{requirements}</b> requirements.
          </p>
        </Link>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Frameworks" icon={BookOpen} value={frameworks.data?.length ?? "–"} href="/admin/frameworks"
          hint={(frameworks.data ?? []).map((f) => f.versions.find((v) => v.status === "published")?.clause_count ?? 0).reduce((a, b) => a + b, 0) + " published clauses"} />
        <Stat label="Domains" icon={Layers} value={domains.data?.length ?? "–"} href="/admin/library"
          hint={`${(domains.data ?? []).filter((d) => d.draft).length} with unpublished changes`} />
        <Stat label="Controls" icon={Library} value={ctrl.length || "–"} hint={`${requirements} requirements`} href="/admin/library" />
        <Stat label="Live assessments" icon={ClipboardList} value={published.length} href="/admin/assessments"
          hint={`${(assessments.data ?? []).reduce((n, a) => n + a.run_count, 0)} tenant runs`} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel className="p-6">
          <PanelTitle icon={FileEdit}>Drafts in progress</PanelTitle>
          {drafts.length === 0 ? (
            <p className="mt-6 text-sm text-muted-foreground">No unpublished drafts. Everything is live.</p>
          ) : (
            <ul className="mt-4 space-y-1">
              {drafts.map((d) => (
                <li key={d.href + d.label}>
                  <Link href={d.href} className="flex items-center justify-between gap-3 rounded-2xl px-3 py-2.5 text-sm hover:bg-muted">
                    <span className="truncate">{d.label}</span>
                    <span className="shrink-0 rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">{d.kind}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel className="p-6">
          <PanelTitle icon={ClipboardList} action={<Button size="sm" asChild><Link href="/admin/assessments/new"><Plus /> New</Link></Button>}>Live assessments</PanelTitle>
          {published.length === 0 ? (
            <p className="mt-6 text-sm text-muted-foreground">Nothing published yet.</p>
          ) : (
            <ul className="mt-4 space-y-1">
              {published.map((a) => (
                <li key={a.id}>
                  <Link href={`/admin/assessments/${a.published!.id}`} className="flex items-center justify-between gap-3 rounded-2xl px-3 py-2.5 text-sm hover:bg-muted">
                    <span className="truncate">{a.published!.title}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="text-xs text-muted-foreground">{a.published!.question_count} questions</span>
                      <VersionBadge status="published" version={a.published!.version} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap gap-1.5">{(frameworks.data ?? []).map((f) => <FrameworkBadge key={f.id} code={f.code} />)}</div>
        </Panel>
      </div>
    </>
  );
}
