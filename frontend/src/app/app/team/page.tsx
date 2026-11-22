"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Copy, KeyRound, MoreHorizontal, UserPlus } from "lucide-react";
import { useState } from "react";

import { Field } from "@/components/app/field";
import { ListSkeleton, PageHeader } from "@/components/app/page";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { formatDate, initials } from "@/lib/format";
import { useAction, useMe } from "@/lib/hooks";
import type { OrganisationalRole, User } from "@/lib/types";

const useRoles = () => useQuery({ queryKey: ["organisational-roles"], queryFn: () => api<OrganisationalRole[]>("/master-data/organisational-roles") });

type Created = { user: User; temporary_password: string };

function TempPassword({ created, onClose }: { created: Created; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share these sign-in details</DialogTitle>
          <DialogDescription>This temporary password is shown only once. {created.user.full_name} will set their own password on first sign-in.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 rounded-lg border bg-muted/40 p-4 text-sm">
          <div><p className="text-xs text-muted-foreground">Email</p><p className="font-medium">{created.user.email}</p></div>
          <div className="flex items-end justify-between gap-3">
            <div><p className="text-xs text-muted-foreground">Temporary password</p><p className="font-mono font-medium">{created.temporary_password}</p></div>
            <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(`${created.user.email}\n${created.temporary_password}`); setCopied(true); }}>
              {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
        <DialogFooter><Button onClick={onClose}>Done</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UserDialog({ user, onClose, onCreated }: { user: User | "new"; onClose: () => void; onCreated: (c: Created) => void }) {
  const roles = useRoles();
  const existing = user === "new" ? null : user;
  const [email, setEmail] = useState("");
  const [name, setName] = useState(existing?.full_name ?? "");
  const [role, setRole] = useState(existing?.organisational_role_id ?? "");
  const [admin, setAdmin] = useState(existing?.platform_role === "tenant_admin");
  const save = useAction(() => existing
    ? api(`/users/${existing.id}`, { method: "PUT", body: { full_name: name, organisational_role_id: role || null, is_admin: admin, is_active: existing.is_active } })
    : api<Created>("/users", { body: { email, full_name: name, organisational_role_id: role || null, is_admin: admin } }),
  { invalidate: [["users"]], success: existing ? "Saved" : undefined, onSuccess: (out) => { onClose(); if (!existing) onCreated(out as Created); } });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{existing ? "Edit team member" : "Add a team member"}</DialogTitle>
          {!existing && <DialogDescription>You'll get a temporary password to share with them.</DialogDescription>}
        </DialogHeader>
        <div className="space-y-4">
          <Field label="Full name" htmlFor="uname"><Input id="uname" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          {!existing && <Field label="Work email" htmlFor="uemail"><Input id="uemail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>}
          <Field label="Organisational role">
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="w-full"><SelectValue placeholder="Select a role" /></SelectTrigger>
              <SelectContent>{roles.data?.filter((r) => r.is_active || r.id === role).map((r) => <SelectItem key={r.id} value={r.id}>{r.name} ({r.abbreviation})</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <label className="flex items-center justify-between gap-4 rounded-lg border px-4 py-3">
            <span><span className="block text-sm font-medium">Workspace admin</span><span className="text-xs text-muted-foreground">Can manage the team and approve assessments.</span></span>
            <Switch checked={admin} onCheckedChange={setAdmin} />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={name.trim().length < 2 || (!existing && !email) || save.isPending}>{existing ? "Save" : "Add member"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function TeamPage() {
  const { data: me } = useMe();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const roles = useRoles();
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const reset = useAction((id: string) => api<Created>(`/users/${id}/reset-password`, { method: "POST" }), { onSuccess: setCreated });
  const toggleActive = useAction((u: User) => api(`/users/${u.id}`, { method: "PUT", body: { full_name: u.full_name, organisational_role_id: u.organisational_role_id, is_admin: u.platform_role === "tenant_admin", is_active: !u.is_active } }), {
    invalidate: [["users"]],
  });
  const roleLabel = (id: string | null) => roles.data?.find((r) => r.id === id)?.name;

  return (
    <>
      <PageHeader title="Team" description="People who can work on assessments. Any member can be assigned a domain to complete."
        actions={<Button onClick={() => setEditing("new")}><UserPlus /> Add member</Button>} />
      <Alert className="mb-6">
        <KeyRound />
        <AlertTitle>No emails are sent</AlertTitle>
        <AlertDescription>New members get a temporary password that you share with them. They choose their own on first sign-in.</AlertDescription>
      </Alert>
      {users.isLoading ? <ListSkeleton /> : (
        <div className="overflow-hidden rounded-3xl bg-card">
          {users.data?.map((u) => (
            <div key={u.id} className={`flex items-center gap-4 border-b px-5 py-3.5 last:border-0 ${u.is_active ? "" : "opacity-60"}`}>
              <Avatar className="size-9"><AvatarFallback className="bg-accent text-xs text-accent-foreground">{initials(u.full_name)}</AvatarFallback></Avatar>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {u.full_name}
                  {u.id === me?.user.id && <span className="text-xs font-normal text-muted-foreground">(you)</span>}
                </p>
                <p className="truncate text-xs text-muted-foreground">{u.email}</p>
              </div>
              <span className="hidden text-sm text-muted-foreground md:block">{roleLabel(u.organisational_role_id) ?? "—"}</span>
              <div className="hidden w-32 justify-end sm:flex">
                {u.platform_role === "tenant_admin" ? <Badge variant="secondary">Admin</Badge> : u.must_change_password ? <Badge variant="outline">Invited</Badge> : null}
                {!u.is_active && <Badge variant="outline">Deactivated</Badge>}
              </div>
              <span className="hidden w-28 text-right text-xs text-muted-foreground lg:block">{u.last_login_at ? `Active ${formatDate(u.last_login_at)}` : "Never signed in"}</span>
              <DropdownMenu>
                <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Member actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => setEditing(u)}>Edit</DropdownMenuItem>
                  {u.id !== me?.user.id && <DropdownMenuItem onClick={() => reset.mutate(u.id)}>Reset password</DropdownMenuItem>}
                  {u.id !== me?.user.id && (
                    <DropdownMenuItem variant={u.is_active ? "destructive" : "default"} onClick={() => toggleActive.mutate(u)}>{u.is_active ? "Deactivate" : "Reactivate"}</DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))}
        </div>
      )}
      {editing && <UserDialog key={editing === "new" ? "new" : editing.id} user={editing} onClose={() => setEditing(null)} onCreated={setCreated} />}
      {created && <TempPassword created={created} onClose={() => setCreated(null)} />}
    </>
  );
}
