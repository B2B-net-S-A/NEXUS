"use client";

/**
 * Baner „To wygląda na powtórkę requestu u <klient>” nad formularzem `/jobs/new`
 * (wariant 2 „Powtórka”, decyzja Artura 23.11.2026). Stoi po odczycie maila,
 * gdy ten sam klient miał już podobny request — dopasowanie z tej samej karty
 * podobnych requestów (`useSimilarRequests`), bez własnego progu. Najlepiej
 * pasująca rekrutacja na górze, reszta pod „Inne podobne (N)”. Dwie kolumny:
 * co weźmiemy z poprzedniej, co z nowego maila. „Użyj <nr>…” składa formularz
 * z szablonu i z różnic maila (`mergeRepeat`), „Czytaj od zera” zostawia odczyt.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { RequestHistoryEntry } from "@/lib/api";
import { formatDayMonthPl } from "@/lib/date-pl";
import type { ClientDefaults } from "@/lib/job-intake-fill";
import {
  mergeRepeat,
  repeatTakeSummary,
  type RepeatMerge,
  type RepeatTemplate,
} from "@/lib/job-intake-repeat";
import type { IntakeForm } from "@/lib/job-request-intake";
import { countPl } from "@/lib/plural-pl";

export const repeatTemplateKey = (jobId: number) => ["repeat-template", jobId] as const;

interface RepeatRequestBannerProps {
  clientName: string;
  /** Podobne requesty klienta (w toku i zamknięte) — kolejność nieważna. */
  entries: readonly RequestHistoryEntry[];
  /** Formularz z ostatniego odczytu maila (przed czymkolwiek, co DL wpisał). */
  read: IntakeForm;
  clientDefaults?: ClientDefaults | null;
  loadTemplate: (jobId: number) => Promise<RepeatTemplate>;
  onUse: (input: { entry: RequestHistoryEntry; template: RepeatTemplate; merge: RepeatMerge }) => void;
  onFromScratch: () => void;
  disabled?: boolean;
}

function stateText(entry: RequestHistoryEntry): string {
  if (entry.is_in_progress) return `W toku od ${formatDayMonthPl(entry.created_at)}`;
  if (entry.outcome === "filled") return "Obsadzona";
  if (entry.outcome === "cancelled") return "Anulowana";
  return "Zamknięta";
}

export function RepeatRequestBanner({
  clientName,
  entries,
  read,
  clientDefaults = null,
  loadTemplate,
  onUse,
  onFromScratch,
  disabled = false,
}: RepeatRequestBannerProps) {
  // Najlepiej pasująca na górze; DL może wskazać inną z „Inne podobne”.
  const ranked = useMemo(
    () => [...entries].sort((a, b) => b.similarity - a.similarity),
    [entries],
  );
  const [chosenId, setChosenId] = useState<number | null>(null);
  const [othersOpen, setOthersOpen] = useState(false);
  const entry = ranked.find((item) => item.job_id === chosenId) ?? ranked[0];
  const others = ranked.filter((item) => item.job_id !== entry?.job_id);

  const templateQuery = useQuery({
    queryKey: repeatTemplateKey(entry?.job_id ?? 0),
    queryFn: () => loadTemplate(entry!.job_id),
    enabled: entry != null,
    staleTime: 5 * 60_000,
    retry: false,
  });
  // „43260” po wczytaniu szablonu; do tego czasu przycisk i tak czeka.
  const label = templateQuery.data?.label ?? "poprzedniej";
  const merge = useMemo(
    () => (templateQuery.data ? mergeRepeat(templateQuery.data, read, { clientDefaults }) : null),
    [templateQuery.data, read, clientDefaults],
  );
  if (!entry) return null;

  const take = templateQuery.data ? repeatTakeSummary(templateQuery.data) : null;
  const mailParts = merge
    ? [
        ...merge.fromMail,
        merge.differences.length > 0
          ? `inne niż w ${label}: ${merge.differences.join(", ")} (pokażemy jako propozycje)`
          : "różnic z poprzednią brak",
      ]
    : null;

  return (
    <section
      aria-labelledby="repeat-request-title"
      data-testid="repeat-request-banner"
      data-tour="new-job.repeat-banner"
      className="flex flex-col gap-3 rounded-xl border-2 border-primary/40 bg-card p-4"
    >
      <h2
        id="repeat-request-title"
        className="flex items-center gap-2 text-sm font-semibold text-foreground"
      >
        <Copy className="h-4 w-4 text-primary" aria-hidden />
        To wygląda na powtórkę requestu u {clientName}
      </h2>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-border bg-background px-3 py-2 text-sm">
        {/* Nazwa od klienta niesie już numer zapytania („… (43260)”). */}
        <span className="font-medium text-foreground">{entry.title}</span>
        <span className="text-muted-foreground">
          · {stateText(entry)} ·{" "}
          {countPl(entry.candidates_count, "kandydat", "kandydatów", "kandydatów")}
          {entry.delivery_lead_name ? ` · DL: ${entry.delivery_lead_name}` : ""}
        </span>
        <a
          href={`/jobs/${entry.job_id}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-primary underline-offset-2 hover:underline"
        >
          Otwórz
        </a>
        {others.length > 0 ? (
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary"
            aria-expanded={othersOpen}
            onClick={() => setOthersOpen((open) => !open)}
          >
            Inne podobne ({others.length})
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${othersOpen ? "rotate-180" : ""}`}
              aria-hidden
            />
          </button>
        ) : null}
      </div>

      {othersOpen && others.length > 0 ? (
        <ul className="flex flex-col gap-1 text-xs" data-testid="repeat-request-others">
          {others.map((item) => (
            <li key={item.job_id} className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate">
                {item.title} · {stateText(item)} ·{" "}
                {countPl(item.candidates_count, "kandydat", "kandydatów", "kandydatów")}
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setChosenId(item.job_id);
                  setOthersOpen(false);
                }}
              >
                Porównaj z tą
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
        <div>
          <h3 className="font-medium text-foreground">Weźmiemy z {label}</h3>
          <p className="text-muted-foreground" data-testid="repeat-request-take">
            {take
              ? take.join(" · ")
              : templateQuery.isError
                ? `Nie udało się wczytać ${entry.title} — spróbuj ponownie albo czytaj od zera.`
                : "Wczytuję…"}
          </p>
        </div>
        <div>
          <h3 className="font-medium text-foreground">Z nowego maila</h3>
          <p className="text-muted-foreground" data-testid="repeat-request-mail">
            {mailParts ? mailParts.join(" · ") : "nazwa i numer · opis projektu · nowe słowa i zdania, jeśli są"}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {templateQuery.isError ? (
          <Button type="button" onClick={() => void templateQuery.refetch()} disabled={disabled}>
            Spróbuj ponownie
          </Button>
        ) : (
          <Button
            type="button"
            disabled={disabled || !templateQuery.data || !merge}
            onClick={() => {
              if (templateQuery.data && merge) onUse({ entry, template: templateQuery.data, merge });
            }}
          >
            Użyj {label} i przeczytaj z maila tylko różnice
          </Button>
        )}
        <Button type="button" variant="outline" onClick={onFromScratch} disabled={disabled}>
          Czytaj od zera
        </Button>
      </div>
    </section>
  );
}
