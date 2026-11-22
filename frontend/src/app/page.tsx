"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMe } from "@/lib/hooks";
import { homeFor } from "@/lib/routes";

export default function Index() {
  const router = useRouter();
  const { data, isError } = useMe();
  useEffect(() => {
    if (data) router.replace(homeFor(data));
    if (isError) router.replace("/login");
  }, [data, isError, router]);
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
