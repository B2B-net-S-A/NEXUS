"use client";

/**
 * Widok panelu pisma na stronie kontraktu (asystent prawny, część F).
 *
 * Bez zapytań — stan i akcje daje `LegalLetterPanel` (albo harness
 * `/preview/legal-letter`). Układ z makiety 25.11.2026: ostrzeżenie o formie,
 * fakty z terminem, treść pisma, cytaty, stopka „Zatwierdzam / mail / DOCX”.
 */

import Link from "next/link";
import { AlertTriangle, CheckCircle2, FileText, Mail, RefreshCw, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  CHECK_LABEL,
  approvalView,
  citationSummary,
  countsOf,
  type LetterCheck,
  type LetterDraft,
  type LetterKindDef,
  type LetterKindKey,
} from "@/lib/legal-letters";
import { cn } from "@/lib/utils";

export interface LetterPanelViewProps {
  kinds: readonly LetterKindDef[];
  kind: LetterKindKey;
  onKindChange: (kind: LetterKindKey) => void;
  draft: LetterDraft | null;
  loading: boolean;
  /** Błąd przygotowania szkicu (zdanie dla człowieka) — nie wygląda jak pusty szkic. */
  error: string | null;
  text: string;
  onTextChange: (text: string) => void;
  instruction: string;
  onInstructionChange: (value: string) => void;
  penaltyAmount: string;
  onPenaltyAmountChange: (value: string) => void;
  onPrepare: () => void;
  originalConfirmed: boolean;
  onConfirmOriginal: () => void;
  onSwitchToAgreement: () => void;
  approved: boolean;
  /** Cytaty po ostatnim „Zatwierdzam” (serwer sprawdza tekst po poprawkach). */
  approvedChecks: LetterCheck[] | null;
  busy: "approve" | "docx" | null;
  actionError: string | null;
  savedName: string | null;
  canSave: boolean;
  canMail: boolean;
  generatorHref: string | null;
  onApprove: () => void;
  onOpenMail: () => void;
  onSaveDocx: () => void;
}

const NEEDS_INPUT: readonly LetterKindKey[] = ["penalty_note", "client_letter"];

function CheckRow({ check }: { check: LetterCheck }) {
  const ok = check.status === "ok";
  return (
    <li className="flex items-start gap-2 text-[12.5px] leading-snug" data-check={check.status}>
      <Badge size="sm" variant={ok ? "success" : "danger"} className="mt-0.5 shrink-0">
        {ok ? "✓" : "!"} {check.citation.raw}
      </Badge>
      <span className={cn(ok ? "text-muted-foreground" : "text-destructive")}>
        {CHECK_LABEL[check.status]}
        {!ok && check.message ? ` — ${check.message}` : ""}
        {ok && check.source?.label ? ` · ${check.source.label}` : ""}
      </span>
    </li>
  );
}

export function LetterPanelView(props: LetterPanelViewProps) {
  const {
    kinds,
    kind,
    draft,
    loading,
    error,
    text,
    approved,
    busy,
  } = props;
  const def = kinds.find((k) => k.key === kind);
  const toClient = kind === "client_letter";
  const needsInput = NEEDS_INPUT.includes(kind);
  const approval = draft ? approvalView(draft, text, props.originalConfirmed) : null;
  const checks = props.approvedChecks ?? draft?.checks ?? [];
  const counts = countsOf(checks);
  const warning = draft?.warning ?? null;
  const showQuestion = warning?.level === "question" && !props.originalConfirmed;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="legal-letter-panel">
      <header className="flex flex-col gap-2 border-b border-border px-5 py-3 pr-12">
        <div className="flex items-center gap-2">
          <Scale aria-hidden className="size-4 text-primary" />
          <h2 className="text-base font-semibold">{toClient ? "Pismo do klienta" : "Pismo do Partnera"}</h2>
          <Badge variant="soft" size="sm" uppercase>
            {approved ? "Zatwierdzone" : "Szkic"}
          </Badge>
        </div>
        <Select value={kind} onValueChange={(value) => props.onKindChange(value as LetterKindKey)}>
          <SelectTrigger aria-label="Rodzaj pisma" className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {kinds.map((k) => (
              <SelectItem key={k.key} value={k.key}>
                {k.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[12.5px] text-muted-foreground">
          {def?.source === "template" ? "Wzór z Generatora wypełniony danymi z NEXUSA" : "Zdania asystenta, dane i terminy z NEXUSA"}
          {" · źródło: podpisana umowa z Dokumentów kontraktu, nie dzisiejszy wzór"}
        </p>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {needsInput && (
          <div className="space-y-2 rounded-lg border border-border bg-card px-3 py-2.5">
            {kind === "penalty_note" && (
              <label className="flex flex-wrap items-center gap-2 text-[12.5px]">
                <span className="text-muted-foreground">Kwota kary z umowy (zł)</span>
                <Input
                  aria-label="Kwota kary"
                  inputMode="decimal"
                  className="h-8 w-36"
                  value={props.penaltyAmount}
                  onChange={(e) => props.onPenaltyAmountChange(e.target.value)}
                />
              </label>
            )}
            <Textarea
              aria-label="Czego dotyczy pismo"
              rows={2}
              placeholder={toClient ? "Czego dotyczy pismo do klienta (bez nazwisk i kwot)" : "Powód kary (bez nazwisk i kwot)"}
              value={props.instruction}
              onChange={(e) => props.onInstructionChange(e.target.value)}
            />
            <Button size="sm" variant="outline" onClick={props.onPrepare} loading={loading} disabled={loading}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {draft ? "Przygotuj ponownie" : "Przygotuj szkic"}
            </Button>
          </div>
        )}

        {error && (
          <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-[12.5px] text-destructive">
            {error}
          </p>
        )}
        {loading && !draft && <p className="text-[12.5px] text-muted-foreground">Asystent przygotowuje szkic…</p>}

        {warning && (showQuestion || warning.level === "info") && (
          <div
            className="rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-[12.5px] leading-snug text-warning-muted-foreground"
            data-testid="letter-form-warning"
          >
            <div className="mb-1 flex items-center gap-1.5 font-semibold">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {warning.title}
            </div>
            {warning.message}
            {showQuestion && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" className="h-7 bg-background" onClick={props.onConfirmOriginal}>
                  To oryginał / podpis kwalifikowany
                </Button>
                <Button size="sm" variant="ghost" className="h-7" onClick={props.onSwitchToAgreement}>
                  Zamień na porozumienie
                </Button>
              </div>
            )}
          </div>
        )}

        {draft && draft.facts.length > 0 && (
          <div className="grid grid-cols-1 gap-2 text-[12.5px] sm:grid-cols-3">
            {draft.facts.map((fact) => (
              <div key={fact.label} className="rounded-md border border-border bg-card px-2.5 py-1.5">
                <div className="text-muted-foreground">{fact.label}</div>
                <div className="font-semibold">{fact.value}</div>
                {fact.note && (
                  <div
                    className={cn(
                      "text-[11.5px]",
                      fact.tone === "ok" && "text-success-muted-foreground",
                      fact.tone === "warn" && "text-warning-muted-foreground",
                      fact.tone === "plain" && "text-muted-foreground",
                    )}
                  >
                    {fact.tone === "ok" ? "✓ " : ""}
                    {fact.note}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {draft?.deadline_note && <p className="text-[12.5px] text-warning-muted-foreground">{draft.deadline_note}</p>}
        {draft && draft.steps.length > 0 && (
          <details className="text-[12px] text-muted-foreground">
            <summary className="cursor-pointer">Jak policzono termin</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {draft.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          </details>
        )}

        {draft && draft.lawyer_review.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5" data-testid="letter-lawyer">
            <Badge variant="warning" size="sm">
              do prawnika
            </Badge>
            <span className="text-[12px] text-muted-foreground">{draft.lawyer_review.join(", ")}</span>
          </div>
        )}

        {draft?.error && (
          <p className="rounded-lg border border-border bg-muted/50 px-3 py-2 text-[12.5px] text-muted-foreground">
            {draft.error}
          </p>
        )}

        {draft && (draft.text || draft.editable) && (
          <article className="rounded-md border border-border bg-card">
            {draft.editable ? (
              <Textarea
                aria-label="Treść pisma"
                className="min-h-[320px] border-0 font-sans text-[13.5px] leading-relaxed"
                value={text}
                onChange={(e) => props.onTextChange(e.target.value)}
                disabled={approved}
              />
            ) : (
              <pre className="whitespace-pre-wrap break-words px-5 py-4 font-sans text-[13.5px] leading-relaxed">{text}</pre>
            )}
          </article>
        )}
        {draft && !draft.editable && props.generatorHref && (
          <p className="text-[12px] text-muted-foreground">
            Skutki w kontrakcie (data końca, rejestr umów) daje dokument wydany w Generatorze —{" "}
            <Link href={props.generatorHref} className="font-medium text-primary hover:underline">
              Otwórz w Generatorze
            </Link>
            .
          </p>
        )}

        {checks.length > 0 && (
          <section aria-label="Cytaty" className="space-y-1">
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Cytaty</h3>
            <ul className="space-y-1">
              {checks.map((check, i) => (
                <CheckRow key={`${check.citation.raw}-${i}`} check={check} />
              ))}
            </ul>
          </section>
        )}

        {draft && !draft.text && draft.passages.length > 0 && (
          <section aria-label="Fragmenty źródeł" className="space-y-1">
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Fragmenty źródeł</h3>
            {draft.passages.map((p) => (
              <blockquote key={`${p.ref}-${p.text.slice(0, 20)}`} className="rounded-md border border-border bg-card px-3 py-2 text-[12.5px]">
                <div className="font-medium">{p.ref}</div>
                <div className="text-muted-foreground">{p.text}</div>
              </blockquote>
            ))}
          </section>
        )}
        {draft && draft.notes.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-[12px] text-muted-foreground">
            {draft.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
        {draft && <p className="text-[11.5px] text-muted-foreground">{draft.disclaimer}</p>}
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
        <Button
          size="sm"
          onClick={props.onApprove}
          disabled={!draft || approved || !approval?.canApprove || busy !== null}
          loading={busy === "approve"}
          title={approval?.reason ?? undefined}
        >
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> {approved ? "Zatwierdzone" : "Zatwierdzam"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={props.onOpenMail}
          disabled={!approved || !props.canMail || busy !== null}
          title={!approved ? "Najpierw „Zatwierdzam”." : undefined}
        >
          <Mail className="h-3.5 w-3.5" aria-hidden /> Otwórz w oknie maila
        </Button>
        {props.canSave && (
          <Button
            size="sm"
            variant="outline"
            onClick={props.onSaveDocx}
            disabled={!approved || busy !== null || props.savedName !== null}
            loading={busy === "docx"}
            title={!approved ? "Najpierw „Zatwierdzam”." : undefined}
          >
            <FileText className="h-3.5 w-3.5" aria-hidden /> DOCX do Dokumentów kontraktu
          </Button>
        )}
        <span className="ml-auto text-[11.5px] text-muted-foreground" data-testid="letter-summary">
          {draft ? citationSummary(counts) : "nic nie wysłano"}
        </span>
        {approval && !approval.canApprove && !approved && approval.reason && (
          <p className="w-full text-[12px] text-destructive" data-testid="letter-block-reason">
            {approval.reason}
          </p>
        )}
        {props.actionError && (
          <p role="alert" className="w-full text-[12px] text-destructive">
            {props.actionError}
          </p>
        )}
        {props.savedName && (
          <p className="w-full text-[12px] text-success-muted-foreground">
            Zapisano „{props.savedName}” w Dokumentach kontraktu (folder „Pisma asystenta”).
          </p>
        )}
      </footer>
    </div>
  );
}
