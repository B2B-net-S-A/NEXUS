"use client";

/**
 * Lewa kolumna przeglądu Delivery Leada (D9, 08.10.2026): wymagania klienta
 * a kandydat, ocena rekrutera z formularza screeningu, ryzyka i historia
 * u klienta. Dane liczy serwer (`GET /api/dl-review/context`) — tu tylko
 * widok. Wymaganie, którego nie da się sprawdzić słowem (zdanie, branża),
 * jest „do oceny”, nigdy „brak”.
 */

import type { ReactNode } from "react";
import { AlertTriangle, Check, CircleHelp, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  DlReviewAssessment,
  DlReviewContext,
  DlReviewRequirement,
  DlReviewRisk,
} from "@/lib/api/dlReview";
import { cn } from "@/lib/utils";

const LEVEL_LABEL: Record<DlReviewRequirement["level"], string> = {
  critical: "krytyczne",
  must: "musi mieć",
  nice: "mile widziane",
  experience: "doświadczenie",
};

const ASSESSMENT_LABELS: Record<string, string> = {
  recommendation: "Dlaczego ten kandydat",
  motivation: "Motywacja",
  red_flags: "Red flags",
  availability: "Dostępność",
  work_mode: "Tryb pracy",
  location: "Lokalizacja",
  english: "Angielski",
  worked_at_client: "Czy pracował u klienta",
};

function StatusCell({ status }: { status: DlReviewRequirement["status"] }) {
  if (status === "met") {
    return (
      <span className="inline-flex items-center gap-1 text-success">
        <Check className="size-3.5" aria-hidden /> jest
      </span>
    );
  }
  if (status === "missing") {
    return (
      <span className="inline-flex items-center gap-1 text-destructive">
        <X className="size-3.5" aria-hidden /> brak
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground" title="Tego nie da się sprawdzić słowem — oceń sam.">
      <CircleHelp className="size-3.5" aria-hidden /> do oceny
    </span>
  );
}

export function RequirementsTable({ rows }: { rows: DlReviewRequirement[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Profil Championa nie ma wymagań do porównania — sprawdź CV obok.
      </p>
    );
  }
  // Status zaraz po wymaganiu: przy 1280 px kolumna ma ok. 260 px i dalsze
  // komórki chowają się pod przewijaniem — to, czy wymaganie jest, ma być widać.
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[26rem] text-left text-xs">
        <thead className="bg-muted/40 text-[11px] text-muted-foreground">
          <tr>
            <th scope="col" className="px-2 py-1.5 font-medium">Wymaganie</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Status</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Źródło</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Kandydat</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={row.key} data-requirement-status={row.status}>
              <td className="px-2 py-1.5 align-top">
                <span className="font-medium text-foreground">{row.label}</span>
                <span className="block text-[10px] text-muted-foreground">{LEVEL_LABEL[row.level]}</span>
              </td>
              <td className="whitespace-nowrap px-2 py-1.5 align-top">
                <StatusCell status={row.status} />
              </td>
              <td className="px-2 py-1.5 align-top">{row.sources.length > 0 ? row.sources.join(", ") : "—"}</td>
              <td className="max-w-[16rem] px-2 py-1.5 align-top text-muted-foreground [overflow-wrap:anywhere]">
                {row.candidate_value ?? (row.status === "met" ? "w profilu" : "—")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AssessmentBlock({ assessment }: { assessment: DlReviewAssessment }) {
  const fields = Object.entries(ASSESSMENT_LABELS).filter(([key]) => assessment.fields[key]);
  const fitTone =
    assessment.overall_fit === "fit" ? "success" : assessment.overall_fit === "miss" ? "danger" : "outline";
  return (
    <div className="space-y-2" data-testid="dl-review-assessment">
      <p className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">Ocena rekrutera:</span>
        {assessment.overall_fit_label ? (
          <Badge size="sm" variant={fitTone as "success" | "danger" | "outline"}>
            {assessment.overall_fit_label}
          </Badge>
        ) : (
          <span className="text-muted-foreground">brak oceny w formularzu</span>
        )}
      </p>
      {fields.length > 0 ? (
        <dl className="space-y-1.5">
          {fields.map(([key, label]) => (
            <div key={key} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-2 text-xs">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="whitespace-pre-line text-foreground [overflow-wrap:anywhere]">{assessment.fields[key]}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {assessment.answers.length > 0 ? (
        <details className="rounded-md border border-border">
          <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium">
            Pełne odpowiedzi ze screeningu ({assessment.answers.length})
          </summary>
          <ol className="space-y-2 border-t border-border p-2 text-xs">
            {assessment.answers.map((answer, index) => (
              <li key={answer.question_id ?? index}>
                <p className="font-medium text-foreground">{answer.question ?? `Pytanie ${index + 1}`}</p>
                <p className="whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">{answer.answer}</p>
                {answer.deal_breaker_hit ? (
                  <p className="mt-0.5 text-[11px] font-medium text-destructive">Narusza „Odpada, gdy…”</p>
                ) : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

const SEVERITY_CLASS: Record<DlReviewRisk["severity"], string> = {
  high: "border-destructive/40 bg-destructive/5 text-destructive",
  medium: "border-warning/40 bg-warning-muted text-warning-muted-foreground",
  info: "border-border bg-muted/30 text-muted-foreground",
};

export function RisksList({ risks }: { risks: DlReviewRisk[] }) {
  if (risks.length === 0) {
    return <p className="text-xs text-muted-foreground">Bez zastrzeżeń z historii i formularza.</p>;
  }
  return (
    <ul className="space-y-1" aria-label="Ryzyka">
      {risks.map((risk, index) => (
        <li
          key={`${risk.code}-${index}`}
          className={cn("flex items-start gap-1.5 rounded-md border px-2 py-1 text-xs", SEVERITY_CLASS[risk.severity])}
        >
          <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
          <span className="min-w-0 [overflow-wrap:anywhere]">{risk.label}</span>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {hint ? <span className="text-[11px] text-muted-foreground">{hint}</span> : null}
      </header>
      {children}
    </section>
  );
}

export interface RequirementsColumnProps {
  context: DlReviewContext | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  /** Karta rekomendacji i arkusz (pod spodem, jak dotąd). */
  children?: ReactNode;
}

export function RequirementsColumn({ context, loading, error, onRetry, children }: RequirementsColumnProps) {
  return (
    <div className="min-w-0 space-y-5" data-testid="dl-review-requirements">
      {loading ? (
        <p className="text-xs text-muted-foreground" role="status">
          Porównuję wymagania klienta z kandydatem…
        </p>
      ) : error || !context ? (
        <p role="alert" className="text-xs text-destructive">
          Nie udało się wczytać porównania z wymaganiami.{" "}
          <button type="button" className="font-medium underline" onClick={onRetry}>
            Ponów
          </button>
        </p>
      ) : (
        <>
          <Section
            title="Wymagania klienta a kandydat"
            hint={
              context.requirements_total > 0
                ? `${context.requirements_met}/${context.requirements_total} krytycznych i musi mieć`
                : undefined
            }
          >
            <RequirementsTable rows={context.requirements} />
          </Section>
          <Section title="Ocena rekrutera">
            <AssessmentBlock assessment={context.assessment} />
          </Section>
          <Section
            title="Ryzyka i historia u klienta"
            hint={context.fix_rounds > 0 ? `wracał do poprawy ${context.fix_rounds}×` : undefined}
          >
            <RisksList risks={context.risks} />
          </Section>
        </>
      )}
      {children}
    </div>
  );
}
