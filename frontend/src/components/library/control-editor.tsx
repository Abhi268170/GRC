"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, ChevronRight, Link2, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";

import { Field } from "@/components/app/field";
import { MandatoryBadge } from "@/components/runs/badges";
import { FrameworkBadge } from "@/components/app/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { CONTROL_MULTI_FIELDS, CONTROL_TEXT_FIELDS } from "@/lib/types";
import type {
  ClauseRef, ClauseSearchResult, ControlMultiField, ControlTextField, ControlVersion, Domain, MasterDataItem, OrganisationalRole,
} from "@/lib/types";

type TemplateDraft = { title: string; description: string };
export type RequirementDraft = {
  key: string; requirement_id: string | null; code?: string; statement: string; guidance: string; mandatory: boolean | null;
  evidence: string[]; action_templates: TemplateDraft[]; risk_templates: TemplateDraft[]; clauses: ClauseRef[];
};
export type ControlDraft = {
  domain_id: string; title: string; area_id: string; company_risk_exposure_id: string; responsible_role_id: string;
  requirements: RequirementDraft[];
} & Record<ControlMultiField, string[]> & Record<ControlTextField, string>;

export const MAX_REQUIREMENTS = 10;

let seq = 0;
const newKey = () => `new-${++seq}`;
const blankRequirement = (): RequirementDraft => ({
  key: newKey(), requirement_id: null, statement: "", guidance: "", mandatory: null, evidence: [""], action_templates: [], risk_templates: [], clauses: [],
});

export function draftFrom(cv: ControlVersion | null, domainId = ""): ControlDraft {
  const texts = Object.fromEntries(CONTROL_TEXT_FIELDS.map(([f]) => [f, cv?.[f] ?? ""])) as Record<ControlTextField, string>;
  const multi = Object.fromEntries(CONTROL_MULTI_FIELDS.map(([f]) => [f, cv?.[f].map((o) => o.id) ?? []])) as Record<ControlMultiField, string[]>;
  return {
    domain_id: cv?.domain_id ?? domainId,
    title: cv?.title ?? "",
    area_id: cv?.area?.id ?? "",
    company_risk_exposure_id: cv?.company_risk_exposure?.id ?? "",
    responsible_role_id: cv?.responsible_role?.id ?? "",
    ...texts,
    ...multi,
    requirements: cv
      ? cv.requirements.map((r) => ({
          key: r.requirement_id, requirement_id: r.requirement_id, code: r.code, statement: r.statement, guidance: r.guidance, mandatory: r.mandatory,
          evidence: r.evidence.length ? r.evidence : [""],
          action_templates: r.action_templates.map((t) => ({ title: t.title, description: t.description })),
          risk_templates: r.risk_templates.map((t) => ({ title: t.title, description: t.description })),
          clauses: r.clauses,
        }))
      : [blankRequirement()],
  };
}

/** A template that was added but left completely empty is dropped; anything else must have both parts. */
const isBlank = (t: TemplateDraft) => !t.title.trim() && !t.description.trim();
export const templateComplete = (t: TemplateDraft) => t.title.trim().length >= 2 && t.description.trim().length >= 2;
const cleanTemplates = (ts: TemplateDraft[]) =>
  ts.filter((t) => !isBlank(t)).map((t) => ({ title: t.title.trim(), description: t.description.trim() }));

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One-line summary shown on a collapsed requirement card. */
function summary(r: RequirementDraft): string[] {
  const evidence = r.evidence.filter((e) => e.trim()).length;
  return [
    r.guidance.trim() ? "Guidance" : "No guidance",
    plural(evidence, "evidence line"),
    plural(r.action_templates.length, "action template"),
    plural(r.risk_templates.length, "risk template"),
    plural(r.clauses.length, "clause"),
  ];
}

/** Why a requirement can't be saved yet, or null. */
export function requirementProblem(r: RequirementDraft): string | null {
  if (r.statement.trim().length < 5) return "Write the statement.";
  if (r.guidance.trim().length < 5) return "Add guidance on how to meet it.";
  if ([...r.action_templates, ...r.risk_templates].some((t) => !isBlank(t) && !templateComplete(t)))
    return "Each template needs both a title and a description.";
  return null;
}

export function toPayload(d: ControlDraft) {
  return {
    domain_id: d.domain_id,
    title: d.title.trim(),
    area_id: d.area_id || null,
    company_risk_exposure_id: d.company_risk_exposure_id || null,
    responsible_role_id: d.responsible_role_id || null,
    ...Object.fromEntries(CONTROL_MULTI_FIELDS.map(([f]) => [f, d[f]])),
    ...Object.fromEntries(CONTROL_TEXT_FIELDS.map(([f]) => [f, d[f].trim() || null])),
    requirements: d.requirements.map((r) => ({
      requirement_id: r.requirement_id, statement: r.statement, guidance: r.guidance.trim(), mandatory: r.mandatory,
      evidence: r.evidence.map((e) => e.trim()).filter(Boolean),
      action_templates: cleanTemplates(r.action_templates), risk_templates: cleanTemplates(r.risk_templates),
      clause_ids: r.clauses.map((c) => c.id),
    })),
  };
}

/** Enough to save a draft. */
export function isValid(d: ControlDraft): boolean {
  return !!d.domain_id && d.title.trim().length >= 2 && d.requirements.length >= 1 && d.requirements.length <= MAX_REQUIREMENTS
    && d.requirements.every((r) => requirementProblem(r) === null);
}

/** What still has to be filled in before publishing (mirrors the server check). */
export function missingForPublish(d: ControlDraft): string[] {
  const missing: string[] = [];
  if (!d.area_id) missing.push("Area");
  if (!d.responsible_role_id) missing.push("Organisational role");
  CONTROL_MULTI_FIELDS.forEach(([f, , label]) => { if (!d[f].length) missing.push(label); });
  if (!d.key_requirement.trim()) missing.push("Key requirement");
  return missing;
}

function ClausePicker({ selected, onAdd }: { selected: ClauseRef[]; onAdd: (c: ClauseRef) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const results = useQuery({
    queryKey: ["clause-search", q],
    queryFn: () => api<ClauseSearchResult[]>(`/frameworks/clauses/search?q=${encodeURIComponent(q)}&limit=40`),
    enabled: open,
    placeholderData: (prev) => prev,
  });
  const taken = new Set(selected.map((c) => c.id));
  const groups = new Map<string, ClauseSearchResult[]>();
  results.data?.filter((c) => !taken.has(c.id)).forEach((c) => groups.set(c.framework_name, [...(groups.get(c.framework_name) ?? []), c]));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="xs"><Link2 /> Map clause</Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Search by reference or title, e.g. A.5.15" value={q} onValueChange={setQ} />
          <CommandList>
            <CommandEmpty>{results.isFetching ? "Searching…" : "No matching clauses"}</CommandEmpty>
            {[...groups.entries()].map(([fw, items]) => (
              <CommandGroup key={fw} heading={fw}>
                {items.map((c) => (
                  <CommandItem key={c.id} value={c.id} onSelect={() => { onAdd({ id: c.id, framework_code: c.framework_code, ref: c.ref, title: c.title }); setOpen(false); }}>
                    <span className="w-20 shrink-0 font-mono text-xs">{c.ref}</span>
                    <span className="line-clamp-2 text-xs">{c.title}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Toggle chips for a several-per-control list. */
function MultiPick({ options, value, onChange }: { options: MasterDataItem[]; value: string[]; onChange: (v: string[]) => void }) {
  const shown = options.filter((o) => o.is_active || value.includes(o.id));
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((o) => {
        const on = value.includes(o.id);
        return (
          <button key={o.id} type="button" title={o.description ?? undefined} aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o.id) : [...value, o.id])}
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs transition ${on ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70"}`}>
            {on && <Check className="size-3" />}{o.label}
          </button>
        );
      })}
    </div>
  );
}

const NONE = "__none";

function OptionSelect({ options, value, onChange, placeholder, allowNone }: {
  options: MasterDataItem[]; value: string; onChange: (v: string) => void; placeholder: string; allowNone?: boolean;
}) {
  return (
    <Select value={value || (allowNone ? NONE : "")} onValueChange={(v) => onChange(v === NONE ? "" : v)}>
      <SelectTrigger className="w-full"><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        {allowNone && <SelectItem value={NONE}>Not set</SelectItem>}
        {options.filter((o) => o.is_active || o.id === value).map((o) => <SelectItem key={o.id} value={o.id}>{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

/** Yes / No / not set. */
function Mandatory({ value, onChange }: { value: boolean | null; onChange: (v: boolean | null) => void }) {
  const opts: [boolean | null, string][] = [[null, "Not set"], [true, "Mandatory"], [false, "Optional"]];
  return (
    <div className="inline-flex rounded-full bg-muted p-0.5">
      {opts.map(([v, label]) => (
        <button key={label} type="button" onClick={() => onChange(v)} aria-pressed={value === v}
          className={`rounded-full px-3 py-1 text-xs transition ${value === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

function SubHeading({ title, hint }: { title: string; hint: string }) {
  return <p className="text-xs"><span className="font-medium">{title}</span> <span className="text-muted-foreground">· {hint}</span></p>;
}

/** Title + description list (action item and risk templates). */
function Templates({ items, onChange, addLabel, titlePlaceholder, descPlaceholder }: {
  items: TemplateDraft[]; onChange: (t: TemplateDraft[]) => void; addLabel: string; titlePlaceholder: string; descPlaceholder: string;
}) {
  const set = (i: number, patch: Partial<TemplateDraft>) => onChange(items.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  return (
    <div className="space-y-2">
      {items.map((t, i) => {
        const incomplete = !isBlank(t) && !templateComplete(t);
        return (
        <div key={i} className="flex gap-2 rounded-2xl bg-muted/50 p-2">
          <div className="min-w-0 flex-1 space-y-2">
            <Input value={t.title} onChange={(e) => set(i, { title: e.target.value })} placeholder={`Title, ${titlePlaceholder}`} className="bg-card"
              aria-invalid={incomplete && t.title.trim().length < 2} />
            <Textarea rows={2} value={t.description} onChange={(e) => set(i, { description: e.target.value })} placeholder={descPlaceholder} className="bg-card"
              aria-invalid={incomplete && t.description.trim().length < 2} />
            {incomplete && <p className="px-1 text-xs text-destructive">Add both a title and a description, or remove this template.</p>}
          </div>
          <Button variant="ghost" size="icon-xs" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="Remove"><X /></Button>
        </div>
        );
      })}
      <Button variant="outline" size="xs" onClick={() => onChange([...items, { title: "", description: "" }])}><Plus /> {addLabel}</Button>
    </div>
  );
}

function EvidenceLines({ lines, onChange }: { lines: string[]; onChange: (l: string[]) => void }) {
  return (
    <div className="space-y-1.5">
      {lines.map((line, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/40" />
          <Input value={line} onChange={(e) => onChange(lines.map((l, j) => (j === i ? e.target.value : l)))}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onChange([...lines.slice(0, i + 1), "", ...lines.slice(i + 1)]); } }}
            placeholder="e.g. Latest completed access review, signed by the system owner" />
          <Button variant="ghost" size="icon-xs" disabled={lines.length === 1 && !line} aria-label="Remove line"
            onClick={() => onChange(lines.length === 1 ? [""] : lines.filter((_, j) => j !== i))}><X /></Button>
        </div>
      ))}
      <Button variant="outline" size="xs" onClick={() => onChange([...lines, ""])}><Plus /> Add evidence line</Button>
    </div>
  );
}

export function ControlEditor({ value, onChange, domains, domainLocked, code }: {
  value: ControlDraft; onChange: (d: ControlDraft) => void; domains: Domain[]; domainLocked?: boolean; code?: string;
}) {
  const md = useQuery({ queryKey: ["master-data"], queryFn: () => api<MasterDataItem[]>("/master-data") });
  const roles = useQuery({ queryKey: ["organisational-roles"], queryFn: () => api<OrganisationalRole[]>("/master-data/organisational-roles") });
  const list = (category: string) => (md.data ?? []).filter((m) => m.category === category);

  const set = <K extends keyof ControlDraft>(k: K, v: ControlDraft[K]) => onChange({ ...value, [k]: v });
  // Requirement cards are collapsed by default; ones that still need something start open.
  const [open, setOpen] = useState<Set<string>>(() => new Set(value.requirements.filter((r) => requirementProblem(r)).map((r) => r.key)));
  const toggle = (key: string) => setOpen((o) => { const n = new Set(o); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const allOpen = value.requirements.every((r) => open.has(r.key));
  const setReq = (i: number, patch: Partial<RequirementDraft>) =>
    set("requirements", value.requirements.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i: number, dir: -1 | 1) => {
    const next = [...value.requirements];
    [next[i], next[i + dir]] = [next[i + dir], next[i]];
    set("requirements", next);
  };
  const domain = domains.find((d) => d.id === value.domain_id);
  const roleGroups: [string, OrganisationalRole[]][] = [
    ["Executive", (roles.data ?? []).filter((r) => r.type === "executive" && (r.is_active || r.id === value.responsible_role_id))],
    ["Operational", (roles.data ?? []).filter((r) => r.type === "operational" && (r.is_active || r.id === value.responsible_role_id))],
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle>Basics</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Title" htmlFor="ctitle">
            <Input id="ctitle" value={value.title} onChange={(e) => set("title", e.target.value)} placeholder="e.g. Access Reviews" />
          </Field>
          <Field label="Domain" hint={domainLocked ? "The domain is part of the control code, so it can't change after publishing."
            : code ? `Code ${code}. Changing the domain gives the control a new code in that domain.` : domain ? `The code is assigned on save: ${domain.abbreviation} + the next free number, e.g. ${domain.abbreviation}01.` : undefined}>
            <Select value={value.domain_id} onValueChange={(v) => set("domain_id", v)} disabled={domainLocked}>
              <SelectTrigger className="w-full"><SelectValue placeholder="Choose a domain" /></SelectTrigger>
              <SelectContent>
                {domains.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    <span className="w-9 font-mono text-xs text-muted-foreground">{d.abbreviation}</span>{(d.published ?? d.draft)!.name}{!d.published && " (draft)"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Area" hint="Which kind of measure this is.">
            <OptionSelect options={list("area")} value={value.area_id} onChange={(v) => set("area_id", v)} placeholder="Choose an area" />
          </Field>
          <Field label="Organisational role" hint="Who is responsible for the control.">
            <Select value={value.responsible_role_id} onValueChange={(v) => set("responsible_role_id", v)}>
              <SelectTrigger className="w-full"><SelectValue placeholder="Choose a role" /></SelectTrigger>
              <SelectContent>
                {roleGroups.map(([label, rs]) => rs.length > 0 && (
                  <SelectGroup key={label}>
                    <SelectLabel>{label}</SelectLabel>
                    {rs.map((r) => <SelectItem key={r.id} value={r.id}>{r.name} <span className="text-muted-foreground">({r.abbreviation})</span></SelectItem>)}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Company risk exposure" hint="Optional.">
            <OptionSelect options={list("company_risk_exposure")} value={value.company_risk_exposure_id}
              onChange={(v) => set("company_risk_exposure_id", v)} placeholder="Not set" allowNone />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Classification</CardTitle>
          <CardDescription>Pick one or more values in each list. The lists are maintained in Master data.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {CONTROL_MULTI_FIELDS.map(([f, category, label]) => (
            <div key={f} className="space-y-2">
              <p className="text-sm font-medium">{label}</p>
              <MultiPick options={list(category)} value={value[f]} onChange={(v) => set(f, v)} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Description</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {CONTROL_TEXT_FIELDS.map(([f, label, hint]) => (
            <div key={f} className={f === "key_requirement" || f === "short_description" ? "sm:col-span-2" : ""}>
              <Field label={label} htmlFor={`c-${f}`} hint={hint}>
                <Textarea id={`c-${f}`} rows={f === "key_requirement" ? 2 : 3} value={value[f]} onChange={(e) => set(f, e.target.value)} />
              </Field>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="font-medium">Requirements</h2>
            <p className="text-sm text-muted-foreground">
              1 to {MAX_REQUIREMENTS} per control. Each is scored on its own and can map to clauses in several frameworks.
            </p>
          </div>
          {value.requirements.length > 1 && (
            <Button variant="ghost" size="xs" onClick={() => setOpen(allOpen ? new Set() : new Set(value.requirements.map((r) => r.key)))}>
              {allOpen ? "Collapse all" : "Expand all"}
            </Button>
          )}
        </div>
        {value.requirements.map((r, i) => {
          const isOpen = open.has(r.key);
          const problem = requirementProblem(r);
          return (
          <Card key={r.key} className="gap-0 py-0">
            <div className={`flex flex-wrap items-center gap-2 px-4 py-2.5 transition-colors ${isOpen ? "border-b" : ""}`}>
              <button type="button" onClick={() => toggle(r.key)} aria-expanded={isOpen}
                className="-my-1 flex min-w-0 flex-1 items-center gap-3 rounded-[10px] py-1 text-left">
                <ChevronRight className={`size-4 shrink-0 text-muted-foreground transition-transform duration-300 ease-smooth ${isOpen ? "rotate-90" : ""}`} />
                <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-medium">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{r.code ?? "new"}</span>
                    <span className={`truncate text-sm ${r.statement.trim() ? "" : "text-muted-foreground"}`}>{r.statement.trim() || "New requirement"}</span>
                  </span>
                  {!isOpen && (
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      {summary(r).join(" · ")}
                      {problem && <span className="text-warning-foreground dark:text-warning">· Incomplete</span>}
                    </span>
                  )}
                </span>
              </button>
              {isOpen ? <Mandatory value={r.mandatory} onChange={(v) => setReq(i, { mandatory: v })} /> : <MandatoryBadge value={r.mandatory} />}
              <Button variant="ghost" size="icon-xs" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up"><ArrowUp /></Button>
              <Button variant="ghost" size="icon-xs" disabled={i === value.requirements.length - 1} onClick={() => move(i, 1)} aria-label="Move down"><ArrowDown /></Button>
              <Button variant="ghost" size="icon-xs" disabled={value.requirements.length === 1}
                onClick={() => set("requirements", value.requirements.filter((_, j) => j !== i))} aria-label="Remove requirement"><Trash2 /></Button>
            </div>
            {/* Height animates via grid rows (0fr <-> 1fr); collapsed content is inert so it can't be tabbed into. */}
            <div className={`grid transition-[grid-template-rows] duration-300 ease-smooth ${isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
            <div className="min-h-0 overflow-hidden" inert={!isOpen}>
            <CardContent className="space-y-5 py-4">
              <Field label="Statement" htmlFor={`st-${r.key}`}>
                <Textarea id={`st-${r.key}`} rows={2} value={r.statement} onChange={(e) => setReq(i, { statement: e.target.value })}
                  placeholder="A testable statement, e.g. User access to critical systems is reviewed at least quarterly." />
              </Field>
              <Field label="Guidance" htmlFor={`gd-${r.key}`} hint="Short: how to meet the requirement. Evidence below is what proves it.">
                <Textarea id={`gd-${r.key}`} rows={2} value={r.guidance} onChange={(e) => setReq(i, { guidance: e.target.value })}
                  placeholder="e.g. System owners review the user list of each critical system every quarter and remove access that is no longer needed." />
              </Field>
              <div className="space-y-2">
                <SubHeading title="Evidence" hint="what can be checked to show it's met" />
                <EvidenceLines lines={r.evidence} onChange={(evidence) => setReq(i, { evidence })} />
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="space-y-2">
                  <SubHeading title="Action item templates" hint="the measure to take if it isn't met" />
                  <Templates items={r.action_templates} onChange={(action_templates) => setReq(i, { action_templates })} addLabel="Add action item"
                    titlePlaceholder="e.g. Introduce quarterly access reviews" descPlaceholder="Description: the measure to take and what done looks like" />
                </div>
                <div className="space-y-2">
                  <SubHeading title="Risk templates" hint="the risk if it isn't met" />
                  <Templates items={r.risk_templates} onChange={(risk_templates) => setReq(i, { risk_templates })} addLabel="Add risk"
                    titlePlaceholder="e.g. Former staff keep access" descPlaceholder="Description: what could happen, and the impact" />
                </div>
              </div>
              <div className="space-y-2">
                <SubHeading title="Framework clauses" hint="mapped as structured clause links" />
                <div className="flex flex-wrap items-center gap-1.5">
                  {r.clauses.map((c) => (
                    <span key={c.id} className="inline-flex items-center gap-1.5 rounded-md border bg-muted/50 py-0.5 pl-1 pr-1 text-xs" title={c.title}>
                      <FrameworkBadge code={c.framework_code} />
                      <span className="font-mono">{c.ref}</span>
                      <button onClick={() => setReq(i, { clauses: r.clauses.filter((x) => x.id !== c.id) })} className="rounded p-0.5 hover:bg-background" aria-label={`Remove ${c.ref}`}>
                        <X className="size-3" />
                      </button>
                    </span>
                  ))}
                  <ClausePicker selected={r.clauses} onAdd={(c) => setReq(i, { clauses: [...r.clauses, c] })} />
                </div>
              </div>
              {problem && <p className="text-xs text-muted-foreground">Before this can be saved: {problem}</p>}
            </CardContent>
            </div>
            </div>
          </Card>
          );
        })}
        <Button variant="outline" className="w-full border-dashed" disabled={value.requirements.length >= MAX_REQUIREMENTS}
          onClick={() => { const r = blankRequirement(); set("requirements", [...value.requirements, r]); setOpen((o) => new Set(o).add(r.key)); }}>
          <Plus /> {value.requirements.length >= MAX_REQUIREMENTS ? `A control can have at most ${MAX_REQUIREMENTS} requirements` : "Add requirement"}
        </Button>
      </div>
    </div>
  );
}
