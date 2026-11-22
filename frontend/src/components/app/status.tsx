import { Badge } from "@/components/ui/badge";
import type { VersionStatus } from "@/lib/types";

const STYLES: Record<VersionStatus, string> = {
  published: "border-success/30 bg-success/10 text-success",
  draft: "border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning",
  deprecated: "border-border bg-muted text-muted-foreground",
};

export function VersionBadge({ status, version }: { status: VersionStatus; version?: number }) {
  return (
    <Badge variant="outline" className={`gap-1 ${STYLES[status]}`}>
      {version !== undefined && <span className="font-mono">v{version}</span>}
      <span className="capitalize">{status}</span>
    </Badge>
  );
}

export function FrameworkBadge({ code }: { code: string }) {
  const label = code === "NIST-CSF" ? "NIST CSF" : code === "ISO-27001" ? "ISO 27001" : code;
  return <Badge variant="secondary" className="font-normal">{label}</Badge>;
}
