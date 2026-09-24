"use client"

/**
 * Ustawienia → Zespół i dostęp → „Kategorie kompetencji” (makieta Main, 24.09.2026).
 *
 * Artur przypisuje ludzi do czterech kategorii zespołu (1. i 2. priorytet),
 * oznacza konta „Poza przydziałem” i ustawia zasady automatu przydziału
 * requestów. 1. priorytet jest jeden na osobę — nadanie go w innej kategorii
 * przenosi dotychczasowy na 2. (tak liczy serwer).
 */

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Plus, X } from "lucide-react"

import { QueryStateNotice } from "@/components/ds/QueryStateNotice"
import { useToast } from "@/components/Toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { competenceTone } from "@/components/v2/CompetenceCategoryBadge"
import { apiErrorMessage } from "@/lib/api-error"
import {
  COMPETENCE_TEAM_QUERY_KEY,
  deleteTeamAssignment,
  putTeamAssignment,
  putTeamRules,
  setAllocationExcluded,
  useCompetenceTeam,
  type CompetenceTeam,
  type TeamCategory,
  type TeamPerson,
  type TeamRules,
} from "@/lib/api/requestAllocation"
import { resolveViewState } from "@/lib/view-state"

const ROLE_LABEL: Record<string, string> = {
  recruiter: "rekruter",
  sourcer: "sourcer",
  tac: "TAC",
  delivery_lead: "DL",
}

function roleLabel(person: TeamPerson): string {
  return person.roles
    .map((r) => ROLE_LABEL[r])
    .filter(Boolean)
    .join(" · ")
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("")
}

export interface CompetenceTeamActions {
  assign: (userId: number, categoryId: number, priority: 1 | 2) => void
  remove: (assignmentId: number) => void
  exclude: (userId: number, excluded: boolean) => void
  saveRules: (rules: TeamRules) => void
}

function PersonChip({
  person,
  onRemove,
}: {
  person: TeamPerson
  onRemove: () => void
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-border bg-background py-0.5 pl-0.5 pr-1 text-sm">
      <span
        className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-[11px] font-bold text-primary"
        aria-hidden
      >
        {initials(person.name)}
      </span>
      <span>{person.name}</span>
      <span className="font-mono text-[11px] text-muted-foreground">
        {roleLabel(person)}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Usuń ${person.name} z kategorii`}
        className="rounded-full p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </span>
  )
}

function AddToCategory({
  category,
  priority,
  people,
  onAdd,
}: {
  category: TeamCategory
  priority: 1 | 2
  people: TeamPerson[]
  onAdd: (userId: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const taken = new Set(
    (priority === 1 ? category.first : category.second).map((p) => p.user_id),
  )
  const matches = people
    .filter((p) => !taken.has(p.user_id) && !p.allocation_excluded)
    .filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase()))
    .slice(0, 8)
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex min-h-9 items-center gap-1 rounded-full border border-dashed border-border px-3 text-sm font-semibold text-primary hover:bg-accent"
        aria-label={`Dodaj osobę do: ${category.name}, ${priority}. priorytet`}
      >
        <Plus className="h-3.5 w-3.5" aria-hidden /> Dodaj
      </button>
    )
  }
  return (
    <div className="flex w-full flex-col gap-2 rounded-md border border-border bg-background p-2">
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Szukaj osoby
        <input
          autoFocus
          className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Imię albo nazwisko"
        />
      </label>
      <ul className="flex flex-col gap-1">
        {matches.map((p) => (
          <li key={p.user_id}>
            <button
              type="button"
              onClick={() => {
                onAdd(p.user_id)
                setOpen(false)
                setQuery("")
              }}
              className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
            >
              <span>{p.name}</span>
              <span className="text-xs text-muted-foreground">{roleLabel(p)}</span>
            </button>
          </li>
        ))}
        {matches.length === 0 && (
          <li className="px-2 text-xs text-muted-foreground">Nikt nie pasuje.</li>
        )}
      </ul>
      <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
        Zamknij
      </Button>
    </div>
  )
}

function RulesForm({
  rules,
  onSave,
}: {
  rules: TeamRules
  onSave: (rules: TeamRules) => void
}) {
  const [threshold, setThreshold] = useState(String(rules.sourcer_threshold))
  const [time, setTime] = useState(rules.review_time)
  return (
    <section
      aria-label="Zasady przydziału"
      className="grid gap-4 rounded-lg border border-border bg-card p-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto] md:items-end"
    >
      <label className="flex flex-col gap-1 text-sm text-muted-foreground">
        Sourcer wystarczy, gdy w bazie jest co najmniej
        <span className="flex items-center gap-2 text-foreground">
          <input
            type="number"
            min={1}
            max={500}
            className="h-10 w-24 rounded-md border border-input bg-background px-2"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
          pasujących osób
        </span>
      </label>
      <label className="flex flex-col gap-1 text-sm text-muted-foreground">
        Codzienny przegląd przydziałów o
        <input
          type="time"
          className="h-10 w-32 rounded-md border border-input bg-background px-2 text-foreground"
          value={time}
          onChange={(e) => setTime(e.target.value)}
        />
      </label>
      <p className="text-sm text-muted-foreground">
        Urlopy biorę z Compassa. Osoba bez kategorii nie dostaje requestów automatycznie.
      </p>
      <Button
        onClick={() =>
          onSave({ sourcer_threshold: Number(threshold), review_time: time })
        }
      >
        Zapisz zasady
      </Button>
    </section>
  )
}

export function CompetenceTeamView({
  team,
  actions,
}: {
  team: CompetenceTeam
  actions: CompetenceTeamActions
}) {
  const people = team.people
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1 overflow-hidden rounded-lg border border-border bg-card">
          <div className="grid grid-cols-[240px_minmax(0,1fr)_minmax(0,1fr)] gap-4 border-b border-border px-5 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <div>Kategoria</div>
            <div>1. priorytet</div>
            <div>2. priorytet</div>
          </div>
          {team.categories.map((category) => (
            <div
              key={category.id}
              className="grid grid-cols-[240px_minmax(0,1fr)_minmax(0,1fr)] items-start gap-4 border-b border-border px-5 py-4 last:border-0"
            >
              <div className="flex flex-col gap-1.5">
                <Badge variant={competenceTone(category.slug)} size="md" className="self-start">
                  {category.name}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  W pracy: {category.requests_searching}
                </span>
              </div>
              {([1, 2] as const).map((priority) => (
                <div key={priority} className="flex flex-wrap gap-2">
                  {(priority === 1 ? category.first : category.second).map((p) => (
                    <PersonChip
                      key={p.user_id}
                      person={p}
                      onRemove={() => p.assignment_id && actions.remove(p.assignment_id)}
                    />
                  ))}
                  <AddToCategory
                    category={category}
                    priority={priority}
                    people={people}
                    onAdd={(userId) => actions.assign(userId, category.id, priority)}
                  />
                </div>
              ))}
            </div>
          ))}
          <p className="bg-muted/40 px-5 py-3 text-sm text-muted-foreground">
            Jedna osoba może mieć kilka kategorii, ale 1. priorytet tylko jeden — nadanie
            go w innej kategorii przenosi dotychczasowy na 2.
          </p>
        </div>

        <aside className="flex w-full flex-col gap-4 xl:w-[340px] xl:shrink-0">
          <section
            aria-label="Bez kategorii"
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4"
          >
            <h3 className="text-sm font-semibold">Bez kategorii</h3>
            <p className="text-sm text-muted-foreground">
              Nie dostaną requestów, dopóki ich nie przypiszesz.
            </p>
            {team.unassigned.length === 0 ? (
              <p className="text-sm text-muted-foreground">Wszyscy mają kategorię.</p>
            ) : (
              team.unassigned.map((p) => (
                <div key={p.user_id} className="flex items-center justify-between gap-2 text-sm">
                  <span>{p.name}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => actions.exclude(p.user_id, true)}
                  >
                    Poza przydziałem
                  </Button>
                </div>
              ))
            )}
          </section>
          <section
            aria-label="Poza przydziałem"
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4"
          >
            <h3 className="text-sm font-semibold">Poza przydziałem</h3>
            <p className="text-sm text-muted-foreground">
              Konta, które nie pracują przy requestach. Automat ich pomija.
            </p>
            {team.excluded.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nikt.</p>
            ) : (
              team.excluded.map((p) => (
                <label key={p.user_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked
                    onChange={() => actions.exclude(p.user_id, false)}
                    className="h-4 w-4 accent-primary"
                  />
                  {p.name}
                </label>
              ))
            )}
          </section>
        </aside>
      </div>
      <RulesForm key={`${team.rules.sourcer_threshold}-${team.rules.review_time}`} rules={team.rules} onSave={actions.saveRules} />
    </div>
  )
}

export function CompetenceTeamPanel() {
  const query = useCompetenceTeam()
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const refresh = () => queryClient.invalidateQueries({ queryKey: COMPETENCE_TEAM_QUERY_KEY })
  const run = async (action: () => Promise<unknown>, fallback: string, ok?: string) => {
    try {
      await action()
      if (ok) showSuccess(ok)
    } catch (error) {
      showError(apiErrorMessage(error, fallback))
    }
    await refresh()
  }

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: false,
    isSuccess: query.isSuccess,
  })
  if (state === "loading") {
    return <div className="h-64 animate-pulse rounded-lg bg-muted" aria-busy="true" />
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />
  }
  return (
    <CompetenceTeamView
      team={query.data as CompetenceTeam}
      actions={{
        assign: (userId, categoryId, priority) =>
          run(
            () => putTeamAssignment(userId, categoryId, priority),
            "Nie udało się przypisać osoby.",
          ),
        remove: (assignmentId) =>
          run(() => deleteTeamAssignment(assignmentId), "Nie udało się usunąć przypisania."),
        exclude: (userId, excluded) =>
          run(
            () => setAllocationExcluded(userId, excluded),
            "Nie udało się zmienić przydziału osoby.",
          ),
        saveRules: (rules) =>
          run(() => putTeamRules(rules), "Nie udało się zapisać zasad.", "Zasady zapisane."),
      }}
    />
  )
}
