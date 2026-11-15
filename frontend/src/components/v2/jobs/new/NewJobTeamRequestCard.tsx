"use client";

/**
 * `/jobs/new` → „Co zamawia klient?” (`docs/claude/klienci/zespol-dla-klienta.md`).
 * Zespół to kilka zwykłych rekrutacji pod jednym zapytaniem: każde stanowisko
 * zakłada się tym samym formularzem (Champion, wymagania, bramki), a tu
 * wskazujesz, do którego zespołu klienta należy. Liczba osób na stanowisku to
 * pole „Liczba osób” w formularzu. Nic się tu nie zapisuje: rekrutacja dołącza
 * do zespołu po „Utwórz”.
 */

import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";

import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { fetchTeamsForClient, jobTeamKeys } from "@/lib/api/jobTeams";
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

export function NewJobTeamRequestCard({
  clientId,
  value,
  onChange,
}: {
  clientId: number | null;
  value: TeamChoice;
  onChange: (next: TeamChoice) => void;
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
