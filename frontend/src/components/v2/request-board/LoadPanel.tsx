"use client"

import Link from "next/link"
import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

import type { BoardChange, LoadPerson } from "@/lib/api/requestAllocation"
import { deadlineLabel } from "@/lib/request-board"

function formatDate(iso: string | null): string {
  if (!iso) return "brak terminu"
  const [y, m, d] = iso.split("-")
  return `${d}.${m}.${y}`
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

const MAX_BAR = 5

/** „Obłożenie” — kliknięcie osoby rozwija jej requesty (makieta C6). */
export function LoadPanel({ load, today }: { load: LoadPerson[]; today: string }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <section className="rounded-lg border border-border bg-card p-4" aria-label="Obłożenie">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">Obłożenie</h3>
        <span className="text-xs text-muted-foreground">kliknij osobę</span>
      </div>
      {load.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nikt nie ma jeszcze kategorii ani requestu. Przypisz ludzi w Ustawieniach →
          Kategorie kompetencji.
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {load.map((person) => {
            const expanded = open === person.user_id
            return (
              <li key={person.user_id}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : person.user_id)}
                  className="grid min-h-9 w-full grid-cols-[16px_minmax(0,1fr)_minmax(0,1fr)_24px] items-center gap-2 rounded-md px-1 text-left text-sm hover:bg-accent"
                >
                  {expanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden />
                  )}
                  <span className="truncate">{person.name}</span>
                  {person.leave_until ? (
                    <span className="text-xs text-muted-foreground">
                      urlop do {formatDate(person.leave_until)}
                    </span>
                  ) : (
                    <span
                      className="h-2.5 rounded bg-primary"
                      style={{
                        width: `${(Math.min(person.count, MAX_BAR) / MAX_BAR) * 100}%`,
                      }}
                      aria-hidden
                    />
                  )}
                  <span className="text-right font-mono tabular-nums">{person.count}</span>
                </button>
                {expanded && (
                  <ul className="mb-2 ml-6 flex flex-col gap-1">
                    {person.requests.length === 0 ? (
                      <li className="text-xs text-muted-foreground">
                        Brak requestów — ma miejsce na kolejny.
                      </li>
                    ) : (
                      person.requests.map((r) => (
                        <li
                          key={r.job_id}
                          className="flex justify-between gap-2 text-xs text-foreground"
                        >
                          <Link href={`/jobs/${r.job_id}`} className="truncate hover:underline">
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
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        Requesty z championem nie liczą się do obłożenia.
      </p>
    </section>
  )
}

const CHANGE_VERB: Record<BoardChange["kind"], string> = {
  assigned: "→",
  released: "zwolnione:",
  champion: "",
}

export function ChangesPanel({ changes }: { changes: BoardChange[] }) {
  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      aria-label="Zmiany od wczoraj"
    >
      <h3 className="mb-2 text-sm font-semibold text-foreground">Zmiany od wczoraj</h3>
      {changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">Bez zmian w ciągu ostatniej doby.</p>
      ) : (
        <ul className="flex flex-col gap-2">
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
