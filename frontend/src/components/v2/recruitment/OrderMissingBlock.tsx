"use client";

/**
 * Werdykt oficjalnej bramki „Przekaż do searchu” z działaniem przy każdym
 * braku (budżet i tryb pracy zapisywane na miejscu). Wydzielone z okna
 * „Zlecenie” (29.09.2026), bo ten sam blok stoi teraz na górze zakładki
 * „Gotowość” w panelu zlecenia obok Profilu Championa — jedna lista braków,
 * jeden kod.
 */

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatJobLocation } from "@/components/v2/jobs/JobSummaryCard";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import {
  buildReadinessChecklist,
  parseBudgetInput,
  READINESS_ACTION,
  READINESS_CHAMPION_ANCHOR,
  READINESS_LABEL,
  WORK_MODE_OPTIONS,
  type ReadinessKey,
  type ReadinessMissing,
} from "@/lib/order-readiness";
import { formatJobBudgetLabel } from "@/lib/job-budget";
import { extractSkills } from "@/lib/job-skills";
import { countPl } from "@/lib/plural-pl";
import { httpStatusFromError } from "@/lib/view-state";

/**
 * „X z Y gotowe" — werdykt OFICJALNEJ bramki „Przekaż do searchu".
 *
 * Lista braków przychodzi z serwera (`blockers`), więc okno nie powtarza
 * żadnej reguły gotowości: jedna lista braków, ta sama co w doku i przy
 * przycisku handoffu (wspólny klucz `["job-readiness", jobId]`). Okno tylko
 * rozpoznaje zdanie serwera (`lib/order-readiness.ts`) i daje przy nim
 * działanie: budżet i tryb pracy zapisuje na miejscu — tą samą drogą co
 * edytor Championa (`PUT …/champion-profile`, sekcja „Podstawowe
 * informacje"; serwer przenosi je do kolumn rekrutacji) — resztę otwiera
 * we właściwej sekcji Profilu Championa.
 */
export function MissingBlock({
  jobId,
  job,
  canSeeGate,
  canEditChampion,
  canEditJob,
  onGoChampion,
  onEditJob,
}: {
  jobId: number;
  job: OrderJob;
  canSeeGate: boolean;
  canEditChampion: boolean;
  canEditJob: boolean;
  onGoChampion: (anchor: string | null) => void;
  onEditJob: () => void;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [budgetText, setBudgetText] = useState("");
  const [budgetError, setBudgetError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data),
    enabled: canSeeGate,
    staleTime: 30_000,
    retry: false,
  });
  const saveBasics = useMutation({
    mutationFn: (basics: Record<string, unknown>) =>
      api.put(`/api/jobs/${jobId}/champion-profile`, { basics }).then((r) => r.data),
    onSuccess: (_data, basics) => {
      invalidateChampionDependents(queryClient, jobId);
      if ("rate_value" in basics) {
        setBudgetText("");
        showSuccess("Budżet zapisany.");
      } else {
        showSuccess("Tryb pracy zapisany.");
      }
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać zlecenia.")),
  });

  if (!canSeeGate) return null;
  if (query.isLoading) return <Skeleton className="h-16 w-full rounded-xl" />;
  if (query.isError) {
    // 403 = Delivery Lead spoza zakresu klienta. To nie awaria — po prostu
    // nie jego bramka; pełna kompletność niżej działa dla każdej roli.
    if (httpStatusFromError(query.error) === 403) return null;
    return (
      <div className="flex items-center justify-between gap-2 rounded-xl border border-dashed border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
        <span>Nie udało się sprawdzić, czego brakuje w zleceniu.</span>
        <button
          type="button"
          className="shrink-0 font-medium text-primary hover:underline"
          onClick={() => void query.refetch()}
        >
          Ponów
        </button>
      </div>
    );
  }
  const data = query.data;
  if (!data || data.closed) return null;

  const blockers: string[] = Array.isArray(data.blockers) ? data.blockers : [];
  if (data.already_handed_off || data.ready || blockers.length === 0) {
    return (
      <section
        className="rounded-xl border border-success/20 bg-success-muted px-4 py-3 text-sm font-semibold text-success-muted-foreground"
        data-testid="order-missing-block"
      >
        {data.already_handed_off
          ? "Zlecenie przekazane do searchu — niczego nie brakuje."
          : "Niczego nie brakuje — zlecenie gotowe do przekazania do searchu."}
      </section>
    );
  }

  const checklist = buildReadinessChecklist(blockers, job.remote_policy ?? null);
  const percent = checklist.total > 0 ? Math.round((checklist.doneCount / checklist.total) * 100) : 0;

  const submitBudget = () => {
    const parsed = parseBudgetInput(budgetText);
    if ("error" in parsed) {
      setBudgetError(parsed.error);
      return;
    }
    setBudgetError(null);
    // Liczba wpisana ręcznie, bez tekstu dokumentu — serwer zapisuje ją jako
    // budżet bez notatki (`prepare_profile`), a kolumnę rekrutacji uzupełnia
    // `fill_job_columns_from_champion`.
    saveBasics.mutate({ rate_value: parsed.value, rate_raw: null });
  };

  const renderAction = (item: ReadinessMissing): ReactNode => {
    const action = item.key ? READINESS_ACTION[item.key] : "champion";
    const anchor = item.key ? READINESS_CHAMPION_ANCHOR[item.key] : null;
    const championLink = (
      <Button type="button" size="sm" variant="outline" onClick={() => onGoChampion(anchor)}>
        {canEditChampion ? "Uzupełnij w Championie" : "Zobacz w Championie"} ↗
      </Button>
    );
    if (action === "budget_input" && canEditChampion) {
      const inputId = `order-budget-${jobId}`;
      return (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            submitBudget();
          }}
        >
          <label htmlFor={inputId} className="sr-only">
            Budżet stawki kandydata w PLN/h
          </label>
          <input
            id={inputId}
            type="text"
            inputMode="decimal"
            value={budgetText}
            onChange={(e) => setBudgetText(e.target.value)}
            placeholder="np. 150"
            aria-invalid={budgetError ? true : undefined}
            aria-describedby={budgetError ? `${inputId}-error` : undefined}
            className="h-8 w-24 rounded-md border border-border bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <span className="text-xs text-muted-foreground">PLN/h</span>
          <Button type="submit" size="sm" loading={saveBasics.isPending} disabled={saveBasics.isPending}>
            Zapisz
          </Button>
          {budgetError ? (
            <p id={`${inputId}-error`} role="alert" className="w-full text-xs text-destructive">
              {budgetError}
            </p>
          ) : null}
        </form>
      );
    }
    if (action === "work_mode_buttons" && canEditChampion) {
      return (
        <div role="group" aria-label="Tryb pracy" className="flex flex-wrap gap-1.5">
          {WORK_MODE_OPTIONS.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant="outline"
              disabled={saveBasics.isPending}
              onClick={() => saveBasics.mutate({ work_mode: option.value })}
            >
              {option.label}
            </Button>
          ))}
        </div>
      );
    }
    if (action === "edit_job") {
      return canEditJob ? (
        <Button type="button" size="sm" variant="outline" onClick={onEditJob}>
          Edytuj rekrutację
        </Button>
      ) : null;
    }
    return championLink;
  };

  return (
    <section
      className="space-y-3 rounded-xl border border-warning/25 bg-warning-muted px-4 py-3 text-warning-muted-foreground"
      data-testid="order-missing-block"
      aria-label="Braki w zleceniu"
    >
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">
            {checklist.doneCount} z {checklist.total} gotowe
          </h3>
          <span className="text-xs">
            brakuje {countPl(checklist.missing.length, "rzeczy", "rzeczy", "rzeczy")}
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Gotowość zlecenia do przekazania do searchu"
          aria-valuemin={0}
          aria-valuemax={checklist.total}
          aria-valuenow={checklist.doneCount}
          className="h-1.5 w-full overflow-hidden rounded-full bg-background/60"
        >
          <div className="h-full rounded-full bg-warning" style={{ width: `${percent}%` }} />
        </div>
      </div>
      <ul className="space-y-2" aria-label="Czego brakuje">
        {checklist.missing.map((item) => (
          <li
            key={item.message}
            data-readiness={item.key ?? "other"}
            className="space-y-1.5 rounded-lg border border-warning/25 bg-card px-3 py-2 text-foreground"
          >
            <div className="flex items-start gap-2 text-[13px]">
              <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" aria-label="Brakuje" />
              <div className="min-w-0">
                <p className="font-medium">{item.label}</p>
                {item.key ? <p className="text-xs text-muted-foreground">{item.message}</p> : null}
              </div>
            </div>
            <div className="pl-5">{renderAction(item)}</div>
          </li>
        ))}
      </ul>
      {checklist.done.length > 0 ? (
        <div className="space-y-1">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide">Gotowe</h4>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground" aria-label="Gotowe">
            {checklist.done.map((key) => (
              <li key={key} className="inline-flex items-center gap-1">
                <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                {doneLabel(key, job)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** Minimalny kształt `GET /api/jobs/{id}`, którego okno używa. */
interface OrderJob {
  title?: string | null;
  client_name?: string | null;
  client_reference?: string | null;
  remote_policy?: string | null;
  location?: string | null;
  onsite_days_per_week?: number | null;
  must_skills?: unknown;
  has_budget_hourly?: boolean | null;
  [key: string]: unknown;
}

function doneLabel(key: ReadinessKey, job: OrderJob): string {
  const label = READINESS_LABEL[key];
  switch (key) {
    case "title":
      return job.title?.trim() ? `${label}: ${job.title.trim()}` : label;
    case "client":
      return job.client_name?.trim() ? `${label}: ${job.client_name.trim()}` : label;
    case "must": {
      const must = extractSkills(job.must_skills);
      return must.length > 0 ? `${label}: ${must.slice(0, 3).join(", ")}${must.length > 3 ? "…" : ""}` : label;
    }
    case "budget": {
      const budget = formatJobBudgetLabel(job as Parameters<typeof formatJobBudgetLabel>[0]);
      return budget != null ? `${label}: ${budget}` : label;
    }
    case "work_mode":
      return `${label}: ${formatJobLocation(job as Parameters<typeof formatJobLocation>[0])}`;
    default:
      return label;
  }
}

/**
 * Po przejściu na zakładkę Championa sekcja montuje się z opóźnieniem —
 * czekamy na nią chwilę i przewijamy. Brak sekcji po 3 s = zostaje sama
 * zakładka (nigdy błąd).
 */
export function scrollToWhenReady(anchor: string, timeoutMs = 3000): void {
  if (typeof window === "undefined") return;
  const started = Date.now();
  const tick = () => {
    // Timer potrafi odpalić po rozmontowaniu (w testach — po zamknięciu jsdom).
    if (typeof document === "undefined") return;
    const el = document.getElementById(anchor);
    if (el) {
      el.scrollIntoView?.({ block: "start", behavior: "smooth" });
      return;
    }
    if (Date.now() - started < timeoutMs) window.setTimeout(tick, 100);
  };
  window.setTimeout(tick, 50);
}
