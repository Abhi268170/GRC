"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardList } from "lucide-react";

import { CatalogCard } from "@/components/app/catalog";
import { EmptyState, ListSkeleton, PageHeader } from "@/components/app/page";
import { api } from "@/lib/api";
import type { CatalogItem } from "@/lib/types";

export default function CatalogPage() {
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogItem[]>("/assessments/catalog/published") });
  return (
    <>
      <PageHeader title="Assessments" description="Choose an assessment to start. The AI guides your team through every question." />
      {catalog.isLoading ? <ListSkeleton rows={3} /> : !catalog.data?.length ? (
        <EmptyState icon={ClipboardList} title="No assessments available yet" text="Check back soon." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {catalog.data.map((item) => <CatalogCard key={item.version_id} item={item} />)}
        </div>
      )}
    </>
  );
}
