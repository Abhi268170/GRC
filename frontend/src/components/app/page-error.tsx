"use client";

import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";

/** What a page shows when it can't load: a plain message, a way to try again, a way out. */
export function PageError({ error, reset, home = "/" }: { error: Error; reset: () => void; home?: string }) {
  const queries = useQueryErrorResetBoundary();
  const status = error instanceof ApiError ? error.status : null;
  const missing = status === 404 || status === 403;
  return (
    <div className="mx-auto flex min-h-[50vh] max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <h2 className="display text-3xl">{missing ? "We couldn't find that" : "This page didn't load"}</h2>
      <p className="text-sm text-muted-foreground">
        {missing
          ? "It doesn't exist, or you don't have access to it."
          : status === 0 || (status !== null && status >= 500)
            ? "The server didn't answer. It may be restarting; try again in a moment."
            : "Something went wrong on this page. Trying again usually helps."}
      </p>
      <div className="flex gap-2">
        {!missing && (
          <Button onClick={() => { queries.reset(); reset(); }}>Try again</Button>
        )}
        <Button variant="outline" asChild><Link href={home}>Go to the start page</Link></Button>
      </div>
    </div>
  );
}
