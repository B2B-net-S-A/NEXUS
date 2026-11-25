"use client";

import { useState } from "react";
import { AlertTriangle, Check, Pencil, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  changeKindLabel,
  changeNumbers,
  changePlace,
  effectiveChange,
  insertedParagraphs,
  orderChanges,
  paragraphPieces,
  type ChangeEdit,
  type Decision,
  type RedlineChange,
  type RedlineParagraph,
  type RedlineSource,
} from "@/lib/legal-redline";
import { cn } from "@/lib/utils";

export interface RedlineReviewProps {
  paragraphs: readonly RedlineParagraph[];
  changes: readonly RedlineChange[];
  decisions: Record<string, Decision>;
  edits: Record<string, ChangeEdit>;
  notes: readonly string[];
  dropped: readonly { paragraph: number | null; reason: string }[];
  onDecide: (changeId: string, decision: Decision) => void;
  onEdit: (changeId: string, edit: ChangeEdit) => void;
}

function Mark({ n }: { n: number | undefined }) {
  if (n == null) return null;
  return (
    <sup className="ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
      {n}
    </sup>
  );
}

const SOURCE_TONE: Record<string, string> = {
  law: "border-info/30 bg-info-muted text-info-muted-foreground",
  contract: "border-primary/25 bg-primary/5 text-primary",
  client: "border-border bg-muted/60 text-foreground",
};

export function SourceChip({ source }: { source: RedlineSource }) {
  const ok = source.state === "ok";
  return (
    <span
      title={source.quote ? `„${source.quote}”` : undefined}
      className={cn(
        "mr-1 inline-flex items-center gap-1 rounded border px-1.5 py-px align-baseline text-[11px] font-medium",
        ok ? (SOURCE_TONE[source.kind] ?? SOURCE_TONE.client) : "border-warning/30 bg-warning-muted text-warning-muted-foreground",
      )}
    >
      {ok ? (
        <Check className="size-3" aria-label="cytat sprawdzony ze źródłem" />
      ) : (
        <AlertTriangle className="size-3" aria-label="cytat bez pokrycia w źródle" />
      )}
      {source.label || source.ref}
      {!ok && <span className="font-normal">— bez pokrycia</span>}
    </span>
  );
}

function DocumentText({
  paragraphs,
  changes,
  decisions,
  edits,
  numbers,
}: {
  paragraphs: readonly RedlineParagraph[];
  changes: readonly RedlineChange[];
  decisions: Record<string, Decision>;
  edits: Record<string, ChangeEdit>;
  numbers: Map<string, number>;
}) {
  const inserted = (index: number, position: "before" | "after") =>
    insertedParagraphs(index, changes, decisions, edits, position).map(({ change, decision }) => (
      <p key={change.id}>
        <ins
          className={cn(
            "bg-success-muted text-success-muted-foreground decoration-success",
            decision === "accepted" && "font-medium",
          )}
        >
          {change.new_text}
        </ins>
        <Mark n={numbers.get(change.id)} />
      </p>
    ));

  return (
    <article
      aria-label="Tekst dokumentu ze zmianami"
      className="space-y-2.5 rounded-lg border border-border bg-background px-6 py-5 text-[13.5px] leading-relaxed"
    >
      {paragraphs.map((paragraph) => {
        const pieces = paragraphPieces(paragraph, changes, decisions, edits);
        const empty = !paragraph.text.trim() && pieces.length <= 1;
        const before = inserted(paragraph.index, "before");
        const after = inserted(paragraph.index, "after");
        if (empty && before.length === 0 && after.length === 0) return null;
        // Numer zmiany stoi za jej ostatnim kawałkiem w akapicie (skreślenie + wstawka = jeden numer).
        const lastPiece = new Map<string, number>();
        pieces.forEach((piece, i) => {
          if (piece.kind !== "text") lastPiece.set(piece.changeId, i);
        });
        return (
          <div key={paragraph.index} className="space-y-2.5">
            {before}
            {!empty && (
              <p
                className={cn(
                  "whitespace-pre-wrap",
                  paragraph.heading && "pt-1 text-center font-semibold",
                  paragraph.in_table && "border-l-2 border-border pl-2 text-[13px]",
                )}
              >
                {pieces.map((piece, i) => {
                  if (piece.kind === "text") return <span key={i}>{piece.text}</span>;
                  const showMark = lastPiece.get(piece.changeId) === i;
                  const Tag = piece.kind === "ins" ? "ins" : "del";
                  return (
                    <span key={i}>
                      <Tag
                        className={cn(
                          piece.kind === "ins"
                            ? "bg-success-muted text-success-muted-foreground decoration-success"
                            : "bg-destructive-muted text-destructive-muted-foreground",
                          piece.decision === "accepted" && "font-medium",
                        )}
                      >
                        {piece.text}
                      </Tag>
                      {showMark && <Mark n={numbers.get(piece.changeId)} />}
                    </span>
                  );
                })}
              </p>
            )}
            {after}
          </div>
        );
      })}
    </article>
  );
}

function ChangeCard({
  change: raw,
  n,
  place,
  decision,
  edit,
  onDecide,
  onEdit,
}: {
  change: RedlineChange;
  n: number | undefined;
  place: string;
  decision: Decision;
  edit: ChangeEdit | undefined;
  onDecide: (decision: Decision) => void;
  onEdit: (edit: ChangeEdit) => void;
}) {
  const change = effectiveChange(raw, edit);
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(change.new_text);
  const [draftReason, setDraftReason] = useState(change.reason);
  const canEditText = change.kind !== "delete_paragraph";
  const unverified = raw.sources.filter((s) => s.state !== "ok").length;

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-2.5",
        decision === "accepted" ? "border-success/40" : decision === "rejected" ? "border-border opacity-70" : "border-border",
      )}
    >
      <div className="flex items-center gap-2">
        <Mark n={n} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold" title={place}>
          {place}
        </span>
        <Badge variant="neutral" size="sm">
          {changeKindLabel(change)}
        </Badge>
      </div>
      {change.reason && <p className="mt-1 text-[12.5px] leading-snug text-muted-foreground">{change.reason}</p>}
      {change.sources.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-y-1">
          {change.sources.map((source, i) => (
            <SourceChip key={`${source.ref}-${i}`} source={source} />
          ))}
        </div>
      )}
      {change.blocked && (
        <p className="mt-1.5 flex items-start gap-1.5 text-[12px] text-warning-muted-foreground">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          Cytat nie zgadza się ze źródłem, więc tej zmiany nie da się przyjąć. „Zmień” usuwa niesprawdzony cytat
          {unverified > 1 ? "y" : ""} — zmiana idzie wtedy pod Twoim powodem.
        </p>
      )}

      {editing ? (
        <div className="mt-2 space-y-1.5">
          {canEditText && (
            <Textarea
              aria-label="Nowy tekst zmiany"
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              rows={3}
              className="text-[13px]"
            />
          )}
          <Input
            aria-label="Powód zmiany (trafia do komentarza w Wordzie)"
            value={draftReason}
            onChange={(e) => setDraftReason(e.target.value)}
            placeholder="Powód (komentarz w Wordzie)"
            className="h-8 text-[13px]"
          />
          <div className="flex gap-1.5">
            <Button
              size="sm"
              className="h-7"
              disabled={canEditText && change.kind === "insert_paragraph" && !draftText.trim()}
              onClick={() => {
                onEdit({ new_text: canEditText ? draftText : change.new_text, reason: draftReason });
                setEditing(false);
              }}
            >
              Zapisz zmianę
            </Button>
            <Button size="sm" variant="ghost" className="h-7" onClick={() => setEditing(false)}>
              Anuluj
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {decision === "pending" ? (
            <>
              <Button
                size="sm"
                variant="outline"
                className="h-7"
                disabled={change.blocked}
                onClick={() => onDecide("accepted")}
              >
                <Check className="mr-1 size-3" aria-hidden="true" /> Przyjmij
              </Button>
              <Button size="sm" variant="ghost" className="h-7" onClick={() => onDecide("rejected")}>
                <X className="mr-1 size-3" aria-hidden="true" /> Odrzuć
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7"
                onClick={() => {
                  setDraftText(change.new_text);
                  setDraftReason(change.reason);
                  setEditing(true);
                }}
              >
                <Pencil className="mr-1 size-3" aria-hidden="true" /> Zmień
              </Button>
            </>
          ) : (
            <>
              <Badge variant={decision === "accepted" ? "success" : "neutral"} size="sm">
                {decision === "accepted" ? "Przyjęta" : "Odrzucona"}
              </Badge>
              <Button size="sm" variant="ghost" className="h-7" onClick={() => onDecide("pending")}>
                <RotateCcw className="mr-1 size-3" aria-hidden="true" /> Cofnij
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Tekst dokumentu ze zmianami (wstawki, skreślenia, numery) i lista zmian
 * z „Przyjmij / Odrzuć / Zmień” — wygląd z makiety „Popraw dokument”.
 * Bez zapytań: stan i akcje przychodzą z góry (okno albo harness).
 */
export function RedlineReview({
  paragraphs,
  changes,
  decisions,
  edits,
  notes,
  dropped,
  onDecide,
  onEdit,
}: RedlineReviewProps) {
  const numbers = changeNumbers(changes);
  const ordered = orderChanges(changes);
  return (
    <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <DocumentText paragraphs={paragraphs} changes={changes} decisions={decisions} edits={edits} numbers={numbers} />
      <aside aria-label="Lista zmian" className="space-y-2">
        {ordered.map((change) => (
          <ChangeCard
            key={change.id}
            change={change}
            n={numbers.get(change.id)}
            place={changePlace(change, paragraphs)}
            decision={decisions[change.id] ?? "pending"}
            edit={edits[change.id]}
            onDecide={(decision) => onDecide(change.id, decision)}
            onEdit={(edit) => onEdit(change.id, edit)}
          />
        ))}
        {notes.map((note, i) => (
          <div
            key={i}
            className="rounded-lg border border-dashed border-border p-2.5 text-[12.5px] text-muted-foreground"
          >
            {note}
          </div>
        ))}
        {dropped.length > 0 && (
          <details className="rounded-lg border border-border p-2.5 text-[12.5px] text-muted-foreground">
            <summary className="cursor-pointer">
              Pominięte propozycje: {dropped.length} (nie pasowały do dokumentu)
            </summary>
            <ul className="mt-1.5 list-disc space-y-1 pl-4">
              {dropped.map((d, i) => (
                <li key={i}>
                  {d.paragraph != null ? `Akapit ${d.paragraph + 1}: ` : ""}
                  {d.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </aside>
    </div>
  );
}
