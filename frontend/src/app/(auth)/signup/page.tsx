"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field } from "@/components/app/field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/app/password-input";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage } from "@/lib/api";
import type { Me } from "@/lib/types";

const INDUSTRIES = [
  "Software / SaaS", "Financial services", "Healthcare", "Retail / E-commerce", "Manufacturing",
  "Professional services", "Education", "Public sector", "Telecommunications", "Other",
];
const SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"];

export default function SignupPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [step, setStep] = useState<1 | 2>(1);
  const [form, setForm] = useState({ company_name: "", industry: "", employee_count: "", full_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const companyReady = form.company_name.trim().length >= 2 && form.industry && form.employee_count;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (step === 1) {
      if (companyReady) setStep(2);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/signup", { body: form });
      qc.setQueryData(["me"], me);
      router.replace("/app");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Step {step} of 2</p>
        <h2 className="display text-4xl">{step === 1 ? "Tell us about your company" : "Create your account"}</h2>
        <p className="text-sm text-muted-foreground">
          {step === 1 ? "Just the basics. We use this to tailor your assessments." : "You'll be the admin for your company's workspace."}
        </p>
      </div>
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {step === 1 ? (
          <>
            <Field label="Company name" htmlFor="company">
              <Input id="company" autoFocus required value={form.company_name} onChange={(e) => set("company_name")(e.target.value)} />
            </Field>
            <Field label="Industry">
              <Select value={form.industry} onValueChange={set("industry")}>
                <SelectTrigger className="w-full"><SelectValue placeholder="Select an industry" /></SelectTrigger>
                <SelectContent>{INDUSTRIES.map((i) => <SelectItem key={i} value={i}>{i}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Number of employees">
              <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-5">
                {SIZES.map((s) => (
                  <button
                    type="button"
                    key={s}
                    onClick={() => set("employee_count")(s)}
                    className={`h-10 rounded-full px-1 text-xs transition sm:text-sm ${form.employee_count === s ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70"}`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </Field>
            <Button type="submit" className="h-11 w-full" disabled={!companyReady}>
              Continue <ArrowRight />
            </Button>
          </>
        ) : (
          <>
            <Field label="Your name" htmlFor="name">
              <Input id="name" autoFocus required value={form.full_name} onChange={(e) => set("full_name")(e.target.value)} />
            </Field>
            <Field label="Work email" htmlFor="email">
              <Input id="email" type="email" autoComplete="email" required value={form.email} onChange={(e) => set("email")(e.target.value)} />
            </Field>
            <Field label="Password" htmlFor="password" hint="At least 10 characters.">
              <PasswordInput id="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={(e) => set("password")(e.target.value)} />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-11" onClick={() => setStep(1)}>
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
