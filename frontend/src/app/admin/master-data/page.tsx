"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Lock, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Field } from "@/components/app/field";
import { ListSkeleton, PageHeader } from "@/components/app/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { MasterDataCategory, MasterDataItem, OrganisationalRole, OrgRoleType } from "@/lib/types";

const ROLES_KEY = "organisational_roles";
const GROUP_ORDER = ["Control classification", "Organisation", "Assessment & scoring", "Risks & actions"];
const SELECTION_LABEL: Record<string, string> = {
  one: "One per control",
  one_optional: "One per control, optional",
  several: "Several per control",
};

type NavEntry = { key: string; label: string; count: number };

// ---------- values ----------

function ItemDialog({ category, item, onClose }: { category: string; item: MasterDataItem | "new"; onClose: () => void }) {
  const existing = item === "new" ? null : item;
  const [code, setCode] = useState("");
  const [label, setLabel] = useState(existing?.label ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const save = useAction(() => existing
    ? api(`/master-data/${existing.id}`, { method: "PUT", body: { label, description: description || null, is_active: existing.is_active } })
    : api("/master-data", { body: { category, code, label, description: description || null } }),
  { invalidate: [["master-data"]], success: "Saved", onSuccess: onClose });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{existing ? "Edit value" : "Add value"}</DialogTitle>
          <DialogDescription>{existing ? <>Code <span className="font-mono">{existing.code}</span> can't be changed.</> : "The code is a permanent identifier and is never shown to users."}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {!existing && <Field label="Code" htmlFor="mcode"><Input id="mcode" className="font-mono" value={code} onChange={(e) => setCode(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} /></Field>}
          <Field label="Name" htmlFor="mlabel"><Input id="mlabel" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="Description" htmlFor="mdesc"><Textarea id="mdesc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!label.trim() || (!existing && !code) || save.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CategoryView({ category, items }: { category: MasterDataCategory; items: MasterDataItem[] }) {
  const [editing, setEditing] = useState<MasterDataItem | "new" | null>(null);
  const toggle = useAction((i: MasterDataItem) => api(`/master-data/${i.id}`, { method: "PUT", body: { label: i.label, description: i.description, is_active: !i.is_active } }), {
    invalidate: [["master-data"]],
  });
  const usage = SELECTION_LABEL[category.selection];
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h2 className="text-2xl font-medium tracking-tight">{category.label}</h2>
          <p className="max-w-xl text-sm text-muted-foreground">{category.description}</p>
          <div className="flex flex-wrap gap-1.5">
            {usage && <Badge variant="secondary" className="bg-card font-normal">{usage}</Badge>}
            {category.locked && <Badge variant="outline" className="gap-1 font-normal"><Lock className="size-3" /> Fixed</Badge>}
          </div>
        </div>
        {!category.locked && <Button size="sm" onClick={() => setEditing("new")}><Plus /> Add value</Button>}
      </div>
      <div className="overflow-hidden rounded-3xl bg-card">
        {items.map((i) => (
          <div key={i.id} className="flex items-center gap-4 border-b px-5 py-3.5 last:border-0">
            {i.numeric_value !== null && <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-accent text-sm font-medium text-accent-foreground">{i.numeric_value}</span>}
            <button className="min-w-0 flex-1 text-left" onClick={() => setEditing(i)}>
              <p className={`text-sm font-medium ${i.is_active ? "" : "text-muted-foreground line-through"}`}>{i.label}</p>
              {i.description && <p className="mt-0.5 text-xs text-muted-foreground">{i.description}</p>}
            </button>
            <span className="hidden font-mono text-xs text-muted-foreground sm:block">{i.code}</span>
            {!category.locked && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="hidden w-10 text-right md:block">{i.is_active ? "Active" : "Off"}</span>
                <Switch checked={i.is_active} onCheckedChange={() => toggle.mutate(i)} aria-label={`${i.label} active`} />
              </label>
            )}
          </div>
        ))}
        {items.length === 0 && <p className="px-5 py-8 text-center text-sm text-muted-foreground">No values yet.</p>}
      </div>
      <p className="text-xs text-muted-foreground">
        {category.locked ? "These values are fixed because scores depend on them." : "Values are never deleted. Switch a value off to stop it being picked; existing uses keep it."}
      </p>
      {editing && <ItemDialog category={category.key} item={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

// ---------- organisational roles ----------

const ROLE_TEXT = [
  ["description", "Description"],
  ["purpose", "Purpose"],
  ["accountabilities", "Accountabilities"],
  ["responsibilities", "Responsibilities"],
  ["decision_making_powers", "Decision-making powers"],
  ["interfaces", "Interfaces"],
] as const;
type RoleText = (typeof ROLE_TEXT)[number][0];
type RoleForm = { name: string; abbreviation: string; type: OrgRoleType; reports_to: string; is_active: boolean } & Record<RoleText, string>;
const LIST_FIELDS: RoleText[] = ["accountabilities", "responsibilities"];

function toForm(r: OrganisationalRole | null): RoleForm {
  return {
    name: r?.name ?? "", abbreviation: r?.abbreviation ?? "", type: r?.type ?? "operational", reports_to: r?.reports_to ?? "",
    is_active: r?.is_active ?? true,
    ...Object.fromEntries(ROLE_TEXT.map(([k]) => [k, r?.[k] ?? ""])) as Record<RoleText, string>,
  };
}

function RoleSheetBody({ role, onDone }: { role: OrganisationalRole | null; onDone: () => void }) {
  const [editing, setEditing] = useState(role === null);
  const [f, setF] = useState<RoleForm>(() => toForm(role));
  const set = <K extends keyof RoleForm>(k: K, v: RoleForm[K]) => setF((x) => ({ ...x, [k]: v }));
  const body = () => ({ ...f, reports_to: f.reports_to.trim() || null, ...Object.fromEntries(ROLE_TEXT.map(([k]) => [k, f[k].trim() || null])) });
  const save = useAction(() => role
    ? api(`/master-data/organisational-roles/${role.id}`, { method: "PUT", body: body() })
    : api("/master-data/organisational-roles", { body: body() }),
  { invalidate: [["organisational-roles"]], success: role ? "Role saved" : "Role added", onSuccess: () => (role ? setEditing(false) : onDone()) });
  const valid = f.name.trim().length >= 2 && /^[A-Z]{2,8}$/.test(f.abbreviation);

  if (!editing && role) {
    return (
      <div className="flex min-h-full flex-col">
        <div className="space-y-3 p-6">
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="font-mono">{role.abbreviation}</span>· {role.type === "executive" ? "Executive" : "Operational"}
            {!role.is_active && <Badge variant="outline">Off</Badge>}
          </p>
          <SheetTitle className="text-2xl font-normal tracking-tight">{role.name}</SheetTitle>
          <SheetDescription>{role.reports_to ? <>Reports to {role.reports_to}</> : "No reporting line set"}</SheetDescription>
        </div>
        <div className="flex-1 space-y-5 px-6 pb-6">
          {ROLE_TEXT.map(([k, label]) => {
            const text = role[k];
            const parts = text && LIST_FIELDS.includes(k) ? text.split(";").map((x) => x.trim()).filter(Boolean).map((x) => x[0].toUpperCase() + x.slice(1)) : null;
            return (
              <section key={k} className="space-y-1.5">
                <h3 className="text-xs font-medium text-muted-foreground">{label}</h3>
                {!text ? <p className="text-sm text-muted-foreground">Not set</p>
                  : parts && parts.length > 1 ? <ul className="list-disc space-y-1 pl-5 text-sm">{parts.map((p) => <li key={p}>{p.replace(/\.$/, "")}</li>)}</ul>
                  : <p className="text-sm leading-relaxed">{text}</p>}
              </section>
            );
          })}
        </div>
        <div className="sticky bottom-0 border-t bg-popover p-4"><Button className="w-full" onClick={() => setEditing(true)}>Edit role</Button></div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="space-y-1 p-6 pb-2">
        <SheetTitle className="text-2xl font-normal tracking-tight">{role ? `Edit ${role.abbreviation}` : "Add a role"}</SheetTitle>
        <SheetDescription>Roles are linked from users and controls.</SheetDescription>
      </div>
      <div className="flex-1 space-y-4 p-6">
        <Field label="Name" htmlFor="rname"><Input id="rname" value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Abbreviation" htmlFor="rabbr" hint="2 to 8 capital letters">
            <Input id="rabbr" className="font-mono" value={f.abbreviation} maxLength={8} onChange={(e) => set("abbreviation", e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))} />
          </Field>
          <Field label="Type">
            <Select value={f.type} onValueChange={(v) => set("type", v as OrgRoleType)}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="executive">Executive</SelectItem><SelectItem value="operational">Operational</SelectItem></SelectContent>
            </Select>
          </Field>
        </div>
        <Field label="Reports to" htmlFor="rreports" hint="Plain text, for example CEO or Board of Directors">
          <Input id="rreports" value={f.reports_to} onChange={(e) => set("reports_to", e.target.value)} />
        </Field>
        {ROLE_TEXT.map(([k, label]) => (
          <Field key={k} label={label} htmlFor={`r-${k}`} hint={LIST_FIELDS.includes(k) ? "Separate items with a semicolon" : undefined}>
            <Textarea id={`r-${k}`} rows={3} value={f[k]} onChange={(e) => set(k, e.target.value)} />
          </Field>
        ))}
        <label className="flex items-center justify-between gap-4 rounded-2xl bg-muted px-4 py-3">
          <span><span className="block text-sm font-medium">Active</span><span className="text-xs text-muted-foreground">Inactive roles can't be picked for new users or controls.</span></span>
          <Switch checked={f.is_active} onCheckedChange={(v) => set("is_active", v)} />
        </label>
      </div>
      <div className="sticky bottom-0 flex gap-2 border-t bg-popover p-4">
        <Button variant="outline" className="flex-1" onClick={() => (role ? (setF(toForm(role)), setEditing(false)) : onDone())}>Cancel</Button>
        <Button className="flex-1" onClick={() => save.mutate(undefined)} disabled={!valid || save.isPending}>{role ? "Save role" : "Add role"}</Button>
      </div>
    </div>
  );
}

function RolesView({ roles }: { roles: OrganisationalRole[] }) {
  const [open, setOpen] = useState<OrganisationalRole | "new" | null>(null);
  const current = open === "new" || open === null ? open : roles.find((r) => r.id === open.id) ?? null;
  const toggle = useAction((r: OrganisationalRole) => api(`/master-data/organisational-roles/${r.id}`, { method: "PUT", body: { ...r, is_active: !r.is_active } }), {
    invalidate: [["organisational-roles"]],
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h2 className="text-2xl font-medium tracking-tight">Organisational roles</h2>
          <p className="max-w-xl text-sm text-muted-foreground">Who is responsible for a control, and each user's role in their company.</p>
          <Badge variant="secondary" className="bg-card font-normal">One per control</Badge>
        </div>
        <Button size="sm" onClick={() => setOpen("new")}><Plus /> Add role</Button>
      </div>
      <div className="overflow-hidden rounded-3xl bg-card">
        {roles.map((r) => (
          <div key={r.id} className="flex items-center gap-4 border-b px-5 py-3.5 last:border-0">
            <span className="w-12 shrink-0 font-mono text-xs text-muted-foreground">{r.abbreviation}</span>
            <button className="min-w-0 flex-1 text-left" onClick={() => setOpen(r)}>
              <p className={`text-sm font-medium ${r.is_active ? "" : "text-muted-foreground line-through"}`}>{r.name}</p>
              {r.description && <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{r.description}</p>}
            </button>
            <span className="hidden w-36 truncate text-xs text-muted-foreground lg:block">{r.reports_to ? `Reports to ${r.reports_to}` : ""}</span>
            <Badge variant={r.type === "executive" ? "default" : "secondary"} className={`hidden w-24 justify-center font-normal sm:inline-flex ${r.type === "executive" ? "" : "bg-muted"}`}>
              {r.type === "executive" ? "Executive" : "Operational"}
            </Badge>
            <Switch checked={r.is_active} onCheckedChange={() => toggle.mutate(r)} aria-label={`${r.name} active`} />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Roles are never deleted. Switch a role off to stop it being picked; existing users and controls keep it.</p>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-xl">
          {open !== null && <RoleSheetBody key={open === "new" ? "new" : open.id} role={current === "new" ? null : current} onDone={() => setOpen(null)} />}
        </SheetContent>
      </Sheet>
    </div>
  );
}

// ---------- page ----------

function Nav({ groups, active, onPick }: { groups: [string, NavEntry[]][]; active: string; onPick: (k: string) => void }) {
  const pill = (on: boolean) => `flex w-full items-center justify-between gap-3 rounded-lg px-3.5 py-1.5 text-left text-sm transition ${on ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`;
  return (
    <nav className="sticky top-24 max-h-[calc(100vh-7rem)] space-y-4 overflow-y-auto rounded-3xl bg-card p-3" aria-label="Master data lists">
      {groups.map(([group, entries]) => (
        <div key={group} className="space-y-1">
          <p className="px-3.5 pb-1 text-xs text-muted-foreground">{group}</p>
          {entries.map((e) => (
            <button key={e.key} onClick={() => onPick(e.key)} className={pill(e.key === active)} aria-current={e.key === active ? "page" : undefined}>
              <span className="truncate">{e.label}</span>
              <span className={`text-xs tabular-nums ${e.key === active ? "text-primary-foreground/70" : "text-muted-foreground"}`}>{e.count}</span>
            </button>
          ))}
        </div>
      ))}
      <div className="space-y-1">
        <p className="px-3.5 pb-1 text-xs text-muted-foreground">Control library</p>
        <Link href="/admin/library" className={pill(false)}><span>Domains</span><ArrowUpRight className="size-3.5 text-muted-foreground" /></Link>
      </div>
    </nav>
  );
}

function MasterData() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const categories = useQuery({ queryKey: ["master-data-categories"], queryFn: () => api<MasterDataCategory[]>("/master-data/categories") });
  const items = useQuery({ queryKey: ["master-data"], queryFn: () => api<MasterDataItem[]>("/master-data") });
  const roles = useQuery({ queryKey: ["organisational-roles"], queryFn: () => api<OrganisationalRole[]>("/master-data/organisational-roles") });

  if (!categories.data || !items.data || !roles.data) return <ListSkeleton />;

  const count = (key: string) => items.data.filter((i) => i.category === key).length;
  const byGroup = new Map<string, NavEntry[]>(GROUP_ORDER.map((g) => [g, []]));
  for (const c of categories.data) {
    if (!byGroup.has(c.group)) byGroup.set(c.group, []);
    byGroup.get(c.group)!.push({ key: c.key, label: c.label, count: count(c.key) });
  }
  byGroup.get("Organisation")!.push({ key: ROLES_KEY, label: "Organisational roles", count: roles.data.length });
  const groups = [...byGroup.entries()].filter(([, e]) => e.length > 0);
  const all = groups.flatMap(([, e]) => e);
  const requested = params.get("list");
  const active = all.some((e) => e.key === requested) ? requested! : all[0].key;
  const pick = (k: string) => router.replace(`${pathname}?list=${k}`, { scroll: false });
  const category = categories.data.find((c) => c.key === active);

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
      <div className="hidden lg:block"><Nav groups={groups} active={active} onPick={pick} /></div>
      <div className="lg:hidden">
        <Select value={active} onValueChange={pick}>
          <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {groups.map(([g, entries]) => entries.map((e, i) => (
              <SelectItem key={e.key} value={e.key}>{i === 0 ? `${g} · ` : ""}{e.label} ({e.count})</SelectItem>
            )))}
          </SelectContent>
        </Select>
      </div>
      <div className="min-w-0">
        {active === ROLES_KEY ? <RolesView roles={roles.data} />
          : category && <CategoryView key={category.key} category={category} items={items.data.filter((i) => i.category === category.key)} />}
      </div>
    </div>
  );
}

export default function MasterDataPage() {
  return (
    <>
      <PageHeader title="Master data" description="The pick-lists everyone chooses from, so every control is classified the same way." />
      <Suspense fallback={<ListSkeleton />}><MasterData /></Suspense>
    </>
  );
}
