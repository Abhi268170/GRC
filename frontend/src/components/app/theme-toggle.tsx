"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { cn } from "@/lib/utils";

/** Sun/moon button that flips between light and dark mode. Both icons render and CSS picks one,
 *  so there's no hydration mismatch before the theme is known. */
export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <button
      type="button"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      aria-label="Switch between light and dark mode"
      title="Switch between light and dark mode"
      className={cn("relative flex size-9 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50", className)}
    >
      <Moon className="size-[18px] transition-[transform,opacity] duration-300 dark:-rotate-90 dark:scale-50 dark:opacity-0" />
      <Sun className="absolute size-[18px] rotate-90 scale-50 opacity-0 transition-[transform,opacity] duration-300 dark:rotate-0 dark:scale-100 dark:opacity-100" />
    </button>
  );
}
