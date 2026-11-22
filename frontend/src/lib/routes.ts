import type { Me } from "./types";

export function homeFor(me: Me): string {
  if (me.user.must_change_password) return "/change-password";
  return me.user.platform_role === "super_admin" ? "/admin" : "/app";
}
