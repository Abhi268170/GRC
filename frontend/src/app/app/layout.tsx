"use client";

import { Building2, ClipboardCheck, ClipboardList, Home, ListTodo, ShieldAlert, Users } from "lucide-react";

import { AppShell, type NavSection } from "@/components/app/shell";
import { useMe } from "@/lib/hooks";

export default function TenantLayout({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe();
  const nav: NavSection[] = [
    {
      items: [
        { href: "/app", label: "Home", icon: Home, exact: true },
        { href: "/app/runs", label: "My assessments", icon: ClipboardCheck },
        { href: "/app/assessments", label: "Catalog", icon: ClipboardList },
      ],
    },
    {
      title: "Registers",
      items: [
        { href: "/app/actions", label: "Action items", icon: ListTodo },
        { href: "/app/risks", label: "Risks", icon: ShieldAlert },
      ],
    },
    {
      title: "Workspace",
      items: [
        { href: "/app/company", label: "Company", icon: Building2 },
        ...(me?.user.platform_role === "tenant_admin" ? [{ href: "/app/team", label: "Team", icon: Users }] : []),
      ],
    },
  ];
  return <AppShell roles={["tenant_admin", "tenant_user"]} sections={nav}>{children}</AppShell>;
}
