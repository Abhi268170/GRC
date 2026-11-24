import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Small label + oversized light title, as in the reference design. */
export function PageHeader({ title, eyebrow, description, actions, back, meta }: {
  title: React.ReactNode; eyebrow?: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode;
  back?: { href: string; label: string }; meta?: React.ReactNode;
}) {
  return (
    <div className="mb-8 pt-4">
      {back && (
        <Link href={back.href} className="mb-5 inline-flex items-center gap-2 rounded-lg bg-card px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground">
          <ArrowLeft className="size-3.5" /> {back.label}
        </Link>
      )}
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 space-y-3">
          {eyebrow && <p className="text-sm text-muted-foreground">{eyebrow}</p>}
          <h1 className="display text-4xl sm:text-5xl">{title}</h1>
          {description && <p className="max-w-2xl text-[15px] text-muted-foreground">{description}</p>}
          {meta && <div className="flex flex-wrap items-center gap-2 pt-1">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function Panel({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("rounded-3xl bg-card", className)} {...props} />;
}

export function PanelTitle({ icon: Icon, children, action }: { icon?: React.ComponentType<{ className?: string }>; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="flex items-center gap-2 text-[15px] text-muted-foreground">{Icon && <Icon className="size-4 text-foreground" />}{children}</p>
      {action}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, text, action }: {
  icon: React.ComponentType<{ className?: string }>; title: string; text?: string; action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-3xl bg-card px-6 py-20 text-center">
      <span className="mb-5 flex size-12 items-center justify-center rounded-xl bg-brand text-brand-foreground">
        <Icon className="size-5" />
      </span>
      <p className="text-lg font-medium">{title}</p>
      {text && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{text}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-20 w-full rounded-3xl" />)}
    </div>
  );
}

/** Big light number with a superscript unit, e.g. 2.4⁄4 or 72%. */
export function BigNumber({ value, unit, className = "" }: { value: React.ReactNode; unit?: string; className?: string }) {
  return (
    <span className={`display inline-flex items-start leading-none ${className}`}>
      <span>{value}</span>
      {unit && <span className="ml-1 pt-[0.08em] text-[0.32em] font-normal tracking-normal opacity-60">{unit}</span>}
    </span>
  );
}

export function Stat({ label, value, unit, hint, icon: Icon, children, href }: {
  label: string; value: React.ReactNode; unit?: string; hint?: React.ReactNode; icon?: React.ComponentType<{ className?: string }>;
  children?: React.ReactNode; href?: string;
}) {
  const body = (
    <>
      <PanelTitle icon={Icon}>{label}</PanelTitle>
      <div className="mt-6"><BigNumber value={value} unit={unit} className="text-5xl" /></div>
      {hint && <p className="mt-2 text-xs text-muted-foreground">{hint}</p>}
      {children && <div className="mt-5">{children}</div>}
    </>
  );
  return href ? (
    <Link href={href} className="block rounded-3xl bg-card p-6 transition hover:ring-2 hover:ring-brand/60">{body}</Link>
  ) : (
    <div className="rounded-3xl bg-card p-6">{body}</div>
  );
}

/** Black-filled progress with a lime marker and a hatched remainder, from the reference. */
export function SegmentBar({ value, max, className = "" }: { value: number; max: number; className?: string }) {
  const pct = max ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={`relative h-6 w-full overflow-hidden rounded-md bg-muted ${className}`}>
      <div className="absolute inset-y-0 left-0 flex transition-[width] duration-500 ease-smooth" style={{ width: `${pct}%` }}>
        <div className="h-full flex-1 rounded-l-md bg-primary" />
        {pct > 0 && <div className="h-full w-1.5 bg-brand" />}
      </div>
      <div className="absolute inset-y-1 right-1 w-1/5 bg-[repeating-linear-gradient(90deg,var(--border)_0_1px,transparent_1px_4px)]" style={{ display: pct >= 80 ? "none" : undefined }} />
    </div>
  );
}

/** Thin vertical "barcode" ticks: values 0..1, with highlighted ticks in lime. */
export function TickChart({ values, highlight = [], className = "" }: { values: number[]; highlight?: number[]; className?: string }) {
  return (
    <div className={`flex h-16 items-end gap-[3px] ${className}`}>
      {values.map((v, i) => (
        <span key={i} className={`w-[2px] shrink-0 rounded-full ${highlight.includes(i) ? "bg-brand" : v > 0.6 ? "bg-foreground" : "bg-foreground/25"}`}
          style={{ height: `${Math.max(8, v * 100)}%` }} />
      ))}
    </div>
  );
}
