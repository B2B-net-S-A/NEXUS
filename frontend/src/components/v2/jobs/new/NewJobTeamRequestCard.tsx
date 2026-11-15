"use client";

/**
 * `/jobs/new` → „Co zamawia klient?” (`docs/claude/klienci/zespol-dla-klienta.md`).
 * Zespół to kilka zwykłych rekrutacji pod jednym zapytaniem: każde stanowisko
 * zakłada się tym samym formularzem (Champion, wymagania, bramki), a tu
 * wskazujesz, do którego zespołu klienta należy. Liczba osób na stanowisku to
 * pole „Liczba osób” w formularzu. Nic się tu nie zapisuje: rekrutacja dołącza
 * do zespołu po „Utwórz”.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Sparkles, Users } from "lucide-react";

import { Button } from "@/components/ui/button";

import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  fetchTeamsForClient,
  jobTeamKeys,
  splitTeamRequest,
  type SplitPosition,
} from "@/lib/api/jobTeams";
import { apiErrorMessage } from "@/lib/api-error";

export type TeamChoice =
  | { mode: "one" }
  | { mode: "team"; teamId: number | null; newName: string };

export const NO_TEAM: TeamChoice = { mode: "one" };

const MODE_OPTIONS = [
  { value: "one", label: "Jedna rekrutacja" },
  { value: "team", label: "Stanowisko w zespole" },
] as const;

/** Komunikat, gdy zespół wybrany, ale bez nazwy nowego; `null` = można tworzyć. */
export function teamChoiceProblem(choice: TeamChoice): string | null {
  if (choice.mode === "team" && choice.teamId == null && !choice.newName.trim()) {
    return "Wybierz zespół albo wpisz nazwę nowego.";
  }
  return null;
}

const SPLIT_MIN_TEXT = 20;
const LEVEL_LABEL = { junior: "junior", regular: "regular", senior: "senior" } as const;

/** Rozbicie zapytania żyje w tej przeglądarce do końca sesji, żeby wrócić po kolejne stanowisko. */
function splitStorageKey(clientId: number): string {
  return `nexus:team-split:${clientId}`;
}

function loadSplit(clientId: number | null): { positions: SplitPosition[]; used: number[] } | null {
  if (clientId == null) return null;
  try {
    const raw = sessionStorage.getItem(splitStorageKey(clientId));
    return raw ? (JSON.parse(raw) as { positions: SplitPosition[]; used: number[] }) : null;
  } catch {
    return null;
  }
}

function saveSplit(clientId: number | null, value: { positions: SplitPosition[]; used: number[] }): void {
  if (clientId == null) return;
  try {
    sessionStorage.setItem(splitStorageKey(clientId), JSON.stringify(value));
  } catch {
    // Pamięć przeglądarki to wygoda; bez niej lista znika po przejściu dalej.
  }
}

/**
 * „Rozbij zapytanie na stanowiska”: odczyt maila (AI, dodatek) podaje stanowiska
 * z treści; „Użyj” wpisuje rolę i liczbę osób do formularza tej rekrutacji.
 */
function RequestSplit({
  clientId,
  requestText,
  onUse,
}: {
  clientId: number | null;
  requestText: string;
  onUse: (position: SplitPosition) => void;
}) {
  const [state, setState] = useState<{ positions: SplitPosition[]; used: number[] } | null>(null);
  useEffect(() => setState(loadSplit(clientId)), [clientId]);
  const split = useMutation({
    mutationFn: () => splitTeamRequest(requestText),
    onSuccess: ({ positions }) => {
      const next = { positions, used: [] };
      setState(next);
      saveSplit(clientId, next);
    },
  });
  const tooShort = requestText.trim().length < SPLIT_MIN_TEXT;

  return (
    <div className="grid gap-2 rounded-lg border border-border px-3 py-2" data-testid="team-request-split">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={tooShort || split.isPending}
          onClick={() => split.mutate()}
        >
          <Sparkles className="h-3.5 w-3.5" />
          {split.isPending ? "Czytam zapytanie…" : "Rozbij zapytanie na stanowiska"}
        </Button>
        <span className="text-xs text-muted-foreground">
          {tooShort
            ? "Wklej treść zapytania („Wypełnij z: Wklej treść”), a odczyt wypisze stanowiska."
            : "Odczyt wypisze stanowiska z treści. „Użyj” wpisze rolę i liczbę osób do tej rekrutacji."}
        </span>
      </div>
      {split.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(split.error, "Nie udało się odczytać stanowisk. Wpisz rolę ręcznie.")}
        </p>
      ) : null}
      {split.isSuccess && state?.positions.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Odczyt nie znalazł w treści stanowisk. Wpisz rolę ręcznie.
        </p>
      ) : null}
      {state && state.positions.length > 0 ? (
        <ul className="grid gap-1">
          {state.positions.map((position, index) => {
            const used = state.used.includes(index);
            return (
              <li
                key={`${position.title}-${index}`}
                className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-sm"
              >
                <span className="min-w-0 font-medium">{position.title}</span>
                <span className="text-xs text-muted-foreground">
                  {position.headcount === 1 ? "1 osoba" : `${position.headcount} os.`}
                  {position.seniority ? ` · ${LEVEL_LABEL[position.seniority]}` : ""}
                  {position.words.length ? ` · ${position.words.join(", ")}` : ""}
                </span>
                {used ? (
                  <span className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground">
                    <Check className="h-3.5 w-3.5" />
                    użyte
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto"
                    onClick={() => {
                      onUse(position);
                      const next = { ...state, used: [...state.used, index] };
                      setState(next);
                      saveSplit(clientId, next);
                    }}
                  >
                    Użyj
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function NewJobTeamRequestCard({
  clientId,
  value,
  onChange,
  requestText = "",
  onUsePosition,
}: {
  clientId: number | null;
  value: TeamChoice;
  onChange: (next: TeamChoice) => void;
  /** Treść zapytania z „Wklej treść” albo odczytu — źródło „Rozbij na stanowiska”. */
  requestText?: string;
  onUsePosition?: (position: SplitPosition) => void;
}) {
  const teams = useQuery({
    queryKey: jobTeamKeys.forClient(clientId ?? 0),
    queryFn: () => fetchTeamsForClient(clientId as number),
    enabled: clientId != null && value.mode === "team",
  });

  return (
    <section className="rounded-xl border border-border bg-card px-4 py-3" data-testid="new-job-team">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="inline-flex items-center gap-1.5 text-sm font-semibold">
          <Users className="h-4 w-4 text-muted-foreground" />
          Co zamawia klient?
        </h2>
        <SegmentedRadio
          label="Co zamawia klient"
          size="sm"
          value={value.mode}
          options={MODE_OPTIONS}
          onChange={(mode) => onChange(mode === "one" ? NO_TEAM : { mode: "team", teamId: null, newName: "" })}
        />
        {value.mode === "one" ? (
          <span className="text-xs text-muted-foreground">
            Klient zamawia kilka stanowisk naraz? Wybierz „Stanowisko w zespole”.
          </span>
        ) : null}
      </div>

      {value.mode === "team" ? (
        <div className="mt-3 grid gap-2">
          {clientId == null ? (
            <p className="text-sm text-muted-foreground">Najpierw wybierz klienta.</p>
          ) : teams.isPending ? (
            <p className="text-sm text-muted-foreground" role="status">Wczytuję zespoły klienta…</p>
          ) : teams.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(teams.error, "Nie udało się wczytać zespołów klienta.")}
            </p>
          ) : (
            <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <label className="grid gap-1 text-xs text-muted-foreground">
                Zespół
                <select
                  className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                  value={value.teamId ?? ""}
                  onChange={(e) =>
                    onChange({
                      mode: "team",
                      teamId: e.target.value ? Number(e.target.value) : null,
                      newName: value.newName,
                    })
                  }
                >
                  <option value="">Nowy zespół…</option>
                  {(teams.data ?? []).map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name} · {team.positions} stanowisk
                    </option>
                  ))}
                </select>
              </label>
              {value.teamId == null ? (
                <label className="grid gap-1 text-xs text-muted-foreground">
                  Nazwa nowego zespołu (widzi ją klient)
                  <Input
                    value={value.newName}
                    maxLength={160}
                    placeholder="np. Zespół danych i raportowania"
                    onChange={(e) => onChange({ mode: "team", teamId: null, newName: e.target.value })}
                  />
                </label>
              ) : null}
            </div>
          )}
          {onUsePosition ? (
            <RequestSplit clientId={clientId} requestText={requestText} onUse={onUsePosition} />
          ) : null}
          <p className="text-xs text-muted-foreground">
            Ta rekrutacja to jedno stanowisko zespołu: ma własnego Championa i Tablicę. Ile osób na
            tym stanowisku, wpisz w „Liczba osób”. Kolejne stanowisko dodasz po utworzeniu, z ekranu
            zespołu.
          </p>
        </div>
      ) : null}
    </section>
  );
}
