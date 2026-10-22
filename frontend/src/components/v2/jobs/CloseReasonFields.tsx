"use client";

/**
 * Wybór powodu zamknięcia w trzech grupach (decyzja Artura 21.10.2026):
 * „Wygraliśmy”, „Przegraliśmy” (tylko inna firma) i „Nie liczy się” (poza hit
 * ratio, z obowiązkowym uzasadnieniem). Wspólne dla „Zamknij rekrutację”
 * (strona rekrutacji, krok „Umowa”), okna w profilu klienta i „Zmień powód”.
 */

import { useQuery } from "@tanstack/react-query";

import { jobsApi } from "@/lib/api";
import {
  CLOSE_REASON_GROUPS,
  closeReasonGroup,
  type CloseReasonGroup,
} from "@/lib/job-close-reasons";
import { cn } from "@/lib/utils";
import type { JobCloseReason } from "@/types/client-profile";

export interface CloseReasonValue {
  reason: JobCloseReason | null;
  notes: string;
  duplicateOfJobId: number | null;
}

interface CloseReasonFieldsProps {
  value: CloseReasonValue;
  onChange: (next: CloseReasonValue) => void;
  jobId: number;
  clientId?: number | null;
}

const GROUP_TONE: Record<CloseReasonGroup, { on: string; effect: string }> = {
  won: { on: "border-info bg-info-muted", effect: "bg-info-muted text-info-muted-foreground" },
  lost: {
    on: "border-warning bg-warning-muted",
    effect: "bg-warning-muted text-warning-muted-foreground",
  },
  neutral: { on: "border-foreground/60 bg-muted", effect: "bg-muted text-foreground" },
};

/** Czy wybór da się wysłać — serwer i tak sprawdza (422 z `code`). */
export function closeReasonReady(value: CloseReasonValue): boolean {
  const group = closeReasonGroup(value.reason);
  if (!group) return false;
  return group !== "neutral" || value.notes.trim().length > 0;
}

export function CloseReasonFields({ value, onChange, jobId, clientId }: CloseReasonFieldsProps) {
  const group = closeReasonGroup(value.reason);
  const groupDef = CLOSE_REASON_GROUPS.find((g) => g.key === group) ?? null;
  const isDuplicate = value.reason === "duplicate";
  const neutral = group === "neutral";

  const siblings = useQuery({
    queryKey: ["close-reason-duplicate-of", clientId],
    queryFn: () =>
      jobsApi
        .list({ client_id: clientId, open_only: true, page_size: 100 })
        .then((r) => (r.data?.items ?? []) as { id: number; title: string }[]),
    enabled: isDuplicate && clientId != null,
    staleTime: 60_000,
  });
  const siblingOptions = (siblings.data ?? []).filter((j) => j.id !== jobId);

  const pickGroup = (key: CloseReasonGroup) => {
    if (key === group) return;
    const first = CLOSE_REASON_GROUPS.find((g) => g.key === key)?.reasons[0]?.value ?? null;
    onChange({ ...value, reason: first, duplicateOfJobId: null });
  };

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-xs font-semibold text-foreground">Jak się skończyła?</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {CLOSE_REASON_GROUPS.map((g) => (
            <button
              key={g.key}
              type="button"
              aria-pressed={g.key === group}
              onClick={() => pickGroup(g.key)}
              data-testid={`close-group-${g.key}`}
              className={cn(
                "flex min-h-11 flex-col items-start rounded-lg border px-3 py-2 text-left",
                g.key === group ? GROUP_TONE[g.key].on : "border-border bg-card hover:bg-muted",
              )}
            >
              <span className="text-sm font-semibold text-foreground">{g.label}</span>
              <span className="text-xs text-muted-foreground">{g.hint}</span>
            </button>
          ))}
        </div>
      </fieldset>

      {groupDef ? (
        <fieldset className="space-y-1.5">
          <legend className="text-xs font-semibold text-foreground">Powód</legend>
          {groupDef.reasons.map((r) => (
            <label
              key={r.value}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2",
                value.reason === r.value ? "border-primary/50 bg-muted/60" : "border-border",
              )}
            >
              <input
                type="radio"
                name="job-close-reason"
                value={r.value}
                checked={value.reason === r.value}
                onChange={() =>
                  onChange({
                    ...value,
                    reason: r.value,
                    duplicateOfJobId: r.value === "duplicate" ? value.duplicateOfJobId : null,
                  })
                }
                className="mt-0.5 accent-primary"
              />
              <span className="flex flex-col">
                <span className="text-sm font-medium text-foreground">{r.label}</span>
                <span className="text-xs text-muted-foreground">{r.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="text-xs text-muted-foreground">
          Wybierz, jak skończyła się rekrutacja — od tego zależy hit ratio.
        </p>
      )}

      {isDuplicate ? (
        <div className="space-y-1">
          <label htmlFor="job-close-duplicate-of" className="text-xs font-semibold text-foreground">
            Która rekrutacja zostaje? (jeśli jest)
          </label>
          <select
            id="job-close-duplicate-of"
            value={value.duplicateOfJobId ?? ""}
            onChange={(e) =>
              onChange({
                ...value,
                duplicateOfJobId: e.target.value ? Number(e.target.value) : null,
              })
            }
            className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:ring-2 focus:ring-primary focus:outline-hidden"
          >
            <option value="">— żadna, założona przez pomyłkę —</option>
            {siblingOptions.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title} · #{j.id}
              </option>
            ))}
          </select>
          {siblings.isError ? (
            <p className="text-xs text-destructive">
              Nie udało się wczytać rekrutacji klienta — możesz zamknąć bez wskazania.
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-1">
        <label htmlFor="job-close-notes" className="text-xs font-semibold text-foreground">
          {neutral ? "Uzasadnienie *" : "Notatka (opcjonalnie)"}
        </label>
        <textarea
          id="job-close-notes"
          rows={3}
          value={value.notes}
          onChange={(e) => onChange({ ...value, notes: e.target.value })}
          placeholder={
            neutral
              ? "Co się stało — widzi to Head of Recruitment w Insights"
              : "Kontekst — co konkretnie się wydarzyło…"
          }
          aria-required={neutral}
          className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm focus:ring-2 focus:ring-primary focus:outline-hidden"
        />
      </div>

      {groupDef ? (
        <p
          className={cn("rounded-lg px-3 py-2 text-xs leading-relaxed", GROUP_TONE[groupDef.key].effect)}
          data-testid="close-reason-effect"
        >
          {groupDef.effect}
        </p>
      ) : null}
    </div>
  );
}
