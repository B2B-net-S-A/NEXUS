"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Flame } from "lucide-react"

import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip"
import type { BoardChange, BoardRequest, LoadPerson } from "@/lib/api/requestAllocation"
import { isP0Active } from "@/lib/job-p0"
import { pluralPl } from "@/lib/plural-pl"
import {
  changesSinceLabel,
  deadlineLabel,
  loadBarScale,
  loadSummary,
  orderLoad,
  outsideP1Href,
} from "@/lib/request-board"
import { cn } from "@/lib/utils"

function formatDate(iso: string | null): string {
  if (!iso) return "brak terminu"
  const [y, m, d] = iso.split("-")
  return `${d}.${m}.${y}`
}

/** `2026-09-29` → `29.09` — urlop to sprawa najbliższych dni, rok tylko w podpowiedzi. */
function formatDayMonth(iso: string): string {
  const [, m, d] = iso.split("-")
  return `${d}.${m}`
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/**
 * Szerokość odcinka paska: `value` ze skali listy (`loadBarScale` — najbardziej
 * obłożona osoba ma pełny pasek), najwyżej tyle, ile zostało miejsca.
 */
function barShare(value: number, scale: number, used = 0): string {
  const share = Math.max(Math.min(value, scale - Math.min(used, scale)), 0)
  return `${(share / scale) * 100}%`
}

/**
 * Ile P0 ma osoba (prośba Olafa, 06.11.2026): rekrutacje z P0 — także po
 * terminie, do decyzji — w których pracuje, bez propozycji automatu. Te same
 * dane tablicy co obłożenie, więc bez osobnego zapytania.
 */
export function p0ByPerson(requests: BoardRequest[] | undefined): Map<number, number[]> {
  const out = new Map<number, number[]>()
  for (const r of requests ?? []) {
    if (!isP0Active(r)) continue
    for (const person of r.people) {
      if (person.proposed) continue
      out.set(person.user_id, [...(out.get(person.user_id) ?? []), r.job_id])
    }
  }
  return out
}

/** Wiersz osoby: nazwisko (z urlopem), pasek i liczba; kliknięcie rozwija requesty. */
function PersonRow({
  person,
  scale,
  expanded,
  onToggle,
  p0 = 0,
}: {
  person: LoadPerson
  scale: number
  expanded: boolean
  onToggle: () => void
  p0?: number
}) {
  const proposed = person.proposed ?? 0
  const base = person.base ?? 0
  const linkedin = person.linkedin ?? 0
  const summary = loadSummary(person)
  return (
    <button
      type="button"
      aria-expanded={expanded}
      onClick={onToggle}
      // `relative`: opis dla czytnika ekranu (`sr-only`) jest
      // pozycjonowany absolutnie i ma zostać w obrębie wiersza.
      // Ostatnia kolumna ma stałą szerokość: każdy wiersz jest osobną
      // siatką, więc przy `auto` paski zaczynałyby się w innym
      // miejscu zależnie od tego, czy liczba to „1”, czy „2 + 1”.
      className="relative grid min-h-9 w-full grid-cols-[16px_minmax(0,2fr)_34px_minmax(48px,1fr)_44px] items-center gap-2 rounded-md px-1 py-0.5 text-left text-sm hover:bg-accent"
    >
      {expanded ? (
        <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden />
      ) : (
        <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden />
      )}
      <span className="min-w-0">
        <span className="block truncate" title={person.name}>
          {person.name}
        </span>
        {/* Urlop pod nazwiskiem, pasek zostaje: obłożenie osoby na
            urlopie też trzeba widzieć (ktoś jej requesty przejmie). */}
        {person.leave_until && (
          <span
            className="block truncate text-[11px] leading-tight text-muted-foreground"
            title={`Urlop do ${formatDate(person.leave_until)}`}
            aria-hidden
          >
            urlop do {formatDayMonth(person.leave_until)}
          </span>
        )}
      </span>
      {p0 > 0 ? (
        <span
          className="inline-flex h-5 items-center justify-center gap-0.5 rounded-md bg-destructive px-1 text-[11px] font-bold tabular-nums text-destructive-foreground"
          title={`P0: ${p0}`}
          data-testid="load-p0"
        >
          <Flame className="h-3 w-3" aria-hidden />
          {p0}
        </span>
      ) : (
        <span aria-hidden />
      )}
      <span className="flex h-2.5 overflow-hidden rounded" aria-hidden>
        {/* 0655: odcinki koszyków — Baza, LinkedIn, potem bez koszyka. */}
        <span
          data-load-base
          className="h-full bg-primary"
          style={{ width: barShare(base, scale) }}
        />
        <span
          data-load-linkedin
          className="h-full bg-info"
          style={{ width: barShare(linkedin, scale, base) }}
        />
        <span
          className="h-full bg-primary/40"
          style={{ width: barShare(person.count - base - linkedin, scale, base + linkedin) }}
        />
        {/* Propozycja: jaśniejszy odcinek z przerywaną krawędzią —
            ten sam język co przerywana ramka przy osobie. */}
        {proposed > 0 && (
          <span
            data-load-proposed
            className="h-full border border-dashed border-primary/60 bg-primary/20"
            style={{ width: barShare(proposed, scale, person.count) }}
          />
        )}
      </span>
      <span className="whitespace-nowrap text-right tabular-nums" title={summary.spoken}>
        <span aria-hidden>{summary.label}</span>
        {/* Jedno zdanie dla czytnika ekranu, zaczęte przecinkiem:
            bez niego nazwisko, urlop i „2 + 1” zlewają się w ciąg
            bez odstępów. */}
        <span className="sr-only">
          {`, ${person.leave_until ? `urlop do ${formatDate(person.leave_until)}, ` : ""}${p0 > 0 ? `P0: ${p0}, ` : ""}${summary.spoken}`}
        </span>
      </span>
    </button>
  )
}

function PersonRequests({
  person,
  today,
  className,
  p0Jobs = [],
}: {
  person: LoadPerson
  today: string
  className: string
  p0Jobs?: number[]
}) {
  const outside = person.outside_p1 ?? 0
  const base = person.base ?? 0
  const linkedin = person.linkedin ?? 0
  return (
    <ul className={className}>
      {person.count > 0 && (
        <li className="text-xs text-muted-foreground" data-testid="load-channels">
          Baza: {base} · LinkedIn: {linkedin}
          {person.count - base - linkedin > 0 ? ` · bez koszyka: ${person.count - base - linkedin}` : ""}
        </li>
      )}
      {person.requests.length === 0 ? (
        <li className="text-xs text-muted-foreground">
          Brak rekrutacji P1 — ma miejsce na kolejną.
        </li>
      ) : (
        person.requests.map((r) => (
          <li
            key={`${r.job_id}-${r.proposed ? "proposed" : "working"}`}
            className="flex justify-between gap-2 text-xs text-foreground"
          >
            <Link href={`/jobs/${r.job_id}`} className="truncate hover:underline">
              {p0Jobs.includes(r.job_id) ? (
                <span className="mr-1 rounded bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">P0</span>
              ) : null}
              {r.title}
              {r.client_name ? ` · ${r.client_name}` : ""}
              {r.proposed ? " (propozycja)" : ""}
            </Link>
            <span className="shrink-0 font-mono text-muted-foreground">
              {r.deadline ? formatDate(r.deadline) : deadlineLabel(null, today)}
            </span>
          </li>
        ))
      )}
      {/* Poza obłożeniem, ale nie znika bez śladu: liczba i link do listy. */}
      {outside > 0 && (
        <li className="text-xs text-muted-foreground" data-testid="load-outside-p1">
          Poza P1: {outside} {pluralPl(outside, "rekrutacja", "rekrutacje", "rekrutacji")} —{" "}
          {pluralPl(outside, "nie liczy się", "nie liczą się", "nie liczy się")} do obłożenia.{" "}
          <Link href={outsideP1Href(person.user_id)} className="font-medium text-primary hover:underline">
            Pokaż na liście rekrutacji
          </Link>
        </li>
      )}
    </ul>
  )
}

/**
 * Lista osób z obłożeniem. `columns` = wariant na pulpit („Czeka na Ciebie”):
 * osoby w kilku kolumnach, a requesty klikniętej osoby pod nimi jako lista,
 * jeden request w wierszu — panel stoi nad kafelkami, więc dwadzieścia osób
 * nie może zająć siedmiuset pikseli wysokości.
 */
export function LoadPeople({
  load,
  today,
  columns = false,
  requests,
}: {
  load: LoadPerson[]
  today: string
  columns?: boolean
  requests?: BoardRequest[]
}) {
  const [open, setOpen] = useState<number | null>(null)
  const p0 = useMemo(() => p0ByPerson(requests), [requests])
  // Najwięcej P0 na górze (decyzja Artura 06.11.2026); przy równej liczbie
  // zostaje dotychczasowa kolejność obłożenia (sort jest stabilny).
  const people = useMemo(
    () =>
      [...orderLoad(load)].sort(
        (a, b) => (p0.get(b.user_id)?.length ?? 0) - (p0.get(a.user_id)?.length ?? 0),
      ),
    [load, p0],
  )
  const scale = useMemo(() => loadBarScale(load), [load])
  if (people.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nikt nie ma jeszcze kategorii ani requestu. Przypisz ludzi w Ustawieniach →
        Kategorie kompetencji.
      </p>
    )
  }
  const toggle = (userId: number) => setOpen(open === userId ? null : userId)
  if (!columns) {
    return (
      <ul className="flex flex-col gap-0.5">
        {people.map((person) => (
          <li key={person.user_id}>
            <PersonRow
              person={person}
              scale={scale}
              expanded={open === person.user_id}
              onToggle={() => toggle(person.user_id)}
              p0={p0.get(person.user_id)?.length ?? 0}
            />
            {open === person.user_id && (
              <PersonRequests person={person} today={today} p0Jobs={p0.get(person.user_id)} className="mb-2 ml-6 flex flex-col gap-1" />
            )}
          </li>
        ))}
      </ul>
    )
  }
  const opened = people.find((person) => person.user_id === open)
  return (
    <>
      <ul className="columns-[300px] gap-x-6">
        {people.map((person) => (
          <li key={person.user_id} className="break-inside-avoid">
            <PersonRow
              person={person}
              scale={scale}
              expanded={open === person.user_id}
              onToggle={() => toggle(person.user_id)}
              p0={p0.get(person.user_id)?.length ?? 0}
            />
          </li>
        ))}
      </ul>
      {opened && (
        <div
          role="group"
          aria-label={`Requesty: ${opened.name}`}
          // Szerokość z limitem: termin stoi przy prawej krawędzi wiersza,
          // więc na szerokim monitorze odjeżdżałby daleko od tytułu.
          className="mt-2 max-w-3xl rounded-md border border-border bg-muted/30 px-3 py-2"
        >
          <p className="mb-1 text-xs font-medium text-foreground">{opened.name}</p>
          <PersonRequests
            person={opened}
            today={today}
            p0Jobs={p0.get(opened.user_id)}
            className="flex flex-col divide-y divide-border [&>li]:py-1"
          />
        </div>
      )}
    </>
  )
}

/** Przypis pod listą: co znaczy „+ 1” i czego obłożenie nie liczy. */
export function LoadFootnote({ load }: { load: LoadPerson[] }) {
  const anyProposed = load.some((person) => (person.proposed ?? 0) > 0)
  return (
    <p className="mt-2 text-xs text-muted-foreground">
      {anyProposed ? "„+ 1” to propozycja automatu czekająca na akceptację. " : ""}
      Nie liczą się rekrutacje bez priorytetu, „Przyjmujemy” i z championem.
    </p>
  )
}

/** Podpis panelu — ten sam na pulpicie „Requesty i obłożenie” i w „Czeka na Ciebie”. */
export const LOAD_SUBTITLE = "Ile rekrutacji P1 w stanie „Szukamy” ma każda osoba w roli „Rekruter”."

/**
 * „Obłożenie” — ile rekrutacji P1 ma każda osoba w roli „Rekruter” (prośba
 * Head of Recruitment, decyzja Artura 14.10.2026). Propozycje automatu przed
 * akceptacją stoją osobno („2 + 1”): to jeszcze nie praca. Kliknięcie osoby
 * rozwija jej rekrutacje P1 i liczbę tych spoza P1 (makieta C6).
 */
export function LoadPanel({
  load,
  today,
  requests,
}: {
  load: LoadPerson[]
  today: string
  requests?: BoardRequest[]
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4" aria-label="Obłożenie">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="flex items-center gap-1.5">
          <h3 className="text-sm font-semibold text-foreground">Obłożenie</h3>
          <RequestPriorityChip level="p1" />
        </span>
        <span className="text-xs text-muted-foreground">kliknij osobę</span>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">{LOAD_SUBTITLE}</p>
      <LoadPeople load={load} today={today} requests={requests} />
      <LoadFootnote load={load} />
    </section>
  )
}

const CHANGE_VERB: Record<BoardChange["kind"], string> = {
  assigned: "→",
  released: "zwolnione:",
  champion: "",
}

/**
 * „Zmiany od wczoraj”. `since` = początek okna z backendu (ta sama godzina
 * poprzedniego dnia roboczego) — w poniedziałek okno obejmuje weekend, więc
 * podpis mówi to wprost. `wide` = pełna szerokość na daily: zmiany w dwóch
 * kolumnach, gdy pulpit ma miejsce.
 */
export function ChangesPanel({
  changes,
  since,
  wide = false,
}: {
  changes: BoardChange[]
  since?: string | null
  wide?: boolean
}) {
  const sinceLabel = changesSinceLabel(since)
  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      aria-label="Zmiany od wczoraj"
    >
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-sm font-semibold text-foreground">Zmiany od wczoraj</h3>
        {sinceLabel && (
          <span className="text-xs text-muted-foreground" data-testid="changes-since">
            {sinceLabel}
          </span>
        )}
      </div>
      {changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {sinceLabel ? `Bez zmian ${sinceLabel}.` : "Bez zmian w ciągu ostatniej doby."}
        </p>
      ) : (
        <ul
          className={cn(
            "flex flex-col gap-2",
            wide && "@min-[900px]/rboard:grid @min-[900px]/rboard:grid-cols-2 @min-[900px]/rboard:gap-x-6",
          )}
        >
          {changes.map((c, i) => (
            <li
              key={`${c.kind}-${c.job_id}-${c.user_name ?? ""}-${i}`}
              className="border-b border-border pb-2 text-sm last:border-0"
            >
              <p className="font-medium text-foreground">
                {c.title}
                {c.client_name ? ` · ${c.client_name}` : ""}
                {c.kind === "champion"
                  ? ": champion"
                  : ` ${CHANGE_VERB[c.kind]} ${c.user_name ?? ""}`}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatWhen(c.at)}
                {c.reason ? ` · ${c.reason}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
