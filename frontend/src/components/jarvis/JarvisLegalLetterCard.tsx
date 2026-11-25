"use client";

/** Szkic pisma od Jarvisa (`draft_legal_letter`, asystent prawny F) — nic nie
 *  wysłano. Zatwierdza i wysyła człowiek z panelu pisma na stronie kontraktu;
 *  treść to zwykły tekst z serwera, pokazany jako tekst, nie markdown. */

import Link from "next/link";
import { Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { JarvisLegalLetter } from "@/lib/jarvis/types";
import { citationSummary, letterKind } from "@/lib/legal-letters";

export function legalLetterHref(letter: Pick<JarvisLegalLetter, "contract_id" | "kind">): string {
  const kind = letterKind(letter.kind)?.key ?? "1";
  return `/contracts/${letter.contract_id}?pismo=${kind}`;
}

export function JarvisLegalLetterCard({ letter, onNavigate }: { letter: JarvisLegalLetter; onNavigate?: () => void }) {
  const label = letter.label || letterKind(letter.kind)?.label || "Pismo";
  const counts = { ok: letter.counts?.ok ?? 0, missing: letter.counts?.missing ?? 0, mismatch: letter.counts?.mismatch ?? 0 };
  return (
    <div className="rounded-lg border border-primary/30 bg-card p-3 shadow-xs" data-testid="jarvis-legal-letter">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
        <Scale className="h-3.5 w-3.5" aria-hidden /> Szkic pisma — nic nie wysłano
      </div>
      <p className="text-sm font-semibold text-foreground">{label}</p>
      {letter.subject && <p className="text-xs text-muted-foreground">Dotyczy: {letter.subject}</p>}
      {letter.text ? (
        <pre className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 px-2 py-1.5 font-sans text-xs text-foreground">
          {letter.text}
        </pre>
      ) : letter.error ? (
        <p className="mt-1.5 text-xs text-muted-foreground">{letter.error}</p>
      ) : null}
      {(letter.lawyer_review?.length ?? 0) > 0 && (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <Badge variant="warning" size="sm">
            do prawnika
          </Badge>
          {letter.lawyer_review?.join(", ")}
        </p>
      )}
      {letter.blocked && (letter.block_reasons?.length ?? 0) > 0 && (
        <p className="mt-1.5 text-xs text-destructive">Do poprawy przed zatwierdzeniem: {letter.block_reasons?.join(" ")}</p>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Button asChild size="sm">
          <Link href={legalLetterHref(letter)} onClick={onNavigate}>
            Otwórz panel pisma
          </Link>
        </Button>
        {letter.counts && <span className="text-[11px] text-muted-foreground">{citationSummary(counts)}</span>}
      </div>
    </div>
  );
}
