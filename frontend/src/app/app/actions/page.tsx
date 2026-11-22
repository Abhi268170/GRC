"use client";

import { useQuery } from "@tanstack/react-query";
import { ListTodo } from "lucide-react";
import { useState } from "react";

import { EmptyState, ListSkeleton, PageHeader, Stat } from "@/components/app/page";
import { ActionDialog, SourceLink } from "@/components/runs/registers";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { ActionItem } from "@/lib/types";

const PRIORITY: Record<string, string> = {
  critical: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
  high: "border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  low: "border-border bg-muted text-muted-foreground",
};
const STATUS: Record<string, string> = { open: "Open", in_progress: "In progress", done: "Done", dismissed: "Dismissed" };

export default function ActionsPage() {
  const items = useQuery({ queryKey: ["action-items"], queryFn: () => api<ActionItem[]>("/action-items") });
  const [filter, setFilter] = useState("active");
  const [editing, setEditing] = useState<ActionItem | null>(null);
  const all = items.data ?? [];
  const shown = all.filter((a) => (filter === "active" ? ["open", "in_progress"].includes(a.status) : filter === "all" ? true : a.status === filter));
  const overdue = all.filter((a) => a.due_date && a.status !== "done" && a.status !== "dismissed" && new Date(a.due_date) < new Date()).length;

  return (
    <>
      <PageHeader title="Action items" description="Remediation work from approved assessments. Assign owners and due dates, and track it to done." />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Stat label="Open" value={all.filter((a) => a.status === "open").length} />
        <Stat label="In progress" value={all.filter((a) => a.status === "in_progress").length} />
        <Stat label="Done" value={all.filter((a) => a.status === "done").length} />
        <Stat label="Overdue" value={overdue} />
      </div>
      <Tabs value={filter} onValueChange={setFilter} className="mb-4">
        <TabsList><TabsTrigger value="active">Active</TabsTrigger><TabsTrigger value="done">Done</TabsTrigger><TabsTrigger value="dismissed">Dismissed</TabsTrigger><TabsTrigger value="all">All</TabsTrigger></TabsList>
      </Tabs>
      {items.isLoading ? <ListSkeleton /> : shown.length === 0 ? (
        <EmptyState icon={ListTodo} title="Nothing here" text="Action items appear when an assessment is approved." />
      ) : (
        <div className="overflow-hidden rounded-3xl bg-card">
          {shown.map((a) => (
            <button key={a.id} onClick={() => setEditing(a)} className="flex w-full items-start gap-4 border-b px-5 py-4 text-left transition last:border-0 hover:bg-muted/40">
              <Badge variant="outline" className={`mt-0.5 shrink-0 capitalize ${PRIORITY[a.priority ?? "low"]}`}>{a.priority}</Badge>
              <div className="min-w-0 flex-1 space-y-1">
                <p className={`text-sm font-medium ${a.status === "done" ? "text-muted-foreground line-through" : ""}`}>{a.title}</p>
                <p className="line-clamp-1 text-xs text-muted-foreground"><SourceLink runId={a.run_id} title={a.run_title} /> · <span className="font-mono">{a.requirement_keys.join(" · ")}</span></p>
              </div>
              <div className="hidden w-32 shrink-0 text-right text-xs sm:block">
                <p>{a.owner?.full_name ?? <span className="text-muted-foreground">Unassigned</span>}</p>
                <p className={a.due_date && new Date(a.due_date) < new Date() && a.status !== "done" ? "text-destructive" : "text-muted-foreground"}>{a.due_date ? `Due ${formatDate(a.due_date)}` : "No due date"}</p>
              </div>
              <Badge variant="secondary" className="shrink-0">{STATUS[a.status]}</Badge>
            </button>
          ))}
        </div>
      )}
      {editing && <ActionDialog key={editing.id} item={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
