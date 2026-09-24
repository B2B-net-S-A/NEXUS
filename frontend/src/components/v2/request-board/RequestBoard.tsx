"use client"

/**
 * Pulpit „Requesty i obłożenie” — makieta C6 (decyzje Artura 24.09.2026).
 *
 * Na daily zespół patrzy, nad czym pracuje: requesty „Szukamy kandydatów”
 * pogrupowane po czterech kategoriach kompetencji, z liczbą requestów w każdej.
 * Kolumny: stanowisko · klient, termin, wysłani (+ znacznik „Champion” —
 * request z championem stoi na dole grupy, przygaszony), kto pracuje (kilka
 * osób z rolą). Po prawej rozwijane „Obłożenie” i „Zmiany od wczoraj”.
 *
 * Filtry liczy przeglądarka (`lib/request-board.ts`), stan w adresie — link
 * wysłany na daily otwiera ten sam widok. Bez podpowiedzi systemu: Artur
 * wprost ich nie chce na tym ekranie.
 */

import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Plus, X } from "lucide-react"

import { QueryStateNotice } from "@/components/ds/QueryStateNotice"
import { useToast } from "@/components/Toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { competenceTone } from "@/components/v2/CompetenceCategoryBadge"
import { apiErrorMessage } from "@/lib/api-error"
import {
  REQUEST_BOARD_QUERY_KEY,
  addBoardPerson,
  removeBoardPerson,
  useRequestBoard,
  type BoardPerson,
  type BoardRequest,
  type RequestBoard as RequestBoardData,
} from "@/lib/api/requestAllocation"
import {
  daysToDeadline,
  deadlineLabel,
  filtersFromParams,
  filtersToParams,
  groupRequests,
  type BoardFilters,
} from "@/lib/request-board"
import { resolveViewState } from "@/lib/view-state"
import { hasRole, useAuthStore } from "@/store/auth"

import { ChangesPanel, LoadPanel } from "./LoadPanel"
import { RequestBoardFilters } from "./RequestBoardFilters"

const COLS = "grid-cols-[minmax(0,2fr)_110px_130px_minmax(0,1.6fr)]"

export function warsawToday(now: Date = new Date()): string {
  return now.toLocaleDateString("sv-SE", { timeZone: "Europe/Warsaw" })
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("")
}

function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-")
  return `${d}.${m}.${y}`
}

const MODE_COPY: Record<RequestBoardData["mode"], { label: string; hint: string }> = {
  off: {
    label: "Automat wyłączony",
    hint: "Przydziały robi się ręcznie.",
  },
  shadow: {
    label: "Podgląd automatu",
    hint: "Automat tylko proponuje (przerywana ramka) — nikt nic nie dostaje.",
  },
  auto: {
    label: "Automat włączony",
    hint: "Automat przydziela ludzi codziennie rano i po każdej zmianie.",
  },
}

function PersonChip({
  person,
  canEdit,
  onRemove,
}: {
  person: BoardPerson
  canEdit: boolean
  onRemove: () => void
}) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full py-0.5 pl-0.5 pr-2 text-sm ${
        person.proposed ? "border border-dashed border-primary/60" : ""
      }`}
    >
      <span
        className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary"
        aria-hidden
      >
        {initials(person.name)}
      </span>
      <span>{person.name}</span>
      <span className="text-[11px] text-muted-foreground">
        {person.role === "sourcer" ? "sourcer" : "rekruter"}
        {person.proposed ? " · propozycja" : ""}
      </span>
      {canEdit && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Zdejmij ${person.name} z requestu`}
          className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </span>
  )
}

function AddPerson({
  board,
  request,
  onAdd,
}: {
  board: RequestBoardData
  request: BoardRequest
  onAdd: (userId: number, role: "recruiter" | "sourcer") => void
}) {
  const [open, setOpen] = useState(false)
  const [userId, setUserId] = useState("")
  const [role, setRole] = useState<"recruiter" | "sourcer">("recruiter")
  const taken = new Set(request.people.map((p) => p.user_id))
  const options = board.load.filter((p) => !taken.has(p.user_id))
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground"
        aria-label={`Dodaj osobę do: ${request.title}`}
      >
        <Plus className="h-3 w-3" aria-hidden /> osoba
      </button>
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <select
        aria-label="Osoba"
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        value={userId}
        onChange={(e) => setUserId(e.target.value)}
      >
        <option value="">Wybierz osobę</option>
        {options.map((p) => (
          <option key={p.user_id} value={p.user_id}>
            {p.name} ({p.count})
          </option>
        ))}
      </select>
      <select
        aria-label="Rola"
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        value={role}
        onChange={(e) => setRole(e.target.value as "recruiter" | "sourcer")}
      >
        <option value="recruiter">rekruter</option>
        <option value="sourcer">sourcer</option>
      </select>
      <Button
        size="sm"
        disabled={!userId}
        onClick={() => {
          onAdd(Number(userId), role)
          setOpen(false)
          setUserId("")
        }}
      >
        Dodaj
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Anuluj
      </Button>
    </span>
  )
}

export function RequestBoardView({
  board,
  today,
  filters,
  onFilters,
  canEdit,
  onAddPerson,
  onRemovePerson,
}: {
  board: RequestBoardData
  today: string
  filters: BoardFilters
  onFilters: (next: BoardFilters) => void
  canEdit: boolean
  onAddPerson: (jobId: number, userId: number, role: "recruiter" | "sourcer") => void
  onRemovePerson: (jobId: number, userId: number) => void
}) {
  const { groups, shown, total } = useMemo(
    () => groupRequests(board, filters, today),
    [board, filters, today],
  )
  const mode = MODE_COPY[board.mode]

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Requesty i obłożenie</h2>
          <p className="text-sm text-muted-foreground">
            {mode.label}. {mode.hint}
            {board.mode !== "off" && !board.availability_known
              ? " Brak świeżych danych o urlopach z Compassa — urlopy nie są uwzględnione."
              : ""}
          </p>
        </div>
        <Link
          href="/jobs/review-states"
          className="text-sm font-medium text-primary hover:underline"
        >
          Porządek w requestach
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {board.groups.map((g) => (
          <Badge key={g.category_id ?? "none"} variant={competenceTone(g.slug)} size="md">
            {g.name} · {g.total}
          </Badge>
        ))}
        <span className="text-sm text-muted-foreground">
          Razem {board.requests.length}{" "}
          {board.requests.length === 1 ? "request" : "requestów"}
        </span>
      </div>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <RequestBoardFilters
            board={board}
            filters={filters}
            onChange={onFilters}
            shown={shown}
            total={total}
          />
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <div className="min-w-[720px]">
              <div
                className={`grid ${COLS} gap-3 border-b border-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground`}
              >
                <div>Stanowisko · klient</div>
                <div>Termin</div>
                <div>Wysłani</div>
                <div>Kto pracuje</div>
              </div>
              {groups.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                  {board.requests.length === 0
                    ? "Żaden request nie jest w stanie „Szukamy kandydatów”. Ustaw stany w „Porządku w requestach”."
                    : "Żaden request nie pasuje do ustawionych filtrów."}
                </p>
              ) : (
                groups.map((group) => (
                  <section key={group.category_id ?? "none"} aria-label={group.name}>
                    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 px-4 py-2">
                      <Badge variant={competenceTone(group.slug)}>{group.name}</Badge>
                      <span className="text-sm font-semibold">{group.shownLabel}</span>
                      <span className="text-sm text-muted-foreground">{group.detail}</span>
                    </div>
                    {group.rows.map((request) => {
                      const days = daysToDeadline(request.deadline, today)
                      return (
                        <div
                          key={request.job_id}
                          className={`grid ${COLS} items-center gap-3 border-b border-border px-4 py-2 text-sm last:border-0 ${
                            request.champion ? "bg-success-muted/30 text-muted-foreground" : ""
                          }`}
                        >
                          <div className="min-w-0">
                            <Link
                              href={`/jobs/${request.job_id}`}
                              className="font-semibold text-foreground hover:underline"
                            >
                              {request.title}
                            </Link>
                            {request.client_name && (
                              <span className="text-muted-foreground">
                                {" "}
                                · {request.client_name}
                              </span>
                            )}
                          </div>
                          <div
                            className={
                              days !== null && days < 0
                                ? "font-semibold text-destructive"
                                : request.deadline
                                  ? "text-foreground"
                                  : "text-muted-foreground"
                            }
                            title={deadlineLabel(request.deadline, today)}
                          >
                            {request.deadline ? formatDate(request.deadline) : "brak"}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono tabular-nums">{request.sent}</span>
                            {request.champion && <Badge variant="success">Champion</Badge>}
                          </div>
                          <div className="flex flex-col items-start gap-1">
                            {request.people.length === 0 && !canEdit && (
                              <span className="text-muted-foreground">nikt</span>
                            )}
                            {request.people.map((person) => (
                              <PersonChip
                                key={person.user_id}
                                person={person}
                                canEdit={canEdit}
                                onRemove={() =>
                                  onRemovePerson(request.job_id, person.user_id)
                                }
                              />
                            ))}
                            {canEdit && !request.champion && (
                              <AddPerson
                                board={board}
                                request={request}
                                onAdd={(userId, role) =>
                                  onAddPerson(request.job_id, userId, role)
                                }
                              />
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </section>
                ))
              )}
            </div>
          </div>
        </div>
        <aside className="flex w-full flex-col gap-4 xl:w-[360px] xl:shrink-0">
          <LoadPanel load={board.load} today={today} />
          <ChangesPanel changes={board.changes} />
        </aside>
      </div>
    </div>
  )
}

/** Kafel pulpitu — dane, adres i akcje; wygląd w `RequestBoardView`. */
export function RequestBoard() {
  const query = useRequestBoard()
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const user = useAuthStore((state) => state.user)
  const canEdit = hasRole(user, "admin", "delivery_lead", "head_of_recruitment")
  const filters = useMemo(
    () => filtersFromParams(new URLSearchParams(params?.toString() ?? "")),
    [params],
  )

  const setFilters = (next: BoardFilters) => {
    const search = filtersToParams(next, new URLSearchParams(params?.toString() ?? ""))
    const qs = search.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  const refresh = () => queryClient.invalidateQueries({ queryKey: REQUEST_BOARD_QUERY_KEY })

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: false,
    isSuccess: query.isSuccess,
  })
  if (state === "loading") {
    return (
      <div className="h-40 animate-pulse rounded-lg bg-muted" aria-busy="true">
        <span className="sr-only">Wczytywanie requestów…</span>
      </div>
    )
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />
  }
  const board = query.data as RequestBoardData
  return (
    <RequestBoardView
      board={board}
      today={warsawToday()}
      filters={filters}
      onFilters={setFilters}
      canEdit={canEdit}
      onAddPerson={async (jobId, userId, role) => {
        try {
          await addBoardPerson(jobId, userId, role)
          showSuccess("Osoba dodana do requestu.")
        } catch (error) {
          showError(apiErrorMessage(error, "Nie udało się dodać osoby."))
        }
        await refresh()
      }}
      onRemovePerson={async (jobId, userId) => {
        try {
          await removeBoardPerson(jobId, userId)
        } catch (error) {
          showError(apiErrorMessage(error, "Nie udało się zdjąć osoby."))
        }
        await refresh()
      }}
    />
  )
}
