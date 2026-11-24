"use client";

import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { IntakeQuestion, RunDetail } from "@/lib/types";

export function Working({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-3xl bg-card px-6 py-20 text-center">
      <p className="font-medium">{title}</p>
      <p className="max-w-md text-sm text-muted-foreground">{text}</p>
      <Loader2 className="mt-2 size-5 animate-spin text-muted-foreground" />
    </div>
  );
}

const STACK_DEPTH = 3; // cards visible behind the current one

function IntakeCard({ q, index, total, answer, onAnswer, onBack, onNext, isLast, busy, offset }: {
  q: IntakeQuestion; index: number; total: number; answer: string; offset: number; isLast: boolean; busy: boolean;
  onAnswer: (v: string) => void; onBack: () => void; onNext: () => void;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const current = offset === 0;
  useEffect(() => {
    if (current) textarea.current?.focus({ preventScroll: true });
  }, [current]);

  // Behind the stack: offset down and scaled; already answered: slid out to the left.
  const style: React.CSSProperties =
    offset < 0
      ? { transform: "translateX(-115%) rotate(-6deg)", opacity: 0 }
      : { transform: `translateY(${offset * 14}px) scale(${1 - offset * 0.05})`, opacity: offset > STACK_DEPTH ? 0 : 1 - offset * 0.18 };

  return (
    <div
      inert={!current}
      aria-hidden={!current}
      style={{ ...style, zIndex: 50 - Math.abs(offset), gridArea: "1 / 1" }}
      className="flex origin-bottom flex-col rounded-3xl bg-card p-6 shadow-[0_24px_60px_-20px_rgb(0_0_0/0.35)] transition-[transform,opacity] duration-450 ease-smooth motion-reduce:transition-none sm:p-8"
    >
      <div className={`flex flex-1 flex-col transition-opacity duration-200 ${current ? "opacity-100" : "opacity-0"}`}>
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">Question {index + 1} of {total}</p>
        <div className="flex gap-1" aria-hidden>
          {Array.from({ length: total }).map((_, i) => (
            <span key={i} className={`h-1.5 rounded-full transition-all ${i < index ? "w-3 bg-primary" : i === index ? "w-6 bg-brand" : "w-3 bg-muted"}`} />
          ))}
        </div>
      </div>
      <h3 className="mt-6 text-2xl leading-snug tracking-tight">{q.text}</h3>
      {q.options.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-1.5">
          {q.options.map((o) => (
            <button key={o} type="button" onClick={() => onAnswer(answer === o ? "" : o)} aria-pressed={answer === o}
              className={`rounded-lg px-3.5 py-1.5 text-sm transition ${answer === o ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70"}`}>
              {o}
            </button>
          ))}
        </div>
      )}
      <Textarea
        ref={textarea}
        rows={3}
        className="mt-4"
        placeholder={q.hint ?? (q.options.length ? "Or describe it in your own words" : "Your answer")}
        value={answer}
        onChange={(e) => onAnswer(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onNext(); } }}
      />
      <div className="mt-auto flex items-center justify-between gap-3 pt-6">
        <Button variant="ghost" onClick={onBack} disabled={index === 0}><ArrowLeft /> Back</Button>
        <Button onClick={onNext} disabled={busy}>
          {isLast ? <>{busy && <Loader2 className="animate-spin" />} Tailor my assessment</> : <>Next <ArrowRight /></>}
        </Button>
      </div>
      </div>
    </div>
  );
}

export function IntakeView({ run }: { run: RunDetail }) {
  const intake = run.intake;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [step, setStep] = useState(0);
  const invalidate = [["run", run.id], ["runs"]];
  const submit = useAction(() => api(`/runs/${run.id}/intake`, { body: { answers } }), { invalidate });
  const skip = useAction(() => api(`/runs/${run.id}/intake/skip`, { method: "POST" }), { invalidate });

  const working = !intake || intake.status === "generating" || intake.status === "tailoring";
  const questions = intake?.questions ?? [];

  return (
    <Dialog open>
      <DialogContent
        showCloseButton={false}
        overlayClassName="bg-black/45 supports-backdrop-filter:backdrop-blur-sm"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
        className="max-w-[calc(100%-2rem)] gap-4 bg-transparent p-0 shadow-none ring-0 sm:max-w-xl"
      >
        <DialogTitle className="sr-only">A few quick questions before you start</DialogTitle>
        <DialogDescription className="sr-only">Your answers tailor the assessment to your company. You can skip this step.</DialogDescription>
        {working ? (
          <Working
            title={intake?.status === "tailoring" ? "Tailoring your assessment" : "Preparing a few quick questions"}
            text={intake?.status === "tailoring"
              ? "Rewording questions for your setup, ordering them, and flagging any that probably don't apply. Usually under a minute."
              : "To tailor this assessment, the AI is picking the context it needs about your company."}
          />
        ) : (
          <>
            <div className="flex items-center gap-2 px-1 text-sm text-white/90">
              A few quick questions to tailor your assessment
            </div>
            <div className="grid pb-12">
              {questions.map((q, i) => (
                <IntakeCard
                  key={q.id} q={q} index={i} total={questions.length} offset={i - step} isLast={i === questions.length - 1}
                  answer={answers[q.id] ?? ""} busy={submit.isPending}
                  onAnswer={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))}
                  onBack={() => setStep((n) => Math.max(0, n - 1))}
                  onNext={() => (i === questions.length - 1 ? submit.mutate(undefined) : setStep((n) => n + 1))}
                />
              ))}
            </div>
            <button type="button" onClick={() => skip.mutate(undefined)} disabled={skip.isPending}
              className="mx-auto text-sm text-white/80 underline-offset-4 hover:text-white hover:underline">
              Skip and use the standard questions
            </button>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
