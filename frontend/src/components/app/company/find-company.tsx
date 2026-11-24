"use client";

import { Building2, Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { ApiError, api, errorMessage } from "@/lib/api";
import type { CompanyHit, CompanyProfile, CompanySearch } from "@/lib/types";

type State =
  | { status: "idle" | "loading" | "too_many" }
  | { status: "done"; results: CompanyHit[] }
  | { status: "error"; message: string };

const MIN_LETTERS = 3;
// One company (one number) can be registered under several names, one row each.
const rowKey = (hit: CompanyHit) => `${hit.uid}|${hit.name}|${hit.legal_seat ?? ""}`;

/** Type the company name, pick it from the commercial register. Used at sign-up and on the company profile page. */
export function FindCompany({ query, onQuery, onPicked, onManual, manualLabel = "My company isn't listed" }: {
  query: string;
  onQuery: (value: string) => void;
  onPicked: (company: CompanyProfile) => void;
  onManual: () => void;
  manualLabel?: string;
}) {
  const [state, setState] = useState<State>({ status: "idle" });
  const [picking, setPicking] = useState<string | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const request = useRef<AbortController | null>(null);

  function cancel() {
    if (timer.current) clearTimeout(timer.current);
    request.current?.abort();
  }
  useEffect(() => cancel, []);

  async function run(name: string) {
    const controller = new AbortController();
    request.current = controller;
    try {
      const found = await api<CompanySearch>("/company/search", { body: { name }, signal: controller.signal });
      setState(found.too_many ? { status: "too_many" } : { status: "done", results: found.results });
    } catch (e) {
      if (controller.signal.aborted) return;
      setState({ status: "error", message: errorMessage(e) });
    }
  }

  function change(value: string) {
    onQuery(value);
    setPickError(null);
    cancel();
    const name = value.trim();
    if (name.length < MIN_LETTERS) {
      setState({ status: "idle" });
      return;
    }
    setState({ status: "loading" });
    timer.current = setTimeout(() => run(name), 300); // wait until the typing pauses
  }

  async function pick(hit: CompanyHit) {
    setPicking(rowKey(hit));
    setPickError(null);
    try {
      onPicked(await api<CompanyProfile>("/company/enrich", { body: { uid: hit.uid, name: hit.name } }));
    } catch (e) {
      setPickError(e instanceof ApiError && e.status === 404 ? "That company is no longer in the register. Pick another one." : errorMessage(e));
      setPicking(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          autoFocus
          aria-label="Search the commercial register"
          placeholder="Company name"
          autoComplete="organization"
          className="h-11 pl-10"
          value={query}
          onChange={(e) => change(e.target.value)}
        />
        {state.status === "loading" && <Loader2 className="absolute right-3.5 top-1/2 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />}
      </div>

      {pickError && <p role="alert" className="text-sm text-destructive">{pickError}</p>}

      {state.status === "done" && state.results.length > 0 && (
        <ul className="max-h-72 space-y-1 overflow-y-auto" aria-label="Companies found">
          {state.results.map((hit) => (
            <li key={rowKey(hit)}>
              <button
                type="button"
                disabled={picking !== null}
                onClick={() => pick(hit)}
                className="flex w-full items-center gap-3 rounded-lg bg-muted/60 px-3 py-2.5 text-left transition hover:bg-muted disabled:opacity-60"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-card text-muted-foreground">
                  {picking === rowKey(hit) ? <Loader2 className="size-4 animate-spin" /> : <Building2 className="size-4" />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{hit.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {[hit.legal_seat, hit.legal_form].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="text-sm text-muted-foreground" aria-live="polite">
        {state.status === "idle" && "We search the Swiss commercial register as you type."}
        {state.status === "too_many" && "A lot of companies match. Keep typing to narrow it down."}
        {state.status === "done" && state.results.length === 0 && "No company with that name in the Swiss commercial register."}
        {state.status === "error" && state.message}
      </p>

      <button type="button" onClick={onManual} className="text-sm font-medium text-primary hover:underline">
        {manualLabel}
      </button>
    </div>
  );
}
