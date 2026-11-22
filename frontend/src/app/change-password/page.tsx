"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field } from "@/components/app/field";
import { Logo } from "@/components/app/logo";
import { ThemeToggle } from "@/components/app/theme-toggle";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PasswordInput } from "@/components/app/password-input";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import { homeFor } from "@/lib/routes";
import type { Me } from "@/lib/types";

export default function ChangePasswordPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) return setError("The new passwords don't match");
    setBusy(true);
    setError(null);
    try {
      await api("/auth/change-password", { body: { current_password: current, new_password: next } });
      const fresh = await api<Me>("/auth/me");
      qc.setQueryData(["me"], fresh);
      router.replace(homeFor(fresh));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-6">
      <Logo className="h-8" />
      <Card className="relative w-full max-w-sm">
        <ThemeToggle className="absolute right-3 top-3" />
        <CardHeader>
          <CardTitle>Set a new password</CardTitle>
          <CardDescription>
            {me?.user.must_change_password ? "You signed in with a temporary password. Choose your own to continue." : "Choose a new password for your account."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
            <Field label="Current password" htmlFor="cur">
              <PasswordInput id="cur" required value={current} onChange={(e) => setCurrent(e.target.value)} />
            </Field>
            <Field label="New password" htmlFor="new" hint="At least 10 characters.">
              <PasswordInput id="new" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} />
            </Field>
            <Field label="Confirm new password" htmlFor="confirm">
              <PasswordInput id="confirm" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy && <Loader2 className="animate-spin" />} Save password
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
