"use client";

/**
 * Odpowiedzi z rozmowy screeningowej — jedyny renderer (02.10.2026).
 *
 * Pokazują go: karta „Odpowiedzi z rozmów screeningowych” w profilu kandydata,
 * dok osoby na Tablicy i zapisany arkusz w panelu osoby. Do tej zmiany dok
 * mówił tylko „Odpowiedziano na N pytań”, a profil nie pokazywał arkusza wcale.
 *
 * Treść pytania idzie z odpowiedzi (`question_text`, stempel serwera) —
 * identyfikatory pytań są pozycyjne, więc po edycji profilu Championa samo
 * `question_id` wskazuje inne pytanie.
 */

import { AlertTriangle } from "lucide-react";

import { EXPERIENCE_KIND_LABEL } from "@/lib/champion-experience";
import { cn } from "@/lib/utils";

export interface ScreeningAnswerRow {
  question_id: string;
  question_text?: string | null;
  response?: string | null;
  deal_breaker_hit?: boolean;
  skipped?: boolean;
  /**
   * Numer pytania w arkuszu (od 1). Podaje go lista przefiltrowana szukaniem —
   * bez niego pytanie nr 4 stałoby się po filtrze „pytaniem 1”.
   */
  position?: number;
}

export interface ScreeningCheckRow {
  kind: "domains" | "certifications" | "regulations";
  name: string;
  status: "confirmed" | "not_confirmed" | "unknown";
  note?: string | null;
}

export interface ScreeningAnswersListProps {
  answers: readonly ScreeningAnswerRow[];
  experienceChecks?: readonly ScreeningCheckRow[] | null;
  notes?: string | null;
  internalNote?: string | null;
  /** Fraza z pola „Szukaj w odpowiedziach” — trafienia są wyróżnione. */
  highlight?: string;
  className?: string;
}

const CHECK_LABEL: Record<Exclude<ScreeningCheckRow["status"], "unknown">, string> = {
  confirmed: "potwierdzone w rozmowie",
  not_confirmed: "brak",
};

/** Tekst pytania albo uczciwa etykieta, gdy pytania nie ma już w profilu. */
export function screeningQuestionLabel(answer: ScreeningAnswerRow, index: number): string {
  return answer.question_text?.trim() || `Pytanie ${answer.position ?? index + 1} (usunięte z profilu)`;
}

function Highlighted({ text, phrase }: { text: string; phrase: string }) {
  const needle = phrase.trim().toLocaleLowerCase("pl");
  if (!needle) return <>{text}</>;
  const haystack = text.toLocaleLowerCase("pl");
  const parts: React.ReactNode[] = [];
  let from = 0;
  for (let at = haystack.indexOf(needle); at >= 0; at = haystack.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(
      <mark key={at} className="rounded-sm bg-warning-muted px-0.5 text-warning-muted-foreground">
        {text.slice(at, at + needle.length)}
      </mark>,
    );
    from = at + needle.length;
  }
  parts.push(text.slice(from));
  return <>{parts}</>;
}

export function ScreeningAnswersList({
  answers,
  experienceChecks,
  notes,
  internalNote,
  highlight = "",
  className,
}: ScreeningAnswersListProps) {
  const checks = (experienceChecks ?? []).filter((c) => c.status !== "unknown");
  return (
    <div className={cn("space-y-3 text-[13px]", className)}>
      {answers.length > 0 ? (
        <ol className="space-y-2.5" aria-label="Pytania i odpowiedzi">
          {answers.map((answer, index) => {
            const response = answer.response?.trim() ?? "";
            return (
              <li key={`${answer.question_id}:${index}`} className="space-y-0.5">
                <p className="font-medium text-foreground [overflow-wrap:anywhere]">
                  {answer.position ?? index + 1}.{" "}
                  <Highlighted text={screeningQuestionLabel(answer, index)} phrase={highlight} />
                  {answer.deal_breaker_hit ? (
                    <span className="ml-1.5 inline-flex items-center gap-0.5 text-xs font-normal text-destructive">
                      <AlertTriangle className="size-3" aria-hidden /> deal-breaker
                    </span>
                  ) : null}
                </p>
                <p className="whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">
                  {response ? (
                    <Highlighted text={response} phrase={highlight} />
                  ) : answer.skipped ? (
                    "— pominięte —"
                  ) : (
                    "— bez odpowiedzi —"
                  )}
                </p>
              </li>
            );
          })}
        </ol>
      ) : null}
      {checks.length > 0 ? (
        <div className="space-y-1">
          <h4 className="text-xs font-semibold text-muted-foreground">Sprawdzone w rozmowie</h4>
          <ul className="space-y-0.5">
            {checks.map((check) => (
              <li key={`${check.kind}:${check.name}`} className="[overflow-wrap:anywhere]">
                <span className="text-xs text-muted-foreground">{EXPERIENCE_KIND_LABEL[check.kind]} · </span>
                <span className="text-foreground">{check.name}</span>
                <span
                  className={cn(
                    "ml-1.5 text-xs",
                    check.status === "confirmed" ? "text-success-muted-foreground" : "text-destructive",
                  )}
                >
                  {CHECK_LABEL[check.status as "confirmed" | "not_confirmed"]}
                </span>
                {check.note?.trim() ? <span className="text-xs text-muted-foreground"> — {check.note}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {notes?.trim() ? (
        <div className="space-y-0.5">
          <h4 className="text-xs font-semibold text-muted-foreground">Notatka ze screeningu</h4>
          <p className="whitespace-pre-line text-foreground [overflow-wrap:anywhere]">
            <Highlighted text={notes} phrase={highlight} />
          </p>
        </div>
      ) : null}
      {internalNote?.trim() ? (
        <div className="space-y-0.5">
          <h4 className="text-xs font-semibold text-muted-foreground">Notatka wewnętrzna</h4>
          <p className="whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">{internalNote}</p>
        </div>
      ) : null}
    </div>
  );
}
