"use client";

import { useQuery } from "@tanstack/react-query";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field } from "@/components/app/field";
import { PageHeader } from "@/components/app/page";
import { ControlPicker } from "@/components/library/control-picker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { AssessmentVersionDetail, ControlSummary } from "@/lib/types";

export default function NewAssessmentPage() {
  const router = useRouter();
  const controls = useQuery({ queryKey: ["controls"], queryFn: () => api<ControlSummary[]>("/library/controls") });
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const chosen = (controls.data ?? []).filter((c) => picked.has(c.id));
  const domains = new Set(chosen.map((c) => c.domain_id)).size;
  const requirements = chosen.reduce((n, c) => n + c.requirement_count, 0);

  const create = useAction(
    () => api<AssessmentVersionDetail>("/assessments", { body: { title, description: description || null, control_ids: [...picked] } }),
    { invalidate: [["assessments"]], onSuccess: (v) => router.replace(`/admin/assessments/${v.id}`) },
  );

  return (
    <>
      <PageHeader back={{ href: "/admin/assessments", label: "Assessments" }} title="New assessment"
        description="Name it and choose the controls. The AI writes one opening question per domain, and the guide follows up on each topic during the assessment." />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardContent className="space-y-4">
              <Field label="Title" htmlFor="title"><Input id="title" placeholder="e.g. Cloud Security Readiness" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
              <Field label="Description" htmlFor="desc" hint="Shown to tenants in the catalog.">
                <Textarea id="desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
              </Field>
            </CardContent>
          </Card>
          <div>
            <h2 className="mb-3 font-medium">Controls</h2>
            <ControlPicker value={picked} onChange={setPicked} />
          </div>
        </div>
        <Card className="h-fit lg:sticky lg:top-20">
          <CardHeader><CardTitle className="text-base">Summary</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <dl className="grid grid-cols-3 gap-2 text-center">
              {[["Domains", domains], ["Controls", chosen.length], ["Requirements", requirements]].map(([k, v]) => (
                <div key={k} className="rounded-lg bg-muted/60 py-3">
                  <dd className="text-xl font-semibold">{v}</dd>
                  <dt className="text-xs text-muted-foreground">{k}</dt>
                </div>
              ))}
            </dl>
            <p className="text-sm text-muted-foreground">The AI writes one plain-language opening question per domain, covering all of its requirements. During the assessment, the guide asks follow-ups for anything an answer leaves out. You can edit or add questions before publishing.</p>
            <Button className="w-full" onClick={() => create.mutate(undefined)} disabled={title.trim().length < 3 || picked.size === 0 || create.isPending}>
              Create & write questions
            </Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
