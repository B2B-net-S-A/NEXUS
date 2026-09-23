"use client";

/**
 * Prawy panel (372 px) dla aktywnego wiersza segmentu „Propozycje z bazy".
 *
 * Panel niczego nie dociąga sam — wszystko, co pokazuje, przyszło już
 * w ładunkach scalonej listy (`ProposalDetail`). Jedyne zapytanie odpala
 * świadomie otwarte okno weryfikacji wymagania.
 */

import type { ReactNode } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { RequirementVerificationDialog } from "@/components/talent-radar/RequirementVerificationDialog";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import { formatBudgetHourly } from "@/lib/job-budget";
import {
  formatHourlyRate,
  proposalRateFit,
  reassignReason,
  type ProposalEntry,
  type ProposalRequirement,
} from "@/lib/proposals-merge";
import { PROPOSAL_SOURCE_LABEL } from "./types";
import { stageLabel } from "@/components/v2/candidates/candidate-row-format";

export interface ProposalPanelProps {
  jobId: number;
  entry: ProposalEntry | null;
  budgetHourly: number | null;
  readOnly?: boolean;
  /** Rola może dodawać do pipeline'u (`useCanAddToRecruitment`). */
  canAdd?: boolean;
  /** Rola może weryfikować wymagania (`useCanVerifyRequirements`). */
  canVerify?: boolean;
  /** Rola może otworzyć profil kandydata (`nav.candidates`). */
  canOpenProfile?: boolean;
  busy?: boolean;
  onAdd: (candidateId: number) => void;
  onShortlist: (candidateId: number) => void;
  onDismiss: (candidateId: number) => void;
  /** Okno maila żyje w stronie rekrutacji — panel tylko o nie prosi. */
  onWriteEmail?: (candidateId: number) => void;
  /** Po zapisanej weryfikacji: odśwież bieżący przegląd (nigdy nowy skan). */
  onVerified?: () => void;
  /** Narzędzia AI administratora — schowane za rozwinięciem. */
  adminTools?: ReactNode;
  /** Pełne szczegóły dopasowania (np. uzasadnienie AI na żądanie) — pod „Kontekst". */
  matchDetails?: ReactNode;
}

const OFFICE_FIT_LABEL: Record<string, string> = {
  ok: "Pasuje do trybu pracy i biura",
  days_exceeded: "Za dużo wymaganych dni w biurze",
  city_mismatch: "Inne miasto niż biuro",
  not_required: "Biuro nie jest wymagane",
};

const STATUS_MARK: Record<ProposalRequirement["status"], { mark: string; label: string; className: string }> = {
  met: { mark: "✓", label: "spełnione", className: "text-success" },
  unknown: { mark: "?", label: "brak potwierdzenia", className: "text-muted-foreground" },
  not_met: { mark: "✕", label: "niespełnione", className: "text-destructive" },
};

function initials(fullName: string): string {
  return fullName.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("");
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5 text-sm">
      <h4 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

function RequirementList({ items }: { items: ProposalRequirement[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1">
      {items.map((r, i) => {
        const s = STATUS_MARK[r.status];
        return (
          <li key={`${r.level}-${r.label}-${i}`} className="inline-flex items-center gap-1">
            <span aria-hidden className={`font-semibold ${s.className}`}>{s.mark}</span>
            <span>{r.label}</span>
            <span className="sr-only"> — {s.label}</span>
            {r.verified && <span className="text-[11px] text-muted-foreground">(zweryfikowane)</span>}
          </li>
        );
      })}
    </ul>
  );
}

export function ProposalPanel({
  jobId,
  entry,
  budgetHourly,
  readOnly = false,
  canAdd = true,
  canVerify = false,
  canOpenProfile = true,
  busy = false,
  onAdd,
  onShortlist,
  onDismiss,
  onWriteEmail,
  onVerified,
  adminTools,
  matchDetails,
}: ProposalPanelProps) {
  if (!entry) {
    return (
      <aside aria-label="Wybrana osoba" className="w-full rounded-xl lg:w-[372px] lg:shrink-0 border border-border bg-card p-4 text-sm text-muted-foreground">
        Wybierz osobę z listy, aby zobaczyć, dlaczego pasuje do tej rekrutacji.
      </aside>
    );
  }
  const { row, detail } = entry;
  const id = row.candidateId;
  const must = detail.requirements.filter((r) => r.level === "must");
  const nice = detail.requirements.filter((r) => r.level === "nice");
  const rateFit = proposalRateFit(detail, budgetHourly);
  const vetoed = detail.eligibility?.assignment_allowed === false;
  const actionsDisabled = readOnly || busy;
  const meta = [detail.title, detail.city].filter(Boolean).join(" · ");

  return (
    <aside aria-label="Wybrana osoba" className="flex w-full flex-col gap-3 lg:w-[372px] lg:shrink-0 rounded-xl border border-border bg-card p-4">
      <header className="flex items-center gap-3">
        <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[13px] font-semibold text-primary">
          {initials(row.fullName)}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[15px] font-semibold text-foreground">{row.fullName}</h3>
          {meta && <p className="truncate text-xs text-muted-foreground">{meta}</p>}
        </div>
        {canOpenProfile && (
          <Link href={`/candidates/${id}?from=job&jobId=${jobId}`} className="shrink-0 text-xs font-medium text-primary hover:underline">
            Pełny profil
          </Link>
        )}
      </header>

      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        {row.sources.map((s) => (
          <span key={s} className="rounded-md bg-muted px-2 py-0.5 font-medium text-foreground">{PROPOSAL_SOURCE_LABEL[s]}</span>
        ))}
        {row.isNew && <span className="rounded-md bg-primary/15 px-2 py-0.5 font-medium text-primary">Nowa</span>}
        <span className="ml-auto font-semibold tabular-nums text-foreground">
          {row.fitScore === null ? "Dopasowanie: nie policzono" : `Dopasowanie: ${row.fitScore}`}
        </span>
      </div>

      {row.previouslyDismissed && (
        <p role="note" className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Wcześniej pominięta w tej rekrutacji — wraca, bo ma nową wersję CV.
        </p>
      )}

      {/* Konflikt z klientem = bursztynowe ostrzeżenie (przypisanie dozwolone);
          czerwień wyłącznie dla weta hiring managera. */}
      {detail.eligibility && (
        <p role={vetoed ? "alert" : "note"} className={`rounded-md px-3 py-2 text-xs ${eligibilityBadgeClass(detail.eligibility)}`}>
          {detail.eligibility.reason}
        </p>
      )}
      {detail.rejectedBySameClient && (
        <p role="note" className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Ten klient odrzucił już tę osobę w podobnym projekcie.
        </p>
      )}

      {detail.reassignFrom && (
        <p
          role="note"
          className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary"
        >
          <b className="font-semibold">↻ Przepięcie.</b> {reassignReason(detail.reassignFrom)}
          {detail.reassignFrom.reference_number
            ? ` (${detail.reassignFrom.reference_number})`
            : ""}
          . Rekrutacje są połączone jako podobne.
        </p>
      )}

      <div className="rounded-lg bg-muted/60 p-3">
        <Section title="Dlaczego pasuje">
          <p className="leading-snug text-foreground">
            {row.reason ?? "To źródło nie podaje uzasadnienia — sprawdź wymagania poniżej albo profil."}
          </p>
        </Section>
      </div>

      <Section title="Wymagania">
        {/* Bramka dealbreakera (0278): węższa niż lista wymagań — bez tych
            technologii osoba jest ukrywana na pozostałych powierzchniach. */}
        {detail.missingMustGate.length > 0 && (
          <p
            className="rounded-md border border-destructive/25 bg-destructive/5 px-2 py-1 text-[11px] text-destructive"
            title="Bramka dealbreakera: bez tych technologii kandydat jest ukrywany na pozostałych powierzchniach rankingu — ta lista jest węższa niż pełne pokrycie wymagań poniżej."
          >
            Bramka must-have: brak {detail.missingMustGate.join(", ")}
          </p>
        )}
        {detail.requirements.length === 0 ? (
          <p className="text-muted-foreground">
            Brak oceny wymagań dla tej osoby — uruchom przegląd bazy, żeby ją policzyć.
          </p>
        ) : (
          <div className="space-y-1.5">
            {must.length > 0 && <RequirementList items={must} />}
            {nice.length > 0 && (
              <div className="text-muted-foreground">
                <span className="text-[11px]">Mile widziane: </span>
                <RequirementList items={nice} />
              </div>
            )}
          </div>
        )}
        {canVerify && !readOnly && onVerified && (
          <RequirementVerificationDialog jobId={jobId} candidateId={id} candidateName={row.fullName} onSaved={onVerified} />
        )}
      </Section>

      <Section title="Stawka i lokalizacja">
        <dl className="space-y-1">
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Stawka wobec budżetu</dt>
            <dd className={rateFit === "over" ? "font-medium text-warning-muted-foreground" : "text-foreground"}>
              {detail.rateRedacted && detail.rateHourly == null
                ? "Stawka ukryta (brak dostępu do finansów)"
                : `${formatHourlyRate(detail.rateHourly) ?? "brak stawki"}${
                    budgetHourly != null ? ` / budżet ${formatBudgetHourly(budgetHourly)} PLN/h` : " / budżet nieokreślony"
                  }${rateFit === "over" ? " — ponad budżet" : rateFit === "in" ? " — w budżecie" : ""}`}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Lokalizacja</dt>
            <dd className="text-right text-foreground">
              {detail.city ?? "brak danych"}
              {detail.officeFit && OFFICE_FIT_LABEL[detail.officeFit] ? ` · ${OFFICE_FIT_LABEL[detail.officeFit]}` : ""}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Dostępność</dt>
            <dd className="text-foreground">{row.availabilityLabel ?? "brak danych"}</dd>
          </div>
        </dl>
      </Section>

      <Section title="Kontekst">
        {detail.similarProjects.length === 0 && !detail.sameClient ? (
          <p className="text-muted-foreground">Brak historii w podobnych projektach.</p>
        ) : (
          <ul className="space-y-0.5">
            {detail.sameClient && <li>Ten klient już rozważał tę osobę.</li>}
            {detail.similarProjects.map((p) => (
              <li key={`${p.jobId}-${p.stage}`} className="truncate">
                <Link href={`/jobs/${p.jobId}`} className="text-primary hover:underline">{p.title}</Link>
                <span className="text-muted-foreground"> · etap: {stageLabel(p.stage)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {detail.aiSummary && (
        <Section title="Podsumowanie">
          <p className="line-clamp-4 text-xs leading-relaxed text-muted-foreground">{detail.aiSummary}</p>
        </Section>
      )}

      {matchDetails ? <div className="border-t border-border pt-3">{matchDetails}</div> : null}

      {adminTools && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Narzędzia AI (administrator)</summary>
          <div className="mt-2">{adminTools}</div>
        </details>
      )}

      <div className="flex-1" />

      {canAdd && (
        <Button
          data-help="jobs.proposals.add"
          size="lg"
          className="w-full"
          disabled={actionsDisabled || vetoed}
          title={vetoed ? "Hiring manager odrzucił tę osobę — dodanie jest zablokowane" : undefined}
          onClick={() => onAdd(id)}
        >
          Dodaj do rekrutacji
        </Button>
      )}
      <div className="flex gap-2">
        {canAdd && (
          <Button variant="outline" className="flex-1" disabled={actionsDisabled} onClick={() => onShortlist(id)}>
            Do shortlisty
          </Button>
        )}
        {canAdd && (
          <Button variant="outline" className="flex-1" disabled={actionsDisabled} onClick={() => onDismiss(id)}>
            Pomiń
          </Button>
        )}
        {onWriteEmail && (
          <Button variant="outline" className="flex-1" disabled={busy} onClick={() => onWriteEmail(id)}>
            Napisz
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">↑ ↓ następna osoba · D dodaj · P pomiń</p>
    </aside>
  );
}
