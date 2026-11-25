"use client";

/**
 * Wybór powodu zamknięcia w trzech grupach (decyzja Artura 21.10.2026):
 * „Wygraliśmy”, „Przegraliśmy” (tylko inna firma) i „Nie liczy się” (poza hit
 * ratio, z obowiązkowym uzasadnieniem). Wspólne dla „Zamknij rekrutację”
 * (strona rekrutacji, krok „Umowa”), okna w profilu klienta i „Zmień powód”.
 */

import { useQuery } from "@tanstack/react-query";

import { jobsApi, type LostWhyPayload } from "@/lib/api";
import {
  CLOSE_REASON_GROUPS,
  closeReasonGroup,
  type CloseReasonGroup,
} from "@/lib/job-close-reasons";
import {
  LOST_WHY,
  LOST_WHY_MAX,
  LOST_WHY_SOURCES,
  toggleLostWhy,
  type LostWhyKey,
  type LostWhySource,
} from "@/lib/lost-review";
import { cn } from "@/lib/utils";
import type { JobCloseReason } from "@/types/client-profile";

export interface CloseReasonValue {
  reason: JobCloseReason | null;
  notes: string;
  duplicateOfJobId: number | null;
  /** „Co zdecydowało?” przy przegranej (25.11.2026). Brak = okno ich nie wysyła. */
  lostWhy?: LostWhyKey[];
  lostWhySource?: LostWhySource | null;
}

interface CloseReasonFieldsProps {
  value: CloseReasonValue;
  onChange: (next: CloseReasonValue) => void;
  jobId: number;
  clientId?: number | null;
}

/**
 * „Co zdecydowało?” przy przegranej (Insights → Przegrane, decyzja Artura
 * 25.11.2026): do dwóch powodów i „Skąd wiesz?”. Oba opcjonalne — okno da się
 * zamknąć bez nich, a DL uzupełni je na spotkaniu.
 */
function LostWhyFields({
  why,
  source,
  onChange,
}: {
  why: LostWhyKey[];
  source: LostWhySource | null;
  onChange: (next: { lostWhy: LostWhyKey[]; lostWhySource: LostWhySource | null }) => void;
}) {
  return (
    <fieldset
      className="space-y-2 rounded-lg border border-warning/60 bg-warning-muted/40 px-3 py-2.5"
      data-testid="close-lost-why"
    >
      <legend className="px-1 text-xs font-semibold text-foreground">
        Co zdecydowało? (do {LOST_WHY_MAX}, opcjonalnie)
      </legend>
      <div className="flex flex-wrap gap-1">
        {LOST_WHY.map((w) => {
          const on = why.includes(w.key);
          return (
            <button
              key={w.key}
              type="button"
              aria-pressed={on}
              onClick={() => onChange({ lostWhy: toggleLostWhy(why, w.key), lostWhySource: source })}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs",
                on ? "border-primary bg-primary/10 text-primary" : "border-border bg-card hover:bg-muted",
              )}
            >
              {w.label}
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-xs">
        <span className="mr-1 font-semibold text-foreground">Skąd wiesz?</span>
        {LOST_WHY_SOURCES.map((s) => (
          <button
            key={s.key}
            type="button"
            aria-pressed={source === s.key}
            onClick={() =>
              onChange({ lostWhy: why, lostWhySource: source === s.key ? null : s.key })
            }
            className={cn(
              "rounded-full border px-2.5 py-1",
              source === s.key
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-card hover:bg-muted",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
      {source === "unknown" ? (
        <p className="text-xs text-muted-foreground">
          Za 3 dni robocze NEXUS przypomni, a w Insights → Przegrane czeka gotowe pytanie do hiring
          managera (wysyłasz je ze swojej skrzynki).
        </p>
      ) : null}
    </fieldset>
  );
}

const GROUP_TONE: Record<CloseReasonGroup, { on: string; effect: string }> = {
  won: { on: "border-info bg-info-muted", effect: "bg-info-muted text-info-muted-foreground" },
  lost: {
    on: "border-warning bg-warning-muted",
    effect: "bg-warning-muted text-warning-muted-foreground",
  },
  neutral: { on: "border-foreground/60 bg-muted", effect: "bg-muted text-foreground" },
};

/** „Co zdecydowało?” do wysyłki; `null` = nic nie wybrano, zapis zostaje bez zmian. */
export function lostWhyOf(value: CloseReasonValue): LostWhyPayload | null {
  const why = value.lostWhy ?? [];
  const source = value.lostWhySource ?? null;
  if (value.reason !== "competitor" || (why.length === 0 && !source)) return null;
  return { why, source };
}

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
  // Zapisana rekrutacja, która zostaje, bywa już zamknięta (lista ma tylko
  // otwarte) — pole ma pokazać to, co pójdzie w zapisie (audyt 22.10.2026).
  const savedMissing =
    value.duplicateOfJobId != null && !siblingOptions.some((j) => j.id === value.duplicateOfJobId);

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

      {value.reason === "competitor" ? (
        <LostWhyFields
          why={value.lostWhy ?? []}
          source={value.lostWhySource ?? null}
          onChange={(next) => onChange({ ...value, ...next })}
        />
      ) : null}

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
            {savedMissing ? (
              <option value={value.duplicateOfJobId ?? ""}>#{value.duplicateOfJobId}</option>
            ) : null}
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
