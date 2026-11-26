"use client";

/**
 * Propozycja AI wyróżnika w „Stronie 1” nowego CV (decyzja Artura 26.11.2026).
 *
 * Wyróżnik ma trzy źródła: praca u klienta (automat), propozycja AI i wpis
 * rekrutera — ostatnie słowo ma rekruter. AI szuka w CV nagrody, wyróżnienia
 * albo certyfikatu z wymagań MUST z cytatem, który sprawdza kod
 * (`services/cv_page1_highlight_checks.py`). Propozycja stoi tu obok trybów
 * i nie trafia do CV, dopóki rekruter jej nie przyjmie („Przyjmij” =
 * `highlight.mode = "ai"`). „Odrzuć” usuwa ją na stałe, „Popraw jako własny”
 * przenosi jej słowa do „Własnego”.
 */

import { type ReactNode, useState } from "react";
import { Check, Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CvHighlightProposal, CvPage1Extras } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { plainText } from "@/lib/cv-page1-why";

export interface PendingProposal {
  /** Numer w `highlight_proposals` (tylko do klucza listy); zapis idzie po `proposal.key`. */
  index: number;
  proposal: CvHighlightProposal;
}

/** Sprawdzone propozycje do przyjęcia, bez tej, która już stoi na stronie 1. */
export function pendingProposals(extras: CvPage1Extras | null | undefined): PendingProposal[] {
  const accepted = extras?.highlight?.mode === "ai" ? extras.highlight.key : null;
  return (extras?.highlight_proposals ?? []).flatMap((proposal, index) =>
    proposal &&
    proposal.verified === true &&
    proposal.key &&
    proposal.label?.trim() &&
    proposal.text?.trim() &&
    proposal.key !== accepted
      ? [{ index, proposal }]
      : [],
  );
}

/** Czy AI już szukało w tym CV (lista jest, choćby pusta). */
export function searched(extras: CvPage1Extras | null | undefined): boolean {
  return Array.isArray(extras?.highlight_proposals);
}

const KIND_LABEL: Record<CvHighlightProposal["kind"], string> = {
  award: "Nagroda z CV",
  certificate: "Certyfikat z wymagań MUST",
};

export interface HighlightAiProps {
  extras: CvPage1Extras | null | undefined;
  disabled: boolean;
  /** Zapis trwa — przyciski czekają, żeby dwa kliknięcia nie poszły naraz. */
  saving: boolean;
  /** Odcisk propozycji (`key`) — nie numer, bo lista może się zmienić w tle. */
  onAccept: (key: string) => void;
  onReject: (key: string) => void;
  onEdit: (proposal: Pick<CvHighlightProposal, "label" | "token" | "text">) => void;
  /** „Poszukaj w CV”; brak = bez przycisku (np. harness bez modelu). */
  onFind?: () => Promise<void>;
}

export function HighlightAi({ extras, disabled, saving, onAccept, onReject, onEdit, onFind }: HighlightAiProps) {
  const [finding, setFinding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saved = extras?.highlight;
  const accepted = saved?.mode === "ai" && saved.label && saved.text ? saved : null;
  const acceptedKey =
    accepted?.key && (extras?.highlight_proposals ?? []).some((p) => p?.key === accepted.key) ? accepted.key : null;
  const pending = pendingProposals(extras);
  const busy = disabled || saving || finding;

  const find = async () => {
    if (!onFind) return;
    setFinding(true);
    setError(null);
    try {
      await onFind();
    } catch (reason) {
      setError(apiErrorMessage(reason, "Nie udało się poszukać wyróżnika w CV. Spróbuj za chwilę."));
    } finally {
      setFinding(false);
    }
  };

  return (
    <div className="space-y-2 border-t border-border pt-2" data-testid="cv-new-highlight-ai">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h4 className="text-xs font-semibold text-foreground">Propozycja AI</h4>
        {onFind ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            aria-busy={finding}
            onClick={() => void find()}
            className="ml-auto h-7 rounded-full px-2.5 text-xs"
            title="AI szuka nagrody, wyróżnienia albo certyfikatu z wymagań MUST, z cytatem z CV"
          >
            {finding ? (
              <Loader2 aria-hidden className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw aria-hidden className="mr-1 h-3.5 w-3.5" />
            )}
            {finding ? "Szukam w CV…" : searched(extras) ? "Poszukaj od nowa" : "Poszukaj w CV"}
          </Button>
        ) : null}
      </div>
      {accepted ? (
        <ProposalCard
          label={accepted.label ?? ""}
          token={accepted.token ?? ""}
          text={accepted.text ?? ""}
          quote={accepted.quote ?? ""}
          kind={accepted.kind ?? null}
          accepted
        >
          <Badge variant="success" size="md">
            <Check aria-hidden className="h-3 w-3" /> Na stronie 1
          </Badge>
          {acceptedKey ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => onReject(acceptedKey)}
              className="h-7 px-2 text-xs"
            >
              Odrzuć
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onEdit(accepted as Pick<CvHighlightProposal, "label" | "token" | "text">)}
            className="h-7 px-2 text-xs"
          >
            Popraw jako własny
          </Button>
        </ProposalCard>
      ) : null}
      {pending.length ? (
        <ul className="space-y-2" aria-label="Propozycje wyróżnika do przyjęcia">
          {pending.map(({ index, proposal }) => (
            <li key={proposal.key || index}>
              <ProposalCard
                label={proposal.label}
                token={proposal.token}
                text={proposal.text}
                quote={proposal.quote}
                company={proposal.company}
                kind={proposal.kind}
              >
                <Button
                  type="button"
                  size="sm"
                  disabled={busy}
                  onClick={() => onAccept(proposal.key)}
                  className="h-7 px-2.5 text-xs"
                >
                  Przyjmij
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onReject(proposal.key)}
                  className="h-7 px-2 text-xs"
                >
                  Odrzuć
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onEdit(proposal)}
                  className="h-7 px-2 text-xs"
                >
                  Popraw jako własny
                </Button>
              </ProposalCard>
            </li>
          ))}
        </ul>
      ) : null}
      {pending.length ? (
        <p className="text-xs text-muted-foreground">Bez przyjęcia propozycja nie trafia do CV.</p>
      ) : accepted ? null : (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {searched(extras)
            ? "W CV nie ma nagrody, wyróżnienia ani certyfikatu z wymagań MUST, które da się potwierdzić cytatem."
            : "AI może poszukać w CV nagrody, wyróżnienia albo certyfikatu z wymagań MUST — z cytatem z CV."}
        </p>
      )}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ProposalCard({
  label,
  token,
  text,
  quote,
  company,
  kind,
  accepted = false,
  children,
}: {
  label: string;
  token: string;
  text: string;
  quote: string;
  company?: string | null;
  kind: CvHighlightProposal["kind"] | null;
  accepted?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className="space-y-1.5 rounded-md border border-border bg-card p-2.5"
      data-testid={accepted ? "cv-new-highlight-accepted" : "cv-new-highlight-proposal"}
    >
      {/* Rodzaj nad etykietą, zdanie na całą szerokość karty — w 1280 × 720 rodzaj obok
          etykiety ściskał zdanie do wąskiej kolumny (ścieżka na stagingu 26.11.2026). */}
      {kind ? <p className="text-xs text-muted-foreground">{KIND_LABEL[kind]}</p> : null}
      <div className="flex min-w-0 items-center gap-2">
        {token ? (
          <span className="flex-none rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-foreground">
            {token}
          </span>
        ) : null}
        <p className="min-w-0 flex-1 text-sm font-medium text-foreground">{label}</p>
      </div>
      <p className="text-xs leading-relaxed text-foreground">{plainText(text)}</p>
      {quote ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Z CV: „{quote}”{company ? ` · ${company}` : ""}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
    </div>
  );
}
