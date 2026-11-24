"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Check, Loader2, MapPin, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { DescriptionField, DetailsFields, SizePicker, fromRegister, missingToConfirm, toForm, type DetailsForm } from "@/components/app/company/details";
import { FindCompany } from "@/components/app/company/find-company";
import { IndustryPicker } from "@/components/app/company/industry-picker";
import { Field } from "@/components/app/field";
import { ListSkeleton, PageHeader, Panel, PanelTitle } from "@/components/app/page";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAction, useMe } from "@/lib/hooks";
import type { CompanyProfile, CompanyProfileData, NogaCandidate } from "@/lib/types";

const KEY = ["company-profile"];

type Form = { name: string; details: DetailsForm; industry: NogaCandidate | null; size: string };

const formOf = (data: CompanyProfileData): Form => ({ name: data.name, details: toForm(data.details), industry: data.noga, size: data.employee_count ?? "" });

function ProfileForm({ data, canEdit }: { data: CompanyProfileData; canEdit: boolean }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [confirmed, setConfirmed] = useState({ at: data.verified_at, by: data.verified_by });
  const [saved, setSaved] = useState<Form>(() => formOf(data));
  const [form, setForm] = useState<Form>(saved);
  const [suggestions, setSuggestions] = useState<NogaCandidate[]>([]);
  const [filledFrom, setFilledFrom] = useState<string | null>(null); // the register entry the form was last filled in from
  const [lookup, setLookup] = useState(false);
  const [query, setQuery] = useState("");

  // confirm: the admin states the details are right and complete (asked once, before the first assessment).
  const save = useAction(
    (confirm: boolean) => api<CompanyProfileData>("/company/profile", {
      method: "PUT",
      body: { name: form.name.trim(), employee_count: form.size, noga_code: form.industry?.code ?? null, details: form.details, confirm },
    }),
    {
      invalidate: [["me"]], // the workspace name and whether the details are confirmed are read from there
      onSuccess: (out) => {
        const justConfirmed = !confirmed.at && Boolean(out.verified_at);
        qc.setQueryData(KEY, out);
        const next = formOf(out);
        setSaved(next);
        setForm(next);
        setFilledFrom(null);
        setConfirmed({ at: out.verified_at, by: out.verified_by });
        toast.success(justConfirmed ? "Company details confirmed" : "Company profile saved");
        // Sent here from "Start assessment": go back to where the user was.
        const back = new URLSearchParams(window.location.search).get("next");
        if (justConfirmed && back?.startsWith("/app/")) router.push(back);
      },
    },
  );

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const valid = form.name.trim().length >= 2 && form.size !== "";
  // An industry saved as free text (before codes were used) doesn't count: one has to be picked from the list.
  const missing = missingToConfirm(form.details, form.industry !== null);
  const complete = valid && missing.length === 0;

  function fill(company: CompanyProfile) {
    setForm((f) => ({
      name: company.name,
      details: fromRegister(company),
      industry: company.industries[0] ?? f.industry,
      size: company.employee_range ?? f.size,
    }));
    setSuggestions(company.industries);
    setFilledFrom(company.name);
    setLookup(false);
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!canEdit || save.isPending) return;
        if (!confirmed.at) {
          if (complete) save.mutate(true);
        } else if (dirty && complete) save.mutate(false);
      }}
    >
      <PageHeader
        eyebrow="Workspace"
        title="Company profile"
        description={canEdit
          ? "Who your company is and what it does. We use it to tailor your assessments. Nothing changes until you save."
          : "Who your company is and what it does. Only a workspace admin can change it."}
        meta={confirmed.at && (
          <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <Check className="size-4 text-foreground" /> Confirmed{confirmed.by ? ` by ${confirmed.by}` : ""} on {formatDate(confirmed.at)}
          </span>
        )}
        actions={canEdit && (
          <>
            <Button type="button" variant="outline" onClick={() => setLookup(true)}>
              <Search /> Fill in from the Swiss register
            </Button>
            {confirmed.at ? (
              <Button type="submit" disabled={!dirty || !complete || save.isPending}>
                {save.isPending && <Loader2 className="animate-spin" />} Save changes
              </Button>
            ) : (
              <>
                <Button type="button" variant="outline" disabled={!dirty || !valid || save.isPending} onClick={() => save.mutate(false)}>
                  Save for later
                </Button>
                <Button type="submit" disabled={!complete || save.isPending}>
                  {save.isPending ? <Loader2 className="animate-spin" /> : <Check />} Confirm details
                </Button>
              </>
            )}
          </>
        )}
      />

      {!confirmed.at && (
        <Alert className="mb-4">
          <AlertTitle>{canEdit ? "Please confirm your company details" : "These details aren't confirmed yet"}</AlertTitle>
          <AlertDescription>
            {canEdit
              ? "Check that everything below is right and complete, then choose Confirm details. You do this once, before your first assessment."
              : "A workspace admin needs to confirm them before the first assessment can start."}
            {canEdit && missing.length > 0 && <span className="mt-1 block font-medium text-foreground">Still needed: {missing.join(", ")}.</span>}
          </AlertDescription>
        </Alert>
      )}
      {confirmed.at && canEdit && missing.length > 0 && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>These can&apos;t be left empty: {missing.join(", ")}.</AlertDescription>
        </Alert>
      )}

      {filledFrom && (
        <Alert className="mb-4">
          <AlertDescription>
            Filled in from the commercial register entry of {filledFrom}. Check the details, change what isn&apos;t right, then save.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel className="space-y-5 p-6">
          <PanelTitle icon={Building2}>Company</PanelTitle>
          <Field label="Company name" htmlFor="profile-name">
            <Input id="profile-name" required maxLength={200} disabled={!canEdit} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </Field>
          <DescriptionField
            id="profile-description"
            disabled={!canEdit}
            value={form.details.description}
            onChange={(description) => setForm((f) => ({ ...f, details: { ...f.details, description } }))}
          />
          <Field label="Industry" hint={!form.industry && data.industry ? `Saved as "${data.industry}". Pick an industry from the list to replace it.` : undefined}>
            {canEdit ? (
              <IndustryPicker
                key={filledFrom ?? "saved"}
                value={form.industry}
                suggestions={suggestions}
                suggestedFrom="Suggested from the commercial register entry:"
                onChange={(industry) => setForm((f) => ({ ...f, industry }))}
              />
            ) : (
              <p className="rounded-lg bg-muted/60 px-3 py-2.5 text-sm">{form.industry?.label_en ?? data.industry ?? "Not set"}</p>
            )}
          </Field>
          <Field label="Number of employees">
            <SizePicker value={form.size} disabled={!canEdit} onChange={(size) => setForm((f) => ({ ...f, size }))} />
          </Field>
        </Panel>

        <Panel className="space-y-5 p-6">
          <PanelTitle icon={MapPin}>Registration and address</PanelTitle>
          <DetailsFields wide idPrefix="profile" disabled={!canEdit} value={form.details} onChange={(details) => setForm((f) => ({ ...f, details }))} />
        </Panel>
      </div>

      <Dialog open={lookup} onOpenChange={setLookup}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Find your company</DialogTitle>
            <DialogDescription>Pick it from the Swiss commercial register. The form is filled in for you to check; nothing is saved yet.</DialogDescription>
          </DialogHeader>
          <FindCompany query={query} onQuery={setQuery} onPicked={fill} onManual={() => setLookup(false)} manualLabel="Cancel" />
        </DialogContent>
      </Dialog>
    </form>
  );
}

export default function CompanyProfilePage() {
  const { data: me } = useMe();
  // Not refetched in the background: that would not touch the form, but a save must be the only thing that changes it.
  const profile = useQuery({ queryKey: KEY, queryFn: () => api<CompanyProfileData>("/company/profile"), staleTime: Infinity, refetchOnWindowFocus: false });
  if (!profile.data || !me) {
    return (
      <>
        <PageHeader eyebrow="Workspace" title="Company profile" />
        <ListSkeleton rows={2} />
      </>
    );
  }
  return <ProfileForm data={profile.data} canEdit={me.user.platform_role === "tenant_admin"} />;
}
