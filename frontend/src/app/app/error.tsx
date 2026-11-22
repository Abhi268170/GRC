"use client";

import { PageError } from "@/components/app/page-error";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return <PageError error={error} reset={reset} home="/app" />;
}
