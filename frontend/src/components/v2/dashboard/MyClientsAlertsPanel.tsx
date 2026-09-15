"use client"

/**
 * Panel „Moi klienci" na dashboardzie Delivery Leada.
 *
 * Osobny kanał od „Moje zadania → Powiadomienia": tam zostają zdarzenia
 * rekrutacyjne, tu wyłącznie sprawy wymagające działania DL wobec zamówień
 * i kontraktów jego klientów. Każda karta to JEDNA sprawa (powtórki składa
 * serwer), z checkboxem „zrobione" i przyciskiem prowadzącym wprost do
 * konkretnego zamówienia, kontraktu albo dokumentu.
 *
 * Odhaczenie zamyka sprawę na serwerze (wszystkie powtórki), zatrzymuje
 * dalsze przypomnienia i zostawia wpis w historii zamówienia. Karta znika
 * od razu (optymistycznie); przy błędzie wraca z komunikatem.
 */

import Link from "next/link"
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, Users } from "lucide-react"

import { QueryStateNotice } from "@/components/ds"
import { useToast } from "@/components/Toast"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import {
  dlAlertsApi,
  type DlAlertCard,
  type DlAlertCardsResponse,
  type DlAlertSection,
} from "@/lib/api/dlAlerts"
import { DASHBOARD_SECTION_POLL_MS } from "@/lib/polling"
import { cn } from "@/lib/utils"

import { DlAlertsSection } from "./DlAlertsSection"

export const MY_CLIENTS_CARDS_QUERY_KEY = ["dl-alerts", "cards"] as const

const SECTIONS: { key: DlAlertSection; title: string }[] = [
  { key: "ending", title: "Kończące się zamówienia i umowy" },
  { key: "new_contractor", title: "Nowi kontraktorzy — draft zamówienia" },
  { key: "order_mail", title: "Zamówienia z maila do weryfikacji" },
  { key: "decision", title: "Decyzje po zakończeniu współpracy" },
]

const REPEAT_DAYS = 7

function daysLabel(days: number): string {
  if (days <= 0) return "dziś"
  return days === 1 ? "1 dzień" : `${days} dni`
}

export function cardPill(card: DlAlertCard): string {
  if (card.section === "new_contractor") return "Uzupełnij"
  if (card.section === "order_mail") return "Weryfikacja"
  if (card.section === "decision") return "Decyzja"
  const urgent = card.priority === "high"
  if (card.days_left !== null) {
    return urgent ? `${daysLabel(card.days_left)} — pilne` : daysLabel(card.days_left)
  }
  if (card.alert_type === "cost_order_exhausted") return "Wyczerpane"
  if (card.alert_type === "order_missing_successor") return "Brak zamówienia"
  if (urgent) return "Pilne"
  return card.alert_type === "cost_budget_low" ? "Budżet" : "Mało MD"
}

export function cardCta(card: DlAlertCard): string {
  switch (card.alert_type) {
    case "contract_ending":
      return "Przejdź do kontraktu"
    case "framework_contract_expiring":
      return "Przejdź do umowy"
    case "new_contractor_draft":
    case "draft_consultant_unassigned":
    case "missing_revenue_rate":
      return "Uzupełnij zamówienie"
    case "order_mail_review":
      return "Przejdź do weryfikacji"
    case "md_consultant_ended":
      return "Podejmij decyzję"
    default:
      return "Przejdź do zamówienia"
  }
}

function formatDay(iso: string | null): string | null {
  if (!iso) return null
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toLocaleDateString("pl-PL", { timeZone: "Europe/Warsaw" })
}

export function cardMeta(card: DlAlertCard): string {
  if (card.section === "decision") {
    return "Zamknie się po podjęciu decyzji w zamówieniu"
  }
  if (card.section === "order_mail") {
    const day = formatDay(card.received_at)
    return day ? `Wczytane automatycznie z maila ${day}` : "Wczytane automatycznie z maila"
  }
  if (card.alert_type === "new_contractor_draft" && card.source === "b2b_generator") {
    return "Draft utworzony automatycznie z Generatora umów"
  }
  // Karta pilna (T-7 / próg tempa) nie ma już kolejnej powtórki — zostaje
  // w panelu do odhaczenia albo do chwili, gdy przyczyna ustąpi.
  const tail =
    card.priority === "high"
      ? "karta zostaje do odhaczenia"
      : `powtórka za ${REPEAT_DAYS} dni, jeśli nieodhaczone`
  if (card.email_sent) return `Wysłano również mail z przypomnieniem · ${tail}`
  if (card.email_requested) return `Mail z przypomnieniem w drodze · ${tail}`
  return card.repeat_count <= 1
    ? `Pierwsze przypomnienie · kolejne za ${REPEAT_DAYS} dni`
    : `${card.repeat_count}. przypomnienie · kolejne za ${REPEAT_DAYS} dni`
}

/** Pogrubia nazwisko i datę w treści przychodzącej z serwera (bez HTML). */
function Highlighted({ text, marks }: { text: string; marks: (string | null)[] }) {
  const needles = marks.filter((mark): mark is string => Boolean(mark && mark.trim()))
  if (needles.length === 0) return <>{text}</>
  const escaped = needles.map((needle) => needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "g"))
  return (
    <>
      {parts.map((part, index) =>
        needles.includes(part) ? (
          <strong key={index} className="font-semibold text-foreground">
            {part}
          </strong>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

function tone(card: DlAlertCard): "high" | "standard" | "action" {
  if (card.priority === "high") return "high"
  if (card.section === "ending") return "standard"
  return "action"
}

function AlertCardItem({
  card,
  onDone,
  pending,
}: {
  card: DlAlertCard
  onDone: (card: DlAlertCard) => void
  pending: boolean
}) {
  const kind = tone(card)
  const pill = cardPill(card)
  return (
    <li
      data-testid="my-clients-card"
      data-priority={card.priority}
      className={cn(
        "flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between sm:p-4",
        kind === "high" && "border-destructive/30 bg-destructive-muted",
        kind === "standard" && "border-warning/30 bg-warning-muted",
        kind === "action" && "border-border bg-muted/50",
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <Checkbox
          className={cn(
            "mt-0.5 h-5 w-5",
            kind === "high" && "border-destructive/60",
            kind === "standard" && "border-warning/60",
          )}
          checked={false}
          disabled={!card.can_mark_handled || pending}
          onCheckedChange={() => onDone(card)}
          aria-label={
            card.can_mark_handled
              ? `Oznacz jako zrobione: ${card.client_name} — ${card.alert_type_label}`
              : "Ta sprawa zamknie się po podjęciu decyzji w zamówieniu"
          }
          title={
            card.can_mark_handled
              ? "Zrobione"
              : "Zamknie się po podjęciu decyzji w zamówieniu"
          }
        />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-foreground">
              {card.client_name}
            </span>
            <Badge
              size="sm"
              variant={
                kind === "high" ? "danger" : kind === "standard" ? "warning" : "outline"
              }
            >
              {pill}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            <Highlighted
              text={card.message}
              marks={[card.candidate_name, card.end_date]}
            />
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{cardMeta(card)}</p>
        </div>
      </div>
      {card.link ? (
        <Link
          href={card.link}
          className="inline-flex shrink-0 items-center justify-center self-start rounded-md border border-primary/40 bg-card px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 sm:self-center"
        >
          {cardCta(card)}
        </Link>
      ) : null}
    </li>
  )
}

export function MyClientsAlertsPanel({
  refetchIntervalMs = DASHBOARD_SECTION_POLL_MS,
}: {
  /** Publiczny harness podglądu wyłącza odpytywanie (`false`) — zapytanie bez
   *  sesji wraca 401, a interceptor przerzuca stronę na /login. */
  refetchIntervalMs?: number | false
} = {}) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [historyOpen, setHistoryOpen] = useState(false)

  const query = useQuery({
    queryKey: MY_CLIENTS_CARDS_QUERY_KEY,
    queryFn: async () => (await dlAlertsApi.cards()).data,
    staleTime: 30_000,
    refetchInterval: refetchIntervalMs,
    refetchOnWindowFocus: true,
  })

  const markDone = useMutation({
    mutationFn: (card: DlAlertCard) => dlAlertsApi.markHandled(card.id),
    onMutate: async (card) => {
      await queryClient.cancelQueries({ queryKey: MY_CLIENTS_CARDS_QUERY_KEY })
      const previous = queryClient.getQueryData<DlAlertCardsResponse>(
        MY_CLIENTS_CARDS_QUERY_KEY,
      )
      if (previous) {
        const cards = previous.cards.filter((item) => item.id !== card.id)
        queryClient.setQueryData<DlAlertCardsResponse>(MY_CLIENTS_CARDS_QUERY_KEY, {
          cards,
          total: cards.length,
        })
      }
      return { previous }
    },
    onError: (_error, _card, context) => {
      if (context?.previous) {
        queryClient.setQueryData(MY_CLIENTS_CARDS_QUERY_KEY, context.previous)
      }
      showToast("Nie udało się oznaczyć sprawy jako zrobionej.", "error")
    },
    onSuccess: () => {
      showToast("Oznaczono jako zrobione — przypomnienia wstrzymane", "success")
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["dl-alerts"] })
    },
  })

  const cards = query.data?.cards ?? []
  const total = cards.length

  return (
    <section aria-labelledby="my-clients-heading" data-testid="my-clients-panel">
      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between gap-3 bg-card p-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Users className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <h2
                id="my-clients-heading"
                className="text-base font-semibold text-foreground"
              >
                Moi klienci
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Zamówienia, kontrakty i weryfikacje wymagające Twojego działania
              </p>
            </div>
          </div>
          {/* Licznik dopiero po udanym pobraniu — „0" przed odpowiedzią
              twierdziłoby, że nic nie ma, zanim cokolwiek wiadomo. */}
          {query.isSuccess ? (
            <Badge variant={total > 0 ? "danger" : "success"} size="md">
              {total > 0 ? `${total} do zrobienia` : "Wszystko załatwione"}
            </Badge>
          ) : null}
        </div>

        <div className="border-t border-border p-4">
          {/* Kolejność: awaria → nie wiem → pustka → dane. Pusty stan wisi na
              `isSuccess`, inaczej przerwa między ponowieniami udaje „brak spraw". */}
          {query.isError ? (
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać spraw klientów."
              onRetry={() => query.refetch()}
            />
          ) : !query.isSuccess ? (
            <div className="space-y-3" aria-label="Wczytywanie spraw klientów">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-20 w-full" />
              ))}
            </div>
          ) : total === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Brak spraw do zrobienia u Twoich klientów.
            </p>
          ) : (
            <div className="space-y-5">
              {SECTIONS.map((section) => {
                const items = cards.filter((card) => card.section === section.key)
                if (items.length === 0) return null
                return (
                  <div key={section.key}>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      {section.title}
                    </h3>
                    <ul className="space-y-3">
                      {items.map((card) => (
                        <AlertCardItem
                          key={card.event_key ?? card.id}
                          card={card}
                          pending={markDone.isPending && markDone.variables?.id === card.id}
                          onDone={(item) => markDone.mutate(item)}
                        />
                      ))}
                    </ul>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <li className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-destructive" aria-hidden />
              Wysoki priorytet (≤7 dni) + mail
            </li>
            <li className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-warning" aria-hidden />
              Przypomnienie standardowe
            </li>
            <li className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-muted-foreground/40" aria-hidden />
              Wymaga uzupełnienia / weryfikacji
            </li>
          </ul>
          <button
            type="button"
            onClick={() => setHistoryOpen((open) => !open)}
            aria-expanded={historyOpen}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            Historia i eksport
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition-transform", historyOpen && "rotate-180")}
              aria-hidden
            />
          </button>
        </div>
        {historyOpen ? (
          <div className="border-t border-border p-4">
            <DlAlertsSection initialTab="handled" />
          </div>
        ) : null}
      </Card>
    </section>
  )
}
