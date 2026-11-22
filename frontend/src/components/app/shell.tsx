"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Loader2, LogOut, Menu, Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Logo } from "@/components/app/logo";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ApiError, api } from "@/lib/api";
import { formatDate, initials } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import { homeFor } from "@/lib/routes";
import type { Me, Notification, PlatformRole } from "@/lib/types";

export type NavItem = { href: string; label: string; icon: LucideIcon; exact?: boolean };
export type NavSection = { title?: string; items: NavItem[] };

function isActive(path: string, { href, exact }: NavItem) {
  return exact ? path === href : path === href || path.startsWith(`${href}/`);
}

/** Horizontal pill navigation; the active item is a black pill. */
function TopNav({ items }: { items: NavItem[] }) {
  const path = usePathname();
  return (
    <nav className="hidden items-center gap-1 lg:flex">
      {items.map((item) => (
        <Link key={item.href} href={item.href}
          className={`rounded-full px-4 py-2 text-sm transition-colors ${isActive(path, item) ? "bg-primary text-primary-foreground" : "text-foreground/75 hover:bg-card hover:text-foreground"}`}>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

function MobileNav({ sections, onNavigate }: { sections: NavSection[]; onNavigate: () => void }) {
  const path = usePathname();
  return (
    <nav className="space-y-6">
      {sections.map((section, i) => (
        <div key={i} className="space-y-1">
          {section.title && <p className="px-3 pb-1 text-xs uppercase tracking-wider text-muted-foreground">{section.title}</p>}
          {section.items.map((item) => {
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} onClick={onNavigate}
                className={`flex items-center gap-3 rounded-full px-4 py-2.5 text-sm ${isActive(path, item) ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
                <Icon className="size-4" />{item.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

const NOTIFICATION_TEXT: Record<string, (p: Record<string, unknown>) => string> = {
  assessment_deprecated: (p) => `A new version (v${p.new_version}) of "${p.assessment_title}" is available. Your current run continues on v${p.old_version}.`,
  domain_assigned: (p) => `You've been assigned "${p.domain_name}" in ${p.assessment_title}.`,
  changes_requested: (p) => `Changes were requested on "${p.domain_name}" in ${p.assessment_title}.`,
  run_submitted: (p) => `${p.assessment_title} is ready for review.`,
  run_approved: (p) => `${p.assessment_title} was approved.`,
};

function Notifications() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["notifications"], queryFn: () => api<Notification[]>("/notifications"), refetchInterval: 60_000, throwOnError: false });
  const unread = data.filter((n) => !n.read_at).length;
  return (
    <Popover onOpenChange={async (open) => {
      if (!open && unread) {
        await api("/notifications/read-all", { method: "POST" }).catch(() => {});
        qc.invalidateQueries({ queryKey: ["notifications"] });
      }
    }}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative bg-card hover:bg-card/70" aria-label="Notifications">
          <Bell />
          {unread > 0 && <span className="absolute right-2 top-2 size-2 rounded-full bg-brand ring-2 ring-card" />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="px-4 pb-2 pt-4 text-sm font-medium">Notifications</div>
        <div className="max-h-96 overflow-y-auto">
          {data.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">You're all caught up.</p>
          ) : (
            data.map((n) => (
              <div key={n.id} className="mx-2 mb-1 flex gap-3 rounded-xl px-3 py-2.5 hover:bg-muted">
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${n.read_at ? "bg-transparent" : "bg-brand"}`} />
                <div className="space-y-1">
                  <p className="text-sm">{NOTIFICATION_TEXT[n.type]?.(n.payload) ?? n.type}</p>
                  <p className="text-xs text-muted-foreground">{formatDate(n.created_at)}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function UserMenu({ me }: { me: Me }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { setTheme } = useTheme();
  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      // Even if the server can't be reached, this browser is signed out below.
    } finally {
      qc.clear();
      router.replace("/login");
    }
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-3 rounded-full py-1 pl-1 pr-2 text-left outline-none transition hover:bg-card focus-visible:ring-3 focus-visible:ring-ring/50" aria-label="Account menu">
          <Avatar className="size-9">
            <AvatarFallback className="bg-primary text-xs font-medium text-primary-foreground">{initials(me.user.full_name)}</AvatarFallback>
          </Avatar>
          <span className="hidden leading-tight sm:block">
            <span className="block text-sm font-medium">{me.user.full_name}</span>
            <span className="block text-xs text-muted-foreground">{ROLE_LABEL[me.user.platform_role]}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="font-medium">{me.user.full_name}</p>
          <p className="truncate text-xs text-muted-foreground">{me.user.email}</p>
          {me.tenant && <p className="mt-1 truncate text-xs text-muted-foreground">{me.tenant.name}</p>}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => setTheme("light")}><Sun /> Light</DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("dark")}><Moon /> Dark</DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("system")}><Monitor /> System</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push("/change-password")}>Change password</DropdownMenuItem>
        <DropdownMenuItem onClick={signOut}><LogOut /> Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const ROLE_LABEL: Record<PlatformRole, string> = { super_admin: "Platform admin", tenant_admin: "Workspace admin", tenant_user: "Team member" };

export function AppShell({ roles, sections, children }: { roles: PlatformRole[]; sections: NavSection[]; children: React.ReactNode }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me, error, refetch, isFetching } = useMe();
  // Only "not signed in" sends the user to the login page. A server restart or a network blip must not.
  const signedOut = error instanceof ApiError && error.status === 401;
  const [mobileOpen, setMobileOpen] = useState(false);
  const fullBleed = usePathname().includes("/domains/");
  const allowed = me && roles.includes(me.user.platform_role) && !me.user.must_change_password;

  useEffect(() => {
    if (signedOut) {
      qc.clear(); // nothing of the previous session may show up for the next person who signs in
      router.replace("/login");
    } else if (me && !allowed) router.replace(homeFor(me));
  }, [me, signedOut, allowed, router, qc]);

  if (!allowed) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        {error && !signedOut && !me ? (
          <>
            <p className="text-sm text-muted-foreground">We can&apos;t reach the server right now.</p>
            <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>Try again</Button>
          </>
        ) : (
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        )}
      </div>
    );
  }

  const items = sections.flatMap((x) => x.items);
  return (
    <div className="min-h-screen">
      {/* The header has the same width and height on every route, so the nav never shifts while navigating.
          Only the border colour differs (the full-bleed workspace gets a visible divider). */}
      <header className={`sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md transition-colors ${fullBleed ? "" : "border-transparent"}`}>
        <div className="mx-auto flex h-18 max-w-[87.5rem] items-center gap-6 px-4 lg:px-8">
          <Button variant="ghost" size="icon" className="bg-card lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu /></Button>
          <Link href={items[0]?.href ?? "/"} aria-label="TrustUp home" className="shrink-0"><Logo className="h-7" /></Link>
          <TopNav items={items} />
          <div className="flex-1" />
          {me.tenant && <span className="hidden rounded-full bg-card px-4 py-2 text-xs text-muted-foreground xl:block">{me.tenant.name}</span>}
          <Notifications />
          <UserMenu me={me} />
        </div>
      </header>
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 px-3 py-5">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Logo className="mx-3 mb-8 h-7 self-start" />
          <MobileNav sections={sections} onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>
      <main className={fullBleed ? "w-full" : "mx-auto w-full max-w-[87.5rem] px-4 pb-16 pt-6 lg:px-8"}>{children}</main>
    </div>
  );
}
