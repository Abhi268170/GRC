"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { ListSkeleton } from "@/components/app/page";
import { FrameworkBadge } from "@/components/app/status";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { ControlSummary, Domain } from "@/lib/types";

/** Pick published controls, grouped by domain. */
export function ControlPicker({ value, onChange }: { value: Set<string>; onChange: (v: Set<string>) => void }) {
  const domains = useQuery({ queryKey: ["domains"], queryFn: () => api<Domain[]>("/library/domains") });
  const controls = useQuery({ queryKey: ["controls"], queryFn: () => api<ControlSummary[]>("/library/controls") });
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const published = (controls.data ?? []).filter((c) => c.status === "published" &&
      (!query || `${c.code} ${c.title}`.toLowerCase().includes(query.toLowerCase())));
    return (domains.data ?? [])
      .filter((d) => d.published)
      .map((d) => ({ domain: d, controls: published.filter((c) => c.domain_id === d.id) }))
      .filter((g) => g.controls.length);
  }, [domains.data, controls.data, query]);

  if (domains.isLoading || controls.isLoading) return <ListSkeleton />;

  const toggle = (ids: string[], on: boolean) => {
    const next = new Set(value);
    ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
    onChange(next);
  };

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input placeholder="Filter controls" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {groups.map(({ domain, controls: list }) => {
        const ids = list.map((c) => c.id);
        const picked = ids.filter((id) => value.has(id)).length;
        return (
          <div key={domain.id} className="overflow-hidden rounded-3xl bg-card">
            <label className="flex cursor-pointer items-center gap-3 border-b bg-muted/40 px-4 py-3">
              <Checkbox checked={picked === ids.length ? true : picked ? "indeterminate" : false} onCheckedChange={(v) => toggle(ids, v === true)} />
              <span className="flex-1 text-sm font-medium">{domain.published!.name}</span>
              <span className="text-xs text-muted-foreground">{picked}/{ids.length}</span>
            </label>
            {list.map((c) => (
              <label key={c.id} className="flex cursor-pointer items-center gap-3 border-b px-4 py-2.5 last:border-0 hover:bg-muted/30">
                <Checkbox checked={value.has(c.id)} onCheckedChange={(v) => toggle([c.id], v === true)} />
                <span className="w-14 shrink-0 font-mono text-xs text-muted-foreground">{c.code}</span>
                <span className="min-w-0 flex-1 truncate text-sm">{c.title}</span>
                <span className="hidden gap-1 sm:flex">{c.frameworks.map((f) => <FrameworkBadge key={f} code={f} />)}</span>
                <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">{c.requirement_count} req.</span>
              </label>
            ))}
          </div>
        );
      })}
      {groups.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">No published controls match.</p>}
    </div>
  );
}
