"use client";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useBoTeam, useSaveDeputy, useSaveTeam, type BoTeamId } from "@/lib/api/back-office";

const SELECT = "h-8 w-full rounded-md border bg-card px-2 text-sm";

/**
 * Skład czterech zespołów i zastępca kierownika. Kierownik to head back office
 * z „Ludzie → Struktura”. Dopóki skład jest pusty, zespół wynika z uprawnień.
 */
export function TeamsPanel() {
  const { showToast } = useToast();
  const query = useBoTeam();
  const saveTeam = useSaveTeam();
  const saveDeputy = useSaveDeputy();
  const data = query.data;

  if (query.isError) {
    return <p className="text-sm text-destructive">{apiErrorMessage(query.error, "Nie udało się wczytać zespołów.")}</p>;
  }
  if (!data) return <p className="text-sm text-muted-foreground">Ładowanie…</p>;

  const change = (team: BoTeamId, ids: number[]) =>
    saveTeam.mutate(
      { team, user_ids: ids },
      { onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać składu."), "error") },
    );
  const empty = data.teams.every((team) => team.members.length === 0);

  return (
    <div className="space-y-4">
      {empty ? (
        <p className="rounded-lg border border-dashed bg-card p-3 text-sm text-muted-foreground">
          Skład nie jest jeszcze wpisany, więc zespół wynika z uprawnień: Sprawy to Opieka, Płace i Raporty godzin to
          Finanse, Kontrakty i zamówienia to Umowy, Moduł Finanse to Zamówienia.
        </p>
      ) : null}
      <label className="flex max-w-md items-center gap-2 text-sm">
        <span className="shrink-0 text-muted-foreground">Zastępca kierownika</span>
        <select
          className={SELECT}
          value={data.deputy_user_id ?? ""}
          onChange={(event) =>
            saveDeputy.mutate(event.target.value ? Number(event.target.value) : null, {
              onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać zastępcy."), "error"),
            })
          }
        >
          <option value="">bez zastępcy</option>
          {data.candidates.map((person) => (
            <option key={person.id} value={person.id}>
              {person.name}
            </option>
          ))}
        </select>
      </label>
      <div className="grid grid-cols-4 gap-3">
        {data.teams.map((team) => {
          const ids = team.members.map((member) => member.id);
          return (
            <section key={team.id} className="min-w-0 rounded-xl bg-muted/60 p-3" aria-label={team.label}>
              <h3 className="pb-2 text-sm font-semibold">{team.label}</h3>
              <ul className="space-y-1 pb-2">
                {team.members.map((member) => (
                  <li key={member.id} className="flex items-center justify-between gap-2 rounded-md bg-card px-2 py-1 text-sm">
                    <span className="min-w-0 truncate">{member.name}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 px-1.5 text-xs"
                      aria-label={`Usuń z zespołu: ${member.name}`}
                      onClick={() => change(team.id, ids.filter((id) => id !== member.id))}
                    >
                      Usuń
                    </Button>
                  </li>
                ))}
              </ul>
              <select
                aria-label={`Dodaj osobę do zespołu ${team.label}`}
                className={SELECT}
                value=""
                onChange={(event) => {
                  const id = Number(event.target.value);
                  if (id) change(team.id, [...ids, id]);
                }}
              >
                <option value="">dodaj osobę…</option>
                {data.candidates
                  .filter((person) => !ids.includes(person.id))
                  .map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.name}
                    </option>
                  ))}
              </select>
            </section>
          );
        })}
      </div>
    </div>
  );
}
