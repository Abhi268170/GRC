import { ArrowUpRight } from "lucide-react";

import { Logo } from "@/components/app/logo";
import { ThemeToggle } from "@/components/app/theme-toggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen gap-4 bg-background p-4 lg:grid-cols-[1.15fr_1fr]">
      <aside className="relative hidden flex-col justify-between p-10 lg:flex">
        <Logo className="h-9 self-start" />
        <div className="space-y-10">
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">AI-guided compliance</p>
            <h1 className="display max-w-xl text-6xl">Assessments your team will actually finish.</h1>
          </div>
          <div className="relative h-56">
            {[2, 1].map((i) => (
              <div key={i} className="glass-brand absolute top-0 h-48 w-80 rounded-3xl opacity-50" style={{ left: `${i * 56}px`, top: `${i * 18}px`, transform: `scale(${1 - i * 0.06})` }} />
            ))}
            <div className="glass-brand relative h-52 w-96 rounded-3xl p-6 text-black">
              <div className="flex items-center justify-between text-sm"><span>Guided by AI</span><ArrowUpRight className="size-4" /></div>
              <p className="mt-8 text-2xl leading-snug">One conversation per domain. <span className="font-medium">Evidence read once</span>, reused everywhere.</p>
            </div>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">NIST CSF 2.0 · ISO/IEC 27001:2022</p>
      </aside>
      <main className="relative flex items-center justify-center rounded-[2rem] bg-card px-6 py-12">
        <ThemeToggle className="absolute right-4 top-4" />
        <div className="w-full max-w-sm">
          <Logo className="mb-10 block h-8 lg:hidden" />
          {children}
        </div>
      </main>
    </div>
  );
}
