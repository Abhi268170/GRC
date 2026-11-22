"use client";

import { ArrowUp, Ban, CheckCircle2, FileText, Loader2, Paperclip, PartyPopper, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { initials } from "@/lib/format";
import { useMe } from "@/lib/hooks";

import { RichText } from "./rich-text";
import type { ChatMessage, EvidenceFile, QuestionState, Workspace } from "@/lib/types";

function NaDialog({ question, onClose, onConfirm, busy }: { question: QuestionState; onClose: () => void; onConfirm: (reason: string) => void; busy: boolean }) {
  const [reason, setReason] = useState(question.proposed_na_reason ?? "");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Doesn't apply to you?</DialogTitle>
          <DialogDescription>The requirements this question covers will be marked not applicable, with your reason recorded.</DialogDescription>
        </DialogHeader>
        <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why doesn't it apply?" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onConfirm(reason)} disabled={reason.trim().length < 3 || busy}>Mark not applicable</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function QuestionCard({ q, current, editable, onNa }: { q: QuestionState; current: boolean; editable: boolean; onNa: () => void }) {
  return (
    <div className={`rounded-3xl p-5 animate-in fade-in-0 slide-in-from-bottom-2 duration-300 ease-smooth ${current ? "glass-brand text-black" : "bg-muted"}`}>
      <p className={`mb-2 flex items-center gap-1.5 text-xs ${current ? "text-black/70" : "text-muted-foreground"}`}>{q.kind === "follow_up" ? "Follow-up" : "Question"}</p>
      <p className={`leading-relaxed ${q.kind === "base" ? "text-lg" : "text-[15px]"}`}>{q.text}</p>
      {q.help_text && q.kind === "base" && <div className={`mt-3 text-xs ${current ? "text-black/70" : "text-muted-foreground"}`}><RichText text={q.help_text} /></div>}
      {current && q.proposed_na && (
        <div className="mt-3 rounded-2xl bg-white/60 px-3 py-2 text-xs">
          <span className="font-medium">This may not apply to you:</span> {q.proposed_na_reason}
        </div>
      )}
      {current && editable && q.kind === "base" && (
        <button onClick={onNa} className="mt-4 inline-flex items-center gap-1 rounded-full bg-white/60 px-3 py-1 text-xs text-black/70 hover:text-black">
          <Ban className="size-3" /> Doesn't apply to us
        </button>
      )}
    </div>
  );
}

function Bubble({ m }: { m: ChatMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[85%] space-y-1.5">
          {m.content && <div className="whitespace-pre-wrap rounded-3xl rounded-br-lg bg-primary px-4 py-3 text-sm text-primary-foreground">{m.content}</div>}
          {!!(m.data?.evidence_ids as string[] | undefined)?.length && (
            <p className="text-right text-xs text-muted-foreground"><Paperclip className="mr-1 inline size-3" />{(m.data!.evidence_ids as string[]).length} file(s) attached</p>
          )}
        </div>
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-medium">{initials(m.author?.full_name ?? "You")}</span>
      </div>
    );
  }
  const rated = (m.data?.rated as string[] | undefined) ?? [];
  return (
    <div className="flex gap-2">
      <div className="max-w-[85%] space-y-1.5">
        <div className="rounded-3xl rounded-bl-lg bg-muted px-4 py-3 text-sm leading-relaxed"><RichText text={m.content} /></div>
        {rated.length > 0 && (
          <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            Suggested ratings for {rated.map((k) => <Badge key={k} variant="outline" className="px-1.5 py-0 font-mono text-[10px]">{k}</Badge>)}
          </p>
        )}
      </div>
    </div>
  );
}

export type LiveTurn = { userText: string; reply: string; status: string | null };

function LiveReply({ live }: { live: LiveTurn }) {
  const { data: me } = useMe();
  const author = me ? { id: me.user.id, full_name: me.user.full_name } : null;
  return (
    <div className="space-y-4 animate-in fade-in-0 slide-in-from-bottom-1 duration-200 ease-smooth">
      {live.userText && <Bubble m={{ id: "pending", role: "user", content: live.userText, data: null, author, created_at: "" }} />}
      <div className="flex gap-2">
        <div className="max-w-[85%] space-y-1.5">
          {live.reply && (
            <div className="rounded-3xl rounded-bl-lg bg-muted px-4 py-3 text-sm leading-relaxed" data-streaming>
              <RichText text={live.reply} />
              <span className="mt-1 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-brand" />
            </div>
          )}
          {(!live.reply || live.status) && (
            <p className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => <span key={i} className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60" style={{ animationDelay: `${i * 150}ms` }} />)}
              </span>
              {live.status ?? "Reviewing your answer…"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function Chat({ ws, onSend, onUpload, onNa, live, naBusy }: {
  ws: Workspace; live: LiveTurn | null; naBusy: boolean;
  onSend: (text: string, evidence: string[]) => Promise<boolean>; onUpload: (f: File) => Promise<EvidenceFile | undefined>; onNa: (q: string, reason: string) => void;
}) {
  const [text, setText] = useState("");
  const [attached, setAttached] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [naFor, setNaFor] = useState<QuestionState | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const questions = new Map(ws.questions.map((q) => [q.id, q]));
  const evidence = new Map(ws.evidence.map((e) => [e.id, e]));
  const processing = attached.some((id) => evidence.get(id)?.processing_status !== "ready");

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [ws.messages.length, live?.reply.length, live?.status]);

  const send = async () => {
    if (live || processing || (!text.trim() && !attached.length)) return;
    const draft = { text, attached };
    setText("");
    setAttached([]);
    // Nothing is saved unless the whole turn succeeds, so a failed turn gives the message back.
    if (!(await onSend(draft.text.trim(), draft.attached))) {
      setText(draft.text);
      setAttached(draft.attached);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
        {ws.comments.filter((c) => !c.resolved).map((c) => (
          <div key={c.id} className="rounded-3xl bg-destructive/8 p-5 text-sm">
            <p className="mb-1 text-xs font-medium text-destructive">Reviewer comment from {c.author}</p>{c.comment}
          </div>
        ))}
        {ws.messages.map((m) => {
          const kind = m.data?.kind as string | undefined;
          if (kind === "question") {
            const q = questions.get(m.data!.run_question_id as string);
            return q ? <QuestionCard key={m.id} q={q} current={q.id === ws.current_question_id} editable={ws.editable} onNa={() => setNaFor(q)} /> : null;
          }
          if (kind === "answer_saved") {
            return (
              <p key={m.id} className="flex animate-in items-center justify-center gap-1.5 text-xs text-muted-foreground fade-in-0 duration-300 ease-smooth">
                <CheckCircle2 className="size-3.5 text-success" /> {m.data?.not_applicable ? "Marked not applicable" : "Answer saved"}
              </p>
            );
          }
          if (kind === "question_closed") {
            return (
              <p key={m.id} className="text-center text-xs text-muted-foreground">
                We've moved on to keep things short. Rate anything still open in the panel.
              </p>
            );
          }
          if (kind === "domain_done") {
            return (
              <div key={m.id} className="flex items-center gap-3 rounded-3xl bg-primary p-5 text-sm text-primary-foreground">
                <PartyPopper className="size-5 shrink-0 text-brand" />
                <span>All questions in this domain are answered. Confirm the ratings, then complete the domain.</span>
              </div>
            );
          }
          return <Bubble key={m.id} m={m} />;
        })}
        {live && <LiveReply live={live} />}
        <div ref={bottom} />
      </div>

      {ws.editable && ws.ai_paused ? (
        <div className="m-3 rounded-full bg-muted px-5 py-3 text-center text-sm text-muted-foreground">
          AI assistance for this assessment has reached its limit. Rate any remaining requirements in the panel.
        </div>
      ) : ws.editable ? (
        <div className="p-3 sm:p-4">
          {attached.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {attached.map((id) => {
                const e = evidence.get(id);
                return (
                  <span key={id} className="inline-flex items-center gap-1.5 rounded-full bg-muted py-1.5 pl-3 pr-1.5 text-xs">
                    {e?.processing_status === "ready" ? <FileText className="size-3.5" /> : e?.processing_status === "failed" ? <X className="size-3.5 text-destructive" /> : <Loader2 className="size-3.5 animate-spin" />}
                    <span className="max-w-48 truncate">{e?.filename ?? "Uploading…"}</span>
                    {e && e.processing_status !== "ready" && <span className="text-muted-foreground">{e.processing_status === "failed" ? "failed" : "reading…"}</span>}
                    <button onClick={() => setAttached((a) => a.filter((x) => x !== id))} className="rounded p-0.5 hover:bg-background" aria-label="Remove"><X className="size-3" /></button>
                  </span>
                );
              })}
            </div>
          )}
          <div className="flex items-end gap-2">
            <Button variant="outline" size="icon-lg" className="shrink-0" onClick={() => fileInput.current?.click()} disabled={uploading} aria-label="Attach evidence">
              {uploading ? <Loader2 className="animate-spin" /> : <Paperclip />}
            </Button>
            <input ref={fileInput} type="file" hidden accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg" onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              setUploading(true);
              const ev = await onUpload(f);
              setUploading(false);
              if (ev) setAttached((a) => (a.includes(ev.id) ? a : [...a, ev.id]));
            }} />
            <Textarea
              rows={1}
              maxLength={4000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={ws.current_question_id ? "Type your answer, ask for help, or attach evidence…" : "Ask a question or add more detail…"}
              className="max-h-40 min-h-11 flex-1 resize-none rounded-3xl px-5 py-3"
            />
            <Button size="icon-lg" className="shrink-0" onClick={send} disabled={live !== null || processing || (!text.trim() && !attached.length)} aria-label="Send">
              <ArrowUp />
            </Button>
          </div>
          <p className="mt-1.5 hidden text-center text-[11px] text-muted-foreground sm:block">Enter to send · Shift+Enter for a new line · Evidence is read once and reused across questions</p>
        </div>
      ) : (
        <div className="m-3 rounded-full bg-muted px-5 py-3 text-center text-sm text-muted-foreground">
          {ws.domain.status === "completed" ? "This domain is completed." : !ws.domain.can_work ? `This domain is assigned to ${ws.domain.assignee?.full_name}.` : "This assessment isn't open for answers."}
        </div>
      )}
      {naFor && <NaDialog question={naFor} busy={naBusy} onClose={() => setNaFor(null)} onConfirm={(reason) => { onNa(naFor.id, reason); setNaFor(null); }} />}
    </div>
  );
}
