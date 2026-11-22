"use client";

import { BookOpen, ClipboardList, Database, LayoutDashboard, Library } from "lucide-react";

import { AppShell, type NavSection } from "@/components/app/shell";

const NAV: NavSection[] = [
  { items: [{ href: "/admin", label: "Overview", icon: LayoutDashboard, exact: true }] },
  {
    title: "Content",
    items: [
      { href: "/admin/library", label: "Control library", icon: Library },
      { href: "/admin/frameworks", label: "Frameworks", icon: BookOpen },
      { href: "/admin/assessments", label: "Assessments", icon: ClipboardList },
    ],
  },
  { title: "Settings", items: [{ href: "/admin/master-data", label: "Master data", icon: Database }] },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AppShell roles={["super_admin"]} sections={NAV}>{children}</AppShell>;
}
