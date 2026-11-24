"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, ClipboardCheck, Gauge, ListTodo, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { CatalogCard, detailsConfirmed } from "@/components/app/catalog";
import { ListSkeleton, PageHeader, SegmentBar, Stat, TickChart } from "@/components/app/page";
import { RunRow } from "@/components/runs/run-row";
import { api } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import type { ActionItem, CatalogItem, RiskItem, RunSummary } from "@/lib/types";

function Insight({ runs }: { runs: RunSummary[] }) {
  const active = runs.find((r) => r.status !== "approved");
  const approved = runs.find((r) => r.status === "approved");
  const { label, text, href } = active
    ? {
        label: "Next step",
        text: active.status === "in_review" ? <>Your <b className="font-medium">{active.title}</b> is ready for review.</> :
          <><b className="font-medium">{active.progress}%</b> of {active.title} is confirmed. Pick up where you left off.</>,
        href: `/app/runs/${active.id}`,
      }
    : approved
      ? { label: "Latest result", text: <>Your latest maturity is <b className="font-medium">{approved.score?.toFixed(1)} out of 4</b>.</>, href: `/app/runs/${approved.id}` }
      : { label: "Get started", text: <>Start your first assessment. It takes a <b className="font-medium">conversation</b>, not a spreadsheet.</>, href: "/app/assessments" };
  return (
    <Link href={href} className="glass-brand group block w-full max-w-md rounded-3xl p-6 text-black transition hover:-translate-y-0.5">
      <div className="flex items-center justify-between text-sm"><span>{label}</span><ArrowUpRight className="size-4 transition group-hover:translate-x-0.5" /></div>
      <p className="mt-6 text-2xl leading-snug">{text}</p>
    </Link>
  );
}

/** Spread values into a fixed number of ticks for the tick charts. */
function ticks(values: number[], n = 40): number[] {
  if (!values.length) return Array.from({ length: n }, (_, i) => 0.15 + 0.1 * Math.abs(Math.sin(i)));
  return Array.from({ length: n }, (_, i) => values[i % values.length]);
}

export default function TenantHome() {
  const { data: me } = useMe();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogItem[]>("/assessments/catalog/published") });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<RunSummary[]>("/runs") });
  const actions = useQuery({ queryKey: ["action-items"], queryFn: () => api<ActionItem[]>("/action-items") });
  const risks = useQuery({ queryKey: ["risks"], queryFn: () => api<RiskItem[]>("/risks") });

  const all = runs.data ?? [];
  const active = all.filter((r) => r.status !== "approved");
  const latest = all.find((r) => r.status === "approved");
  const current = active[0];
  const openActions = (actions.data ?? []).filter((a) => ["open", "in_progress"].includes(a.status));
  const activeRisks = (risks.data ?? []).filter((r) => ["open", "mitigating"].includes(r.status));
  const priorityWeight = { critical: 1, high: 0.8, medium: 0.5, low: 0.3 } as const;

  return (
    <>
      <div className="mb-6 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <PageHeader
          eyebrow={me?.tenant?.name ?? "Your workspace"}
          title="Overview"
        />
        {runs.data && <div className="lg:mb-8"><Insight runs={all} /></div>}
      </div>

      {me && !detailsConfirmed(me) && (
        <div className="mb-4 flex flex-col gap-3 rounded-3xl bg-brand p-6 text-brand-foreground sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">{me.user.platform_role === "tenant_admin" ? "Confirm your company details" : "Your company details aren't confirmed yet"}</p>
            <p className="text-sm opacity-80">
              {me.user.platform_role === "tenant_admin"
                ? "Check that they are right and complete. You do this once, before your first assessment."
                : "A workspace admin needs to confirm them before the first assessment can start."}
            </p>
          </div>
          <Link href="/app/company" className="inline-flex shrink-0 items-center gap-2 self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground sm:self-auto">
            {me.user.platform_role === "tenant_admin" ? "Review details" : "View details"} <ArrowUpRight className="size-4" />
          </Link>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Maturity" icon={Gauge} value={latest?.score?.toFixed(1) ?? "—"} unit="/4" hint={latest ? latest.title : "No approved assessment yet"} href={latest ? `/app/runs/${latest.id}` : "/app/runs"}>
          <SegmentBar value={latest?.score ?? 0} max={4} />
        </Stat>
        <Stat label="In progress" icon={ClipboardCheck} value={current ? current.progress : 0} unit="%" hint={current ? `${current.domains_completed}/${current.domains_total} domains · ${current.title}` : "Nothing in progress"} href={current ? `/app/runs/${current.id}` : "/app/assessments"}>
          <SegmentBar value={current?.progress ?? 0} max={100} />
        </Stat>
        <Stat label="Open actions" icon={ListTodo} value={openActions.length} hint={`${openActions.filter((a) => a.priority === "critical" || a.priority === "high").length} high priority`} href="/app/actions">
          <TickChart values={ticks(openActions.map((a) => priorityWeight[a.priority ?? "low"]))} highlight={openActions.length ? [openActions.length - 1] : []} />
        </Stat>
        <Stat label="Active risks" icon={ShieldAlert} value={activeRisks.length} hint={activeRisks.length ? `Highest score ${Math.max(...activeRisks.map((r) => r.score))}` : "No active risks"} href="/app/risks">
          <TickChart values={ticks(activeRisks.map((r) => r.score / 25))} highlight={activeRisks.length ? [0] : []} />
        </Stat>
      </div>

      {active.length > 0 && (
        <section className="mt-10">
          <div className="mb-4 flex items-end justify-between">
            <h2 className="text-xl font-medium tracking-tight">Continue where you left off</h2>
            <Link href="/app/runs" className="inline-flex items-center gap-1 text-sm hover:opacity-70">All assessments <ArrowUpRight className="size-3.5" /></Link>
          </div>
          <div className="space-y-2">{active.slice(0, 4).map((r) => <RunRow key={r.id} run={r} />)}</div>
        </section>
      )}

      <section className="mt-10">
        <div className="mb-4 flex items-end justify-between">
          <h2 className="text-xl font-medium tracking-tight">Available assessments</h2>
          <Link href="/app/assessments" className="inline-flex items-center gap-1 text-sm hover:opacity-70">Catalog <ArrowUpRight className="size-3.5" /></Link>
        </div>
        {catalog.isLoading ? <ListSkeleton rows={2} /> : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {catalog.data?.slice(0, 3).map((item) => <CatalogCard key={item.version_id} item={item} />)}
          </div>
        )}
      </section>
    </>
  );
}
