"use client"

/**
 * Pulpit „Requesty i obłożenie” — makieta C6 (decyzje Artura 24.09.2026).
 *
 * Na daily zespół patrzy, nad czym pracuje: requesty „Szukamy kandydatów”
 * pogrupowane po czterech kategoriach kompetencji, z liczbą requestów w każdej.
 * Kolumny jak na liście rekrutacji (02.10.2026): request z priorytetem
 * i klientem, kategoria, Delivery Lead, data otwarcia, termin, wysłani
 * (+ znacznik „Champion” — request z championem stoi na dole grupy,
 * przygaszony) i Rekruter — osoby, które nad requestem pracują. Po prawej
 * rozwijane „Obłożenie” i „Zmiany od wczoraj”.
 *
 * Automat tylko PROPONUJE osobę (przerywana ramka). Akceptuje ją albo odrzuca
 * Head of Recruitment i admin; do tego czasu nikt nie jest przypisany.
 *
 * Filtry liczy przeglądarka (`lib/request-board.ts`), stan w adresie — link
 * wysłany na daily otwiera ten sam widok. Bez podpowiedzi systemu: Artur
 * wprost ich nie chce na tym ekranie.
 */

import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"

import { QueryStateNotice } from "@/components/ds/QueryStateNotice"
import { useToast } from "@/components/Toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  competenceShortLabel,
  competenceTone,
} from "@/components/v2/CompetenceCategoryBadge"
import { JobDeadlineCell } from "@/components/v2/jobs/JobListCells"
import { RecruiterChips } from "@/components/v2/jobs/RecruiterChips"
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip"
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2"
import { useCapability } from "@/hooks/useCapability"
import { apiErrorMessage } from "@/lib/api-error"
import {
  addBoardPerson,
  decideProposal,
  useRequestBoard,
  type BoardPerson,
  type BoardRequest,
  type RequestBoard as RequestBoardData,
} from "@/lib/api/requestAllocation"
import { formatIsoDatePl } from "@/lib/date-pl"
import { formatDeadlineShort, shortenPersonName } from "@/lib/job-header-subtitle"
import { canRemoveRecruiter, removeRecruiter, workingRecruiters } from "@/lib/job-team"
import { invalidateJobTeam } from "@/lib/job-team-cache"
import { pluralPl } from "@/lib/plural-pl"
import {
  boardPeople,
  filtersFromParams,
  filtersToParams,
  groupRequests,
  loadSummary,
  pendingProposalCount,
  requestWord,
  unstaffedCount,
  type BoardFilters,
  type ShownGroup,
} from "@/lib/request-board"
import { priorityLevelOf } from "@/lib/request-priority"
import { cn } from "@/lib/utils"
import { resolveViewState } from "@/lib/view-state"
import { warsawDateOf } from "@/lib/warsaw-date"

import { ChangesPanel, LoadPanel } from "./LoadPanel"
import { RequestBoardFilters } from "./RequestBoardFilters"

// Układ zależy od szerokości KONTENERA, nie okna: ten sam pulpit stoi
// w kafelku (ok. 330 px na telefonie, 990 px na laptopie) i na pełnej
// szerokości dużego monitora. Dwa nazwane kontenery:
//
//  `rboard` (cały pulpit) — gdzie stoją „Obłożenie” i „Zmiany od wczoraj”:
//    · od 1040 px po prawej (kolumna 300 px; tabeli zostaje ≥ 724 px, czyli
//      mieści się bez przewijania),
//    · 640–1039 px pod tabelą, obok siebie,
//    · poniżej 640 px pod tabelą, jedno pod drugim.
//
//  `rtable` (sama tabela) — ile kolumn:
//    · poniżej 700 px: cztery kolumny o stałej szerokości (razem 700 px),
//      tabela przewija się w poziomie, pierwsza kolumna jest przyklejona;
//    · 700–1059 px: cztery kolumny elastyczne; Kategoria, Delivery Lead
//      i „Otwarta” stoją drobnym drukiem pod tytułem;
//    · od 1060 px: siedem kolumn jak na liście rekrutacji. Próg = pięć kolumn
//      stałych (480 px) + odstępy i marginesy (104 px) + minimum na tytuł
//      (260 px) i osoby (220 px).
const GRID_COLS =
  "grid-cols-[192px_104px_92px_276px] @min-[700px]/rtable:grid-cols-[minmax(0,2fr)_104px_92px_minmax(0,1.6fr)] @min-[1060px]/rtable:grid-cols-[minmax(0,2fr)_84px_116px_84px_104px_92px_minmax(0,1.7fr)]"
/** Komórka kolumny, która istnieje dopiero w szerokiej tabeli. */
const WIDE_ONLY = "hidden @min-[1060px]/rtable:block"
/** Ta sama informacja drobnym drukiem pod tytułem — znika, gdy ma własną kolumnę. */
const FOLDED_ONLY = "@min-[1060px]/rtable:hidden"
/** Pierwsza kolumna przyklejona tam, gdzie tabela przewija się w poziomie. */
const STICKY_FIRST =
  "@max-[699px]/rtable:sticky @max-[699px]/rtable:left-0 @max-[699px]/rtable:z-10 @max-[699px]/rtable:border-r @max-[699px]/rtable:border-border/60 @max-[699px]/rtable:bg-card"

export function warsawToday(now: Date = new Date()): string {
  return now.toLocaleDateString("sv-SE", { timeZone: "Europe/Warsaw" })
}

/** Klucz pary request–osoba dla stanu „zapis trwa”. */
export function boardPersonKey(jobId: number, userId: number): string {
  return `${jobId}:${userId}`
}

const MODE_COPY: Record<RequestBoardData["mode"], { label: string; hint: string }> = {
  off: {
    label: "Automat wyłączony",
    hint: "Przydziały robi się ręcznie.",
  },
  shadow: {
    label: "Automat proponuje — akceptuje Head of Recruitment",
    hint: "Do akceptacji nikt nie jest przypisany.",
  },
  // W trybie „auto” nikt niczego nie zatwierdza: rekruter prowadzący jest
  // przypisany od razu, a Head of Recruitment zmienia tylko to, z czym się
  // nie zgadza.
  auto: {
    label: "Automat przydziela od razu",
    hint: "Rekruter prowadzący jest przypisany zaraz po przekazaniu do searchu — Head of Recruitment może go zmienić.",
  },
}

/** „Na akceptację czekają 2 propozycje.” — pusty napis, gdy nie czeka żadna. */
function pendingSentence(count: number): string {
  if (count <= 0) return ""
  const verb = pluralPl(count, "czeka", "czekają", "czeka")
  const noun = pluralPl(count, "propozycja", "propozycje", "propozycji")
  return ` Na akceptację ${verb} ${count} ${noun}.`
}

function AddPerson({
  board,
  request,
  onAdd,
}: {
  board: RequestBoardData
  request: BoardRequest
  onAdd: (userId: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [userId, setUserId] = useState("")
  // Osobę z samą propozycją automatu da się dodać ręcznie — Delivery Lead nie
  // musi czekać na akceptację; odpadają tylko ci, którzy już pracują.
  const taken = new Set(workingRecruiters(request.people).map((p) => p.user_id))
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
        className="h-8 max-w-full rounded-md border border-input bg-background px-2 text-xs"
        value={userId}
        onChange={(e) => setUserId(e.target.value)}
      >
        <option value="">Wybierz osobę</option>
        {options.map((p) => (
          <option key={p.user_id} value={p.user_id}>
            {p.name} ({loadSummary(p).label})
          </option>
        ))}
      </select>
      <Button
        size="sm"
        disabled={!userId}
        onClick={() => {
          onAdd(Number(userId))
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

export interface RequestBoardViewProps {
  board: RequestBoardData
  today: string
  filters: BoardFilters
  onFilters: (next: BoardFilters) => void
  /** Dodaje i zdejmuje ludzi — capability `job.recruiter.assign`. */
  canStaff: boolean
  /** Akceptuje i odrzuca propozycje automatu — capability `request.proposal.decide`. */
  canDecide: boolean
  onAddPerson: (jobId: number, userId: number) => void
  /** „×” przy osobie: zdjęcie pracującej osoby albo odrzucenie propozycji. */
  onRemovePerson: (request: BoardRequest, person: BoardPerson) => void
  onAcceptProposal: (request: BoardRequest, person: BoardPerson) => void
  /** Pary request–osoba (`boardPersonKey`), których zapis właśnie trwa. */
  busyKeys?: ReadonlySet<string>
}

interface RowProps
  extends Pick<
    RequestBoardViewProps,
    | "board"
    | "canStaff"
    | "canDecide"
    | "onAddPerson"
    | "onRemovePerson"
    | "onAcceptProposal"
    | "busyKeys"
  > {
  request: BoardRequest
  group: ShownGroup
  /** Dzień firmy jako data lokalna — tak liczy termin lista rekrutacji. */
  now: Date
}

function RequestRow({
  board,
  request,
  group,
  now,
  canStaff,
  canDecide,
  onAddPerson,
  onRemovePerson,
  onAcceptProposal,
  busyKeys,
}: RowProps) {
  const people = boardPeople(request)
  const busy = (person: BoardPerson) =>
    busyKeys?.has(boardPersonKey(request.job_id, person.user_id)) === true
  const categoryShort =
    group.category_id === null ? null : (competenceShortLabel(group.slug) ?? group.name)
  const lead = request.delivery_lead ?? null
  const opened = warsawDateOf(request.opened_effective_at)
  // Drobny druk pod tytułem; pozycje „zwinięte” znikają, gdy mają własną kolumnę.
  const meta: { key: string; text: string; title: string; folded: boolean }[] = []
  if (request.client_name) {
    meta.push({ key: "client", text: request.client_name, title: "Klient", folded: false })
  }
  if (categoryShort) {
    meta.push({ key: "cat", text: categoryShort, title: `Kategoria: ${group.name}`, folded: true })
  }
  if (lead) {
    meta.push({
      key: "lead",
      text: `DL: ${shortenPersonName(lead.name) ?? lead.name}`,
      title: `Delivery Lead: ${lead.name}`,
      folded: true,
    })
  }
  if (opened) {
    meta.push({
      key: "opened",
      text: `otwarta ${formatDeadlineShort(opened) ?? formatIsoDatePl(opened)}`,
      title: `Otwarta ${formatIsoDatePl(opened)}`,
      folded: true,
    })
  }

  return (
    <div
      className={cn(
        "grid gap-x-3 border-b border-border text-sm last:border-0",
        GRID_COLS,
        request.champion && "bg-success-muted/30 text-muted-foreground",
      )}
    >
      <div
        className={cn(
          "flex min-w-0 flex-col justify-center self-stretch py-2 pl-4",
          STICKY_FIRST,
        )}
      >
        <div className="flex min-w-0 items-start gap-1.5">
          <Link
            href={`/jobs/${request.job_id}`}
            title={request.title}
            className="line-clamp-2 min-w-0 break-words font-semibold leading-snug text-foreground hover:underline"
          >
            {request.title}
          </Link>
          <RequestPriorityChip level={priorityLevelOf(request)} className="mt-0.5 shrink-0" />
        </div>
        {meta.length > 0 && (
          <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] text-muted-foreground">
            {meta.map((item, index) => (
              <span
                key={item.key}
                title={item.title}
                className={cn("min-w-0 max-w-full truncate", item.folded && FOLDED_ONLY)}
              >
                {index > 0 ? "· " : ""}
                {item.text}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className={cn(WIDE_ONLY, "self-center")} data-testid="request-category-cell">
        {categoryShort ? (
          <Badge variant={competenceTone(group.slug)} size="sm" title={group.name}>
            {categoryShort}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </div>
      <div
        className={cn(WIDE_ONLY, "min-w-0 self-center truncate text-xs text-foreground")}
        title={lead ? lead.name : undefined}
        data-testid="request-lead-cell"
      >
        {lead ? lead.name : <span className="text-muted-foreground">—</span>}
      </div>
      <div
        className={cn(
          WIDE_ONLY,
          "self-center whitespace-nowrap text-xs tabular-nums text-muted-foreground",
        )}
        data-testid="request-opened-cell"
      >
        {opened ? formatIsoDatePl(opened) : "—"}
      </div>
      <div className="self-center py-2">
        <JobDeadlineCell deadline={request.deadline} now={now} />
      </div>
      <div className="flex items-center gap-2 self-center">
        <span className="font-mono tabular-nums">{request.sent}</span>
        {request.champion && <Badge variant="success">Champion</Badge>}
      </div>
      {/* „+ osoba” stoi w tej samej linii co osoby, dopóki się mieści. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 self-center py-2 pr-4">
        <RecruiterChips
          people={people}
          size="sm"
          // Lista nie szersza niż kolumna: długie nazwisko obcina się w chipie,
          // zamiast wypychać tabelę w poziome przewijanie.
          className="max-w-full"
          label={`Rekruter: ${request.title}`}
          onRemove={(person) => onRemovePerson(request, person)}
          canRemove={(person) =>
            !busy(person) &&
            canRemoveRecruiter(person, { canStaff, canDecide, canEdit: false })
          }
          proposalActions={(person) =>
            canDecide ? (
              <Button
                size="sm"
                loading={busy(person)}
                onClick={() => onAcceptProposal(request, person)}
                aria-label={`Akceptuj propozycję: ${person.name} — ${request.title}`}
              >
                Akceptuj
              </Button>
            ) : (
              <span className="text-[11px] text-muted-foreground">czeka na akceptację</span>
            )
          }
          emptyLabel={
            request.champion ? (
              // Mamy championa — nikt już nie szuka, więc brak osoby to nie alarm.
              <span className="text-muted-foreground">nikt</span>
            ) : (
              <span className="rounded-full bg-warning-muted px-2 py-0.5 text-xs font-medium text-warning-muted-foreground">
                Bez rekrutera
              </span>
            )
          }
        />
        {canStaff && !request.champion && (
          <AddPerson
            board={board}
            request={request}
            onAdd={(userId) => onAddPerson(request.job_id, userId)}
          />
        )}
      </div>
    </div>
  )
}

export function RequestBoardView({
  board,
  today,
  filters,
  onFilters,
  canStaff,
  canDecide,
  onAddPerson,
  onRemovePerson,
  onAcceptProposal,
  busyKeys,
}: RequestBoardViewProps) {
  const { groups, shown, total } = useMemo(
    () => groupRequests(board, filters, today),
    [board, filters, today],
  )
  const unstaffed = useMemo(
    () => unstaffedCount(board, filters, today),
    [board, filters, today],
  )
  // Termin liczymy względem dnia firmy (Europe/Warsaw), nie zegara przeglądarki.
  const now = useMemo(() => {
    const [year, month, day] = today.split("-").map(Number)
    return new Date(year, month - 1, day, 12)
  }, [today])
  const mode = MODE_COPY[board.mode]

  return (
    <div className="@container/rboard flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Requesty i obłożenie</h2>
          <p className="text-sm text-muted-foreground">
            {mode.label}. {mode.hint}
            {pendingSentence(pendingProposalCount(board))}
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
          Razem {board.requests.length} {requestWord(board.requests.length)}
        </span>
      </div>

      <div className="flex flex-col gap-4 @min-[1040px]/rboard:flex-row @min-[1040px]/rboard:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <RequestBoardFilters
            board={board}
            filters={filters}
            onChange={onFilters}
            shown={shown}
            total={total}
            unstaffed={unstaffed}
          />
          {/* `relative`: nazwy dla czytników ekranu w komórkach są pozycjonowane
              absolutnie i mają zostać w obrębie przewijanej tabeli. */}
          <div className="@container/rtable relative overflow-x-auto rounded-lg border border-border bg-card">
            <div className="min-w-[700px] @min-[700px]/rtable:min-w-0">
              <div
                className={cn(
                  "grid gap-x-3 border-b border-border text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                  GRID_COLS,
                )}
              >
                <div className={cn("py-2 pl-4", STICKY_FIRST)}>Request</div>
                <div className={cn(WIDE_ONLY, "py-2")}>Kategoria</div>
                <div className={cn(WIDE_ONLY, "py-2")}>Delivery Lead</div>
                <div className={cn(WIDE_ONLY, "py-2")}>Otwarta</div>
                <div className="py-2">Termin</div>
                <div className="py-2">Wysłani</div>
                <div className="py-2 pr-4">Rekruter</div>
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
                    {group.rows.map((request) => (
                      <RequestRow
                        key={request.job_id}
                        board={board}
                        request={request}
                        group={group}
                        now={now}
                        canStaff={canStaff}
                        canDecide={canDecide}
                        onAddPerson={onAddPerson}
                        onRemovePerson={onRemovePerson}
                        onAcceptProposal={onAcceptProposal}
                        busyKeys={busyKeys}
                      />
                    ))}
                  </section>
                ))
              )}
            </div>
          </div>
        </div>
        <aside className="grid w-full gap-4 @min-[640px]/rboard:grid-cols-2 @min-[1040px]/rboard:w-[300px] @min-[1040px]/rboard:shrink-0 @min-[1040px]/rboard:grid-cols-1">
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
  const { showError, showInfo, showSuccess } = useToast()
  const { askConfirm, confirmDialog } = useConfirmV2()
  const canStaff = useCapability("job.recruiter.assign")
  const canDecide = useCapability("request.proposal.decide")
  const [busyKeys, setBusyKeys] = useState<ReadonlySet<string>>(() => new Set())
  const filters = useMemo(
    () => filtersFromParams(new URLSearchParams(params?.toString() ?? "")),
    [params],
  )

  const setFilters = (next: BoardFilters) => {
    const search = filtersToParams(next, new URLSearchParams(params?.toString() ?? ""))
    const qs = search.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  /**
   * Jeden zapis dotyczący pary request–osoba. Odświeżamy także po błędzie:
   * odmowa (np. 409 „propozycja nieaktualna”) znaczy, że pulpit pokazuje stan,
   * którego już nie ma.
   */
  const run = async (
    jobId: number,
    userId: number,
    action: () => Promise<unknown>,
    failure: string,
  ): Promise<boolean> => {
    const key = boardPersonKey(jobId, userId)
    setBusyKeys((prev) => new Set(prev).add(key))
    try {
      await action()
      return true
    } catch (error) {
      showError(apiErrorMessage(error, failure))
      return false
    } finally {
      setBusyKeys((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
      invalidateJobTeam(queryClient, jobId)
    }
  }

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
    <>
      <RequestBoardView
        board={board}
        today={warsawToday()}
        filters={filters}
        onFilters={setFilters}
        canStaff={canStaff}
        canDecide={canDecide}
        busyKeys={busyKeys}
        onAddPerson={async (jobId, userId) => {
          const added = await run(
            jobId,
            userId,
            () => addBoardPerson(jobId, userId),
            "Nie udało się dodać osoby.",
          )
          if (added) showSuccess("Osoba dodana do requestu.")
        }}
        onRemovePerson={async (request, person) => {
          if (person.proposed) {
            const confirmed = await askConfirm({
              title: `Odrzucić propozycję: ${person.name}?`,
              description: `Automat nie zaproponuje już tej osoby do requestu „${request.title}”. Nadal można ją przypisać ręcznie.`,
              confirmLabel: "Odrzuć propozycję",
            })
            if (!confirmed) return
            // Trasa decyzji, nie zdjęcia osoby: gdyby ktoś w międzyczasie
            // przypisał tę osobę ręcznie, „odrzuć” ma skończyć się odmową,
            // a nie zdjąć pracującego rekrutera.
            const rejected = await run(
              request.job_id,
              person.user_id,
              () => decideProposal(request.job_id, person.user_id, { decision: "reject" }),
              "Nie udało się odrzucić propozycji.",
            )
            if (rejected) showInfo("Propozycja odrzucona.")
            return
          }
          const confirmed = await askConfirm({
            title: `Zdjąć z requestu: ${person.name}?`,
            description: `${person.name} przestanie pracować nad „${request.title}”.`,
            confirmLabel: "Zdejmij",
            variant: "destructive",
          })
          if (!confirmed) return
          await run(
            request.job_id,
            person.user_id,
            () => removeRecruiter(request.job_id, person, { canStaff: true }),
            "Nie udało się zdjąć osoby.",
          )
        }}
        onAcceptProposal={async (request, person) => {
          const accepted = await run(
            request.job_id,
            person.user_id,
            () => decideProposal(request.job_id, person.user_id, { decision: "accept" }),
            "Nie udało się zaakceptować propozycji.",
          )
          if (accepted) showSuccess(`${person.name} pracuje nad „${request.title}”.`)
        }}
      />
      {confirmDialog}
    </>
  )
}
