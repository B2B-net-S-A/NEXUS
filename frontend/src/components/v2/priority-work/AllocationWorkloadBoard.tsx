"use client"

import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  allocationApi,
  allocationReason,
  type AllocationMode,
} from "@/lib/recruitment-allocation-api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

export function AllocationWorkloadBoard() {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ["allocation-team"],
    queryFn: allocationApi.team,
    refetchInterval: 30_000,
  })
  const change = useMutation({
    mutationFn: (mode: AllocationMode) => allocationApi.mode(mode),
    onSuccess: () => client.invalidateQueries({ queryKey: ["allocation-team"] }),
  })
  if (query.isPending)
    return <Card className="p-4">Sprawdzanie obłożenia i dostępności…</Card>
  if (query.isError)
    return (
      <Card className="p-4 text-destructive">
        Nie udało się pobrać obłożenia.{" "}
        <Button variant="outline" onClick={() => query.refetch()}>
          Ponów
        </Button>
      </Card>
    )
  const data = query.data
  const names = new Map(data.people.map((person) => [person.user_id, person.name]))
  return (
    <Card className="space-y-5 p-4" aria-label="Obłożenie i zastępstwa">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Obłożenie i zastępstwa</h2>
          <p className="text-sm text-muted-foreground">
            Najpierw liczymy poszukiwania, potem zaległe zadania, zadania na dziś i
            obsługę kandydatów.
          </p>
        </div>
        <label className="text-sm">
          Nowe przydziały{" "}
          <select
            className="ml-2 rounded border border-border bg-background p-2"
            aria-label="Tryb automatycznego przydziału"
            value={data.mode}
            disabled={!data.enabled || change.isPending}
            onChange={(event) => change.mutate(event.target.value as AllocationMode)}
          >
            <option value="off">Zatrzymane</option>
            <option value="shadow">Podgląd decyzji</option>
            <option value="auto" disabled={!data.availability_fresh}>
              Automatyczne
            </option>
          </select>
        </label>
      </div>
      {change.isError && (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się zmienić trybu. Sprawdź synchronizację i spróbuj ponownie.
        </p>
      )}
      <p
        className={
          data.availability_fresh
            ? "text-sm text-muted-foreground"
            : "text-sm text-destructive"
        }
      >
        {data.availability_fresh
          ? "COMPASS: dane aktualne"
          : "COMPASS: brak aktualnych danych. Nowe automatyczne przydziały czekają."}
        {data.last_sync_at &&
          ` · Odczyt: ${new Date(data.last_sync_at).toLocaleString("pl-PL")}`}
        {data.mode === "shadow" && " · Podgląd nie zmienia prowadzących."}
      </p>
      {data.worker_error && (
        <p role="alert" className="text-destructive">
          Przeliczanie wymaga uwagi: {data.worker_error}. Zdarzenia czekają na ponowienie.
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {data.people.map((person) => (
          <section key={person.user_id} className="rounded-lg border border-border p-3">
            <div className="flex justify-between gap-2">
              <h3 className="font-medium">{person.name}</h3>
              <span className="text-xs text-muted-foreground">
                {person.available ? "Dostępny/a" : "Poza przydziałem"}
              </span>
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-1 text-sm">
              <dt>Poszukiwania</dt>
              <dd className="text-right font-semibold">{person.active_searches}</dd>
              <dt>Z faworytem</dt>
              <dd className="text-right">{person.with_favorite}</dd>
              <dt>Zaległe zadania</dt>
              <dd className="text-right">{person.overdue_tasks}</dd>
              <dt>Zadania na dziś</dt>
              <dd className="text-right">{person.tasks_today}</dd>
              <dt>Obsługa kandydatów</dt>
              <dd className="text-right">{person.candidate_followups}</dd>
              <dt>Przejęte rekrutacje / zadania</dt>
              <dd className="text-right">
                {person.inherited_recruitments} / {person.inherited_tasks}
              </dd>
            </dl>
          </section>
        ))}
      </div>
      {!!data.delegations.length && (
        <div>
          <h3 className="font-medium">Aktywne zastępstwa</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {data.delegations.map((item) => (
              <li key={item.owner_id}>
                {item.performer_name} zastępuje {item.owner_name}: {item.start_date} –{" "}
                {item.end_date}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!data.issues.length && (
        <div className="rounded border border-destructive/30 p-3">
          <h3 className="font-medium">Do rozstrzygnięcia przez kierownika</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {data.issues.map((issue, index) => (
              <li key={index}>
                {names.get(issue.user_id ?? issue.owner_id ?? 0) ?? "Zespół"}:{" "}
                {allocationReason[issue.reason ?? issue.code ?? ""] ??
                  issue.reason ??
                  issue.code}
                {issue.job_id && (
                  <>
                    {" "}
                    ·{" "}
                    <Link
                      className="text-primary underline"
                      href={`/jobs/${issue.job_id}`}
                    >
                      Rekrutacja #{issue.job_id}
                    </Link>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <h3 className="font-medium">Kolejka i decyzje</h3>
        {!data.requests.length && (
          <p className="mt-2 text-sm text-muted-foreground">
            Brak przekazań do automatycznego przydziału.
          </p>
        )}
        <ul className="mt-2 divide-y divide-border">
          {data.requests.map((request) => (
            <li
              key={request.id}
              className="flex flex-wrap justify-between gap-2 py-3 text-sm"
            >
              <div>
                <Link
                  href={`/jobs/${request.job_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {request.title}
                </Link>
                <p className="text-muted-foreground">
                  {request.status === "assigned"
                    ? "Przydzielono"
                    : request.status === "cancelled"
                      ? "Zakończono obsługę kolejki"
                      : data.mode === "shadow"
                        ? "Podgląd"
                        : "Oczekuje"}{" "}
                  · {allocationReason[request.reason ?? ""] ?? "Czeka na przeliczenie"}
                </p>
                {request.decision?.workload_before && (
                  <p className="text-xs text-muted-foreground">
                    Przed wyborem: {request.decision.workload_before.active_searches}{" "}
                    poszukiwań, {request.decision.workload_before.overdue_tasks}{" "}
                    zaległych, {request.decision.workload_before.tasks_today} na dziś,{" "}
                    {request.decision.workload_before.candidate_followups} procesów.
                    Kompetencja:{" "}
                    {request.decision.competence_priority === 1 ? "główna" : "dodatkowa"}.
                  </p>
                )}
              </div>
              <span>{request.person_name ?? "Jeszcze bez osoby"}</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

export function JobAllocationSummary({ jobId }: { jobId: number }) {
  const query = useQuery({
    queryKey: ["job-allocation", jobId],
    queryFn: () => allocationApi.job(jobId),
    refetchInterval: 30_000,
    retry: false,
  })
  if (!query.data) return null
  const data = query.data
  return (
    <div className="space-y-1 rounded border border-border bg-muted/30 p-3 text-sm">
      <p>
        Prowadzący: <strong>{data.owner_name ?? "Nieprzypisany"}</strong>
      </p>
      {data.substitution && (
        <p>
          Wykonuje: <strong>{data.effective_name}</strong> · zastępstwo{" "}
          {data.substitution.start_date} – {data.substitution.end_date}
        </p>
      )}
      {data.favorite_sourcing_paused && (
        <p>
          Faworyt zatrzymał poszukiwania. Obsługa kandydata i terminy pozostają aktywne.
        </p>
      )}
      {data.reason && (
        <p>
          {allocationReason[data.reason] ?? data.reason}
          {data.decision?.workload_before &&
            ` · ${data.decision.workload_before.active_searches} aktywnych poszukiwań przed przydziałem`}
        </p>
      )}
    </div>
  )
}
