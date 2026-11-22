"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/app/page";
import { ControlEditor, draftFrom, isValid, toPayload } from "@/components/library/control-editor";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { ControlDetail, Domain } from "@/lib/types";

export default function NewControlPage() {
  const router = useRouter();
  const domains = useQuery({ queryKey: ["domains"], queryFn: () => api<Domain[]>("/library/domains") });
  const [draft, setDraft] = useState(() => draftFrom(null));

  const create = useAction(
    () => api<ControlDetail>("/library/controls", { body: toPayload(draft) }),
    { invalidate: [["controls"], ["domains"]], success: "Control saved as a draft", onSuccess: (c) => router.replace(`/admin/library/controls/${c.id}`) },
  );

  return (
    <>
      <PageHeader
        back={{ href: "/admin/library", label: "Control library" }}
        title="New control"
        description="Controls start as drafts. The code is assigned from the domain when you save, e.g. IAM01.0001 for the first version of the first Identity & Access Management control."
        actions={<Button onClick={() => create.mutate(undefined)} disabled={!isValid(draft) || create.isPending}>Save draft</Button>}
      />
      <div className="space-y-6">
        <ControlEditor value={draft} onChange={setDraft} domains={domains.data ?? []} />
      </div>
    </>
  );
}
