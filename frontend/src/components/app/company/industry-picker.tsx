"use client";

import { Check, Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { NogaCandidate } from "@/lib/types";

function Row({ item, selected, onSelect }: { item: NogaCandidate; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition ${selected ? "bg-primary text-primary-foreground" : "bg-muted/60 hover:bg-muted"}`}
    >
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{item.label_en}</span>
        <span className={`block truncate text-xs ${selected ? "text-primary-foreground/75" : "text-muted-foreground"}`}>{item.section_label_en}</span>
      </span>
      {selected && <Check className="mt-0.5 size-4 shrink-0" />}
    </button>
  );
}

/** The company's industry (a NOGA 2025 code). Shows the chosen one; "Change" opens the suggestions
 *  and a search over the whole list. */
export function IndustryPicker({ value, suggestions, suggestedFrom, onChange }: {
  value: NogaCandidate | null;
  suggestions: NogaCandidate[];
  suggestedFrom: string;
  onChange: (value: NogaCandidate) => void;
}) {
  const [open, setOpen] = useState(value === null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<NogaCandidate[] | null>(null);
  const [searching, setSearching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const request = useRef<AbortController | null>(null);

  function cancel() {
    if (timer.current) clearTimeout(timer.current);
    request.current?.abort();
  }
  useEffect(() => cancel, []);

  function search(text: string) {
    setQuery(text);
    cancel();
    const q = text.trim();
    if (q.length < 2) {
      setFound(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    timer.current = setTimeout(async () => {
      const controller = new AbortController();
      request.current = controller;
      try {
        setFound(await api<NogaCandidate[]>(`/company/industries?q=${encodeURIComponent(q)}`, { signal: controller.signal }));
      } catch {
        if (controller.signal.aborted) return;
        setFound([]);
      }
      setSearching(false);
    }, 250);
  }

  function choose(item: NogaCandidate) {
    onChange(item);
    setOpen(false);
    setQuery("");
    setFound(null);
  }

  if (!open && value) {
    return (
      <div className="flex items-start gap-3 rounded-lg bg-muted/60 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{value.label_en}</p>
          <p className="truncate text-xs text-muted-foreground">{value.section_label_en}</p>
        </div>
        <button type="button" onClick={() => setOpen(true)} className="shrink-0 text-sm font-medium text-primary hover:underline">
          Change
        </button>
      </div>
    );
  }

  const list = found ?? suggestions;
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input aria-label="Search industries" placeholder="Search industries, e.g. software" className="pl-10"
          value={query}
          onChange={(e) => search(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); /* Enter must not submit the step */ }}
        />
        {searching && <Loader2 className="absolute right-3.5 top-1/2 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />}
      </div>
      {found === null && suggestions.length > 0 && <p className="text-xs text-muted-foreground">{suggestedFrom}</p>}
      {found !== null && found.length === 0 && !searching && <p className="text-xs text-muted-foreground">Nothing matches. Try another word.</p>}
      {list.length > 0 && (
        <ul className="max-h-56 space-y-1 overflow-y-auto" aria-label="Industries">
          {list.map((item) => (
            <li key={item.code}>
              <Row item={item} selected={value?.code === item.code} onSelect={() => choose(item)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
