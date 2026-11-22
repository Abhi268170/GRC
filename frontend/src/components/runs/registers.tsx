"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Field } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { ActionItem, RiskItem, User } from "@/lib/types";

function Choice({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <Field label={label}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent>{options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
      </Select>
    </Field>
  );
}

function useTeam() {
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  return [["none", "Unassigned"], ...(users.data ?? []).filter((u) => u.is_active).map((u) => [u.id, u.full_name])] as [string, string][];
}

export function ActionDialog({ item, onClose }: { item: ActionItem; onClose: () => void }) {
  const team = useTeam();
  const [f, setF] = useState({
    title: item.title, description: item.description ?? "", priority: item.priority ?? "medium", status: item.status,
    owner_id: item.owner?.id ?? "none", due_date: item.due_date ?? "",
  });
  const save = useAction(() => api(`/action-items/${item.id}`, { method: "PUT", body: { ...f, owner_id: f.owner_id === "none" ? null : f.owner_id, due_date: f.due_date || null } }), {
    invalidate: [["action-items"]], success: "Saved", onSuccess: onClose,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Action item</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <Field label="Title"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Description"><Textarea rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Choice label="Status" value={f.status} onChange={(v) => setF({ ...f, status: v as ActionItem["status"] })}
              options={[["open", "Open"], ["in_progress", "In progress"], ["done", "Done"], ["dismissed", "Dismissed"]]} />
            <Choice label="Priority" value={f.priority} onChange={(v) => setF({ ...f, priority: v as NonNullable<ActionItem["priority"]> })}
              options={[["critical", "Critical"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]]} />
            <Choice label="Owner" value={f.owner_id} onChange={(v) => setF({ ...f, owner_id: v })} options={team} />
            <Field label="Due date"><Input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
          </div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>Save</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RiskDialog({ item, onClose }: { item: RiskItem; onClose: () => void }) {
  const team = useTeam();
  const [f, setF] = useState({
    title: item.title, description: item.description ?? "", category: item.category ?? "security", likelihood: String(item.likelihood),
    impact: String(item.impact), treatment: item.treatment ?? "none", status: item.status, owner_id: item.owner?.id ?? "none",
  });
  const scale: [string, string][] = [["1", "1 · Very low"], ["2", "2 · Low"], ["3", "3 · Medium"], ["4", "4 · High"], ["5", "5 · Very high"]];
  const save = useAction(() => api(`/risks/${item.id}`, {
    method: "PUT",
    body: { ...f, likelihood: Number(f.likelihood), impact: Number(f.impact), treatment: f.treatment === "none" ? null : f.treatment, owner_id: f.owner_id === "none" ? null : f.owner_id },
  }), { invalidate: [["risks"]], success: "Saved", onSuccess: onClose });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Risk</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <Field label="Title"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Description"><Textarea rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Choice label="Likelihood" value={f.likelihood} onChange={(v) => setF({ ...f, likelihood: v })} options={scale} />
            <Choice label="Impact" value={f.impact} onChange={(v) => setF({ ...f, impact: v })} options={scale} />
            <Choice label="Treatment" value={f.treatment} onChange={(v) => setF({ ...f, treatment: v })}
              options={[["none", "Not decided"], ["mitigate", "Mitigate"], ["accept", "Accept"], ["transfer", "Transfer"], ["avoid", "Avoid"]]} />
            <Choice label="Status" value={f.status} onChange={(v) => setF({ ...f, status: v as RiskItem["status"] })}
              options={[["open", "Open"], ["mitigating", "Mitigating"], ["accepted", "Accepted"], ["closed", "Closed"], ["dismissed", "Dismissed"]]} />
            <Choice label="Category" value={f.category} onChange={(v) => setF({ ...f, category: v })}
              options={[["security", "Information security"], ["compliance", "Compliance"], ["operational", "Operational"], ["third_party", "Third party"], ["data_privacy", "Data privacy"]]} />
            <Choice label="Owner" value={f.owner_id} onChange={(v) => setF({ ...f, owner_id: v })} options={team} />
          </div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>Save</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SourceLink({ runId, title }: { runId?: string | null; title?: string | null }) {
  return runId ? <Link href={`/app/runs/${runId}`} className="hover:opacity-70 hover:underline">{title}</Link> : <span>Manual</span>;
}
