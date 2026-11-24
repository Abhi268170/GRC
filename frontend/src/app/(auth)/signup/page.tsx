"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DetailsFields, EMPTY_DETAILS, SizePicker, addressLine, fromRegister, hostname, type DetailsForm } from "@/components/app/company/details";
import { FindCompany } from "@/components/app/company/find-company";
import { IndustryPicker } from "@/components/app/company/industry-picker";
import { Field } from "@/components/app/field";
import { PasswordInput } from "@/components/app/password-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage } from "@/lib/api";
import type { CompanyProfile, Me, NogaCandidate } from "@/lib/types";

// find: search the register. manual: the company isn't in it. confirm: check the details, industry and size.
// account: name, email, password.
type Step = "find" | "manual" | "confirm" | "account";

const HEADINGS: Record<Step, { n: number; title: string; text: string }> = {
  find: { n: 1, title: "Find your company", text: "Pick it from the list and we'll fill in the details for you." },
  manual: { n: 1, title: "Tell us about your company", text: "Just the basics. We use this to tailor your assessments." },
  confirm: { n: 2, title: "Does this look right?", text: "Change anything that isn't. It is saved when you create the workspace." },
  account: { n: 3, title: "Create your account", text: "You'll be the admin for your company's workspace." },
};

export default function SignupPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("find");
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<CompanyProfile | null>(null); // the register entry the details were filled in from
  const [name, setName] = useState("");
  const [details, setDetails] = useState<DetailsForm>(EMPTY_DETAILS);
  const [editing, setEditing] = useState(false);
  const [classified, setClassified] = useState<string | null>(null); // the description the suggestions were made from
  const [suggestions, setSuggestions] = useState<NogaCandidate[]>([]);
  const [industry, setIndustry] = useState<NogaCandidate | null>(null);
  const [size, setSize] = useState("");
  const [account, setAccount] = useState({ full_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const heading = HEADINGS[step];
  const manualReady = name.trim().length >= 2 && details.description.trim().length >= 10;
  const confirmReady = name.trim().length >= 2 && industry !== null && size !== "";

  function go(next: Step) {
    setError(null);
    setStep(next);
  }

  function picked(company: CompanyProfile) {
    setFound(company);
    setName(company.name);
    setDetails(fromRegister(company));
    setEditing(false);
    setSuggestions(company.industries);
    setIndustry(company.industries[0] ?? null);
    setSize(company.employee_range ?? "");
    setClassified(null);
    go("confirm");
  }

  function enterByHand() {
    if (found) {
      // What was filled in for the company picked before doesn't apply to this one.
      setFound(null);
      setName(query.trim());
      setDetails(EMPTY_DETAILS);
      setSuggestions([]);
      setIndustry(null);
      setSize("");
      setClassified(null);
    } else if (!name) {
      setName(query.trim());
    }
    setEditing(false);
    go("manual");
  }

  async function describeCompany() {
    const description = details.description.trim();
    if (classified !== description) {
      setBusy(true);
      let suggested: NogaCandidate[] = [];
      try {
        suggested = await api<NogaCandidate[]>("/company/classify", { body: { description, company_name: name.trim() } });
      } catch {
        // No suggestion: the industry can still be searched for on the next step.
      }
      setBusy(false);
      setClassified(description);
      setSuggestions(suggested);
      setIndustry(suggested[0] ?? null);
    }
    go("confirm");
  }

  async function createWorkspace() {
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/signup", {
        body: { company_name: name.trim(), noga_code: industry?.code, employee_count: size, details, ...account },
      });
      qc.clear(); // nothing cached for a previous user may be shown to this one
      qc.setQueryData(["me"], me);
      router.replace("/app");
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      setBusy(false);
      if (message.toLowerCase().includes("web address")) {
        // The one detail the server checks: take the user back to where it can be fixed.
        setEditing(true);
        setStep("confirm");
      }
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (step === "manual" && manualReady) void describeCompany();
    else if (step === "confirm" && confirmReady) go("account");
    else if (step === "account") void createWorkspace();
  }

  const summary = [
    [details.legal_form, details.registration_number].filter(Boolean).join(" · "),
    addressLine(details),
    details.website ? hostname(details.website) : "",
  ].filter(Boolean);
  const headcountHint = found?.employees && found.employee_range === size
    ? `Public data says about ${found.employees.toLocaleString("en")}${found.employees_year ? ` (${found.employees_year})` : ""}. Change it if that's wrong.`
    : undefined;

  return (
    <div className="space-y-8" data-wide>
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Step {heading.n} of 3</p>
        <h2 className="display text-4xl">{heading.title}</h2>
        <p className="text-sm text-muted-foreground">{heading.text}</p>
      </div>
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {step === "find" && <FindCompany query={query} onQuery={setQuery} onPicked={picked} onManual={enterByHand} />}

        {step === "manual" && (
          <>
            <Field label="Company name" htmlFor="company">
              <Input id="company" autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="What does your company do?" htmlFor="description" hint="One sentence is enough. We use it to suggest your industry.">
              <Textarea
                id="description"
                required
                maxLength={2000}
                placeholder="We build accounting software for small businesses."
                value={details.description}
                onChange={(e) => setDetails((d) => ({ ...d, description: e.target.value }))}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-11" aria-label="Back to the search" onClick={() => go("find")}>
                <ArrowLeft />
              </Button>
              <Button type="submit" className="h-11 flex-1" disabled={!manualReady || busy}>
                {busy ? <Loader2 className="animate-spin" /> : null} Continue {!busy && <ArrowRight />}
              </Button>
            </div>
          </>
        )}

        {step === "confirm" && (
          <>
            {editing ? (
              <div className="space-y-4 rounded-lg border border-border p-4">
                <Field label="Company name" htmlFor="company-name">
                  <Input id="company-name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
                </Field>
                <DetailsFields value={details} onChange={setDetails} wide />
                <Button type="button" variant="outline" className="w-full" onClick={() => setEditing(false)}>Done</Button>
              </div>
            ) : (
              <div className="flex items-start gap-3 rounded-lg border border-border px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{name.trim()}</p>
                  <div className="mt-1 space-y-0.5 text-sm text-muted-foreground">
                    {summary.map((line) => <p key={line}>{line}</p>)}
                    {summary.length === 0 && <p>No address or website yet.</p>}
                  </div>
                </div>
                <button type="button" onClick={() => setEditing(true)} className="shrink-0 text-sm font-medium text-primary hover:underline">
                  {summary.length === 0 ? "Add details" : "Edit"}
                </button>
              </div>
            )}
            <Field label="Industry">
              <IndustryPicker
                key={found?.uid ?? classified ?? "manual"}
                value={industry}
                suggestions={suggestions}
                suggestedFrom={found ? "Suggested from your commercial register entry:" : "Suggested from your description:"}
                onChange={setIndustry}
              />
            </Field>
            <Field label="Number of employees" hint={headcountHint}>
              <SizePicker value={size} onChange={setSize} />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-11" aria-label="Back" onClick={() => go(found ? "find" : "manual")}>
                <ArrowLeft />
              </Button>
              <Button type="submit" className="h-11 flex-1" disabled={!confirmReady}>
                Continue <ArrowRight />
              </Button>
            </div>
          </>
        )}

        {step === "account" && (
          <>
            <Field label="Your name" htmlFor="name">
              <Input id="name" autoFocus required autoComplete="name" value={account.full_name} onChange={(e) => setAccount((a) => ({ ...a, full_name: e.target.value }))} />
            </Field>
            <Field label="Work email" htmlFor="email">
              <Input id="email" type="email" autoComplete="email" required value={account.email} onChange={(e) => setAccount((a) => ({ ...a, email: e.target.value }))} />
            </Field>
            <Field label="Password" htmlFor="password" hint="At least 10 characters.">
              <PasswordInput id="password" autoComplete="new-password" required minLength={10} value={account.password} onChange={(e) => setAccount((a) => ({ ...a, password: e.target.value }))} />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-11" aria-label="Back" onClick={() => go("confirm")}>
                <ArrowLeft />
              </Button>
              <Button type="submit" className="h-11 flex-1" disabled={busy}>
                {busy && <Loader2 className="animate-spin" />} {busy ? "Setting up your workspace…" : "Create workspace"}
              </Button>
            </div>
          </>
        )}
      </form>
      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-primary hover:underline">Sign in</Link>
      </p>
    </div>
  );
}
