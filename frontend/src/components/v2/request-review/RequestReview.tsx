"use client"

/**
 * „Porządek w requestach” (makieta Portfel, decyzje Artura 24.09.2026).
 *
 * W Traffit nikt nie zamyka rekrutacji, więc NEXUS pokazywał setki „otwartych”
 * requestów. Delivery Lead decyduje tu, nad czym naprawdę pracujemy. System
 * podpowiada stan z historii pipeline'u (aplikacje z ogłoszeń nie są pracą),
 * DL zatwierdza pojedynczo albo hurtem. „Mamy championa” zmienia przycisk
 * championa (ten sam co w nagłówku rekrutacji) — tu jest zakładką.
 */

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { QueryStateNotice } from "@/components/ds/QueryStateNotice"
import { TabbedNav } from "@/components/ds/TabbedNav"
import { useToast } from "@/components/Toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/lib/api-error"
import {
  REVIEW_PAGE_SIZE,
  changeWorkStates,
  useRequestReview,
  type ReviewResponse,
  type ReviewRow,
} from "@/lib/api/requestAllocation"
import {
  STATE_HINT,
  STATE_LABEL,
  VISIBLE_STATES,
  type VisibleState,
  type WorkState,
} from "@/lib/request-work-state"
import { similarJobsApi } from "@/lib/similar-jobs-api"
import { resolveViewState } from "@/lib/view-state"

const STATE_TONE: Record<VisibleState, "neutral" | "info" | "success" | "warning" | "soft"> = {
  to_review: "neutral",
  searching: "info",
  champion: "success",
  client_silent: "warning",
  finished: "soft",
}

const ACTIONS: { state: WorkState; label: string }[] = [
  { state: "searching", label: "Szukamy" },
  { state: "client_silent", label: "Klient milczy" },
  { state: "finished", label: "Zakończony" },
]

function daysAgo(iso: string | null): string {
  if (!iso) return "—"
  const days = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 86_400_000))
  if (days === 0) return "dziś"
  if (days === 1) return "wczoraj"
  return `${days} dni temu`
}

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  const [y, m, d] = iso.split("-")
  return `${d}.${m}.${y}`
}

export interface RequestReviewActions {
  setState: (changes: { job_id: number; state: WorkState }[]) => void
  dropChampion: (jobId: number) => void
}

export function RequestReviewView({
  data,
  tab,
  onTab,
  mine,
  onMine,
  q,
  onQ,
  actions,
  onMore,
  loadingMore = false,
}: {
  data: ReviewResponse
  tab: VisibleState
  onTab: (tab: VisibleState) => void
  mine: boolean
  onMine: (mine: boolean) => void
  q: string
  onQ: (q: string) => void
  actions: RequestReviewActions
  /** „Pokaż więcej” — gdy lista zakładki ma kolejne strony. */
  onMore?: () => void
  loadingMore?: boolean
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const total = Object.values(data.counts).reduce((a, b) => a + b, 0)
  const suggestions = useMemo(
    () =>
      data.rows
        .filter(
          (r) =>
            !r.closed && selected.has(r.job_id) && r.suggested_state && r.suggested_state !== tab,
        )
        .map((r) => ({ job_id: r.job_id, state: r.suggested_state as WorkState })),
    [data.rows, selected, tab],
  )
  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const bulk = (state: WorkState) => {
    actions.setState([...selected].map((job_id) => ({ job_id, state })))
    setSelected(new Set())
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {(["searching", "champion", "client_silent", "finished"] as const).map((state) => (
          <div key={state} className="flex flex-col gap-1.5 rounded-lg border border-border bg-card p-4">
            <Badge variant={STATE_TONE[state]} className="self-start">
              {STATE_LABEL[state]}
            </Badge>
            <p className="text-sm text-foreground">{STATE_HINT[state]}</p>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2">
          <TabbedNav
            ariaLabel="Stan requestu"
            value={tab}
            onValueChange={(value) => {
              setSelected(new Set())
              onTab(value as VisibleState)
            }}
            tabs={VISIBLE_STATES.map((state) => ({
              value: state,
              label: STATE_LABEL[state],
              count: data.counts[state] ?? 0,
            }))}
          />
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={mine}
                onChange={(e) => onMine(e.target.checked)}
              />
              Tylko moje
            </label>
            <input
              aria-label="Szukaj stanowiska"
              className="h-9 w-48 rounded-md border border-input bg-background px-2 text-sm"
              placeholder="Szukaj stanowiska"
              value={q}
              onChange={(e) => onQ(e.target.value)}
            />
          </div>
        </div>

        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm">
            <span className="mr-2 text-muted-foreground">Zaznaczone: {selected.size}</span>
            {ACTIONS.filter((a) => a.state !== tab).map((a) => (
              <Button key={a.state} size="sm" variant="outline" onClick={() => bulk(a.state)}>
                {a.label}
              </Button>
            ))}
            {suggestions.length > 0 && (
              <Button
                size="sm"
                onClick={() => {
                  actions.setState(suggestions)
                  setSelected(new Set())
                }}
              >
                Przyjmij podpowiedzi ({suggestions.length})
              </Button>
            )}
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-10 px-4 py-2">
                  <span className="sr-only">Zaznacz</span>
                </th>
                <th className="px-2 py-2">Request</th>
                <th className="px-2 py-2">DL</th>
                <th className="px-2 py-2">Termin</th>
                <th className="px-2 py-2">Ostatnia praca</th>
                <th className="px-2 py-2">Ostatnie CV do klienta</th>
                <th className="px-2 py-2">Aplikacje 14 dni</th>
                <th className="px-2 py-2">Podpowiedź</th>
                <th className="px-4 py-2">Decyzja</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                    {q || mine
                      ? "Żaden request nie pasuje do wyszukiwania."
                      : `Brak requestów w stanie „${STATE_LABEL[tab]}”.`}
                  </td>
                </tr>
              ) : (
                data.rows.map((row: ReviewRow) => (
                  <tr key={row.job_id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2">
                      {/* Zamkniętej rekrutacji nie da się przełączyć (serwer: 409),
                          więc nie wchodzi też do zmian hurtowych. */}
                      {row.closed ? null : (
                        <input
                          type="checkbox"
                          aria-label={`Zaznacz: ${row.title}`}
                          className="h-4 w-4 accent-primary"
                          checked={selected.has(row.job_id)}
                          onChange={() => toggle(row.job_id)}
                        />
                      )}
                    </td>
                    <td className="px-2 py-2">
                      <Link href={`/jobs/${row.job_id}`} className="font-semibold hover:underline">
                        {row.title}
                      </Link>
                      {row.client_name && (
                        <div className="text-xs text-muted-foreground">{row.client_name}</div>
                      )}
                    </td>
                    <td className="px-2 py-2">{row.delivery_lead_name ?? "—"}</td>
                    <td className="px-2 py-2 font-mono text-xs">{formatDate(row.deadline)}</td>
                    <td className="px-2 py-2 font-mono text-xs">{daysAgo(row.last_work_at)}</td>
                    <td className="px-2 py-2 font-mono text-xs">
                      {daysAgo(row.last_cv_at)}
                      {row.sent_total ? ` · ${row.sent_total} os.` : ""}
                    </td>
                    <td className="px-2 py-2 font-mono text-xs">{row.applications_14d}</td>
                    <td className="px-2 py-2">
                      {row.suggested_state ? (
                        <div className="flex flex-col gap-1">
                          <Badge variant={STATE_TONE[row.suggested_state]} className="self-start">
                            {STATE_LABEL[row.suggested_state]}
                          </Badge>
                          <span className="text-xs text-muted-foreground">{row.suggestion_reason}</span>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">{row.suggestion_reason}</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {row.closed ? (
                        <span className="text-xs text-muted-foreground">
                          Rekrutacja zamknięta — najpierw ją otwórz.
                        </span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {tab === "champion" ? (
                            <Button size="sm" variant="outline" onClick={() => actions.dropChampion(row.job_id)}>
                              Champion odpadł
                            </Button>
                          ) : null}
                          {ACTIONS.filter((a) => a.state !== tab).map((a) => (
                            <Button
                              key={a.state}
                              size="sm"
                              variant="outline"
                              onClick={() => actions.setState([{ job_id: row.job_id, state: a.state }])}
                            >
                              {a.label}
                            </Button>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      {data.has_more && onMore ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" disabled={loadingMore} onClick={onMore}>
            {loadingMore ? "Wczytuję…" : "Pokaż więcej"}
          </Button>
          <span className="text-xs text-muted-foreground">
            Pokazano {data.rows.length} z {data.total ?? data.rows.length}.
          </span>
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Wszystkich requestów na liście: {total}. „Zakończony” działa w NEXUSIE — w Traffit
        rekrutacja zostaje, jak była.
      </p>
    </div>
  )
}

export function RequestReview() {
  const [tab, setTab] = useState<VisibleState>("to_review")
  const [mine, setMine] = useState(false)
  const [q, setQ] = useState("")
  const [limit, setLimit] = useState(REVIEW_PAGE_SIZE)
  // Nowa zakładka, filtr albo szukanie = od pierwszej strony.
  const trimmed = q.trim()
  useEffect(() => {
    setLimit(REVIEW_PAGE_SIZE)
  }, [tab, mine, trimmed])
  const query = useRequestReview(tab, mine, trimmed, limit)
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["request-work-states"] }),
      queryClient.invalidateQueries({ queryKey: ["request-board"] }),
    ])

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: false,
    isSuccess: query.isSuccess,
  })
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => query.refetch()} />
  }
  if (state === "loading" || !query.data) {
    return <div className="h-64 animate-pulse rounded-lg bg-muted" aria-busy="true" />
  }
  return (
    <RequestReviewView
      data={query.data}
      tab={tab}
      onTab={setTab}
      mine={mine}
      onMine={setMine}
      q={q}
      onQ={setQ}
      onMore={() => setLimit((current) => current + REVIEW_PAGE_SIZE)}
      loadingMore={query.isFetching && query.isPlaceholderData}
      actions={{
        setState: async (changes) => {
          try {
            const result = await changeWorkStates(changes)
            showSuccess(
              result.changed.length === 1
                ? "Zmieniono stan requestu."
                : `Zmieniono stan ${result.changed.length} requestów.`,
            )
          } catch (error) {
            showError(apiErrorMessage(error, "Nie udało się zmienić stanu."))
          }
          await refresh()
        },
        dropChampion: async (jobId) => {
          try {
            await similarJobsApi.setChampionFound(jobId, false)
            showSuccess("Request wrócił do „Szukamy kandydatów”.")
          } catch (error) {
            showError(apiErrorMessage(error, "Nie udało się zdjąć championa."))
          }
          await refresh()
        },
      }}
    />
  )
}
