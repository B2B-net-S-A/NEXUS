"use client"

import Link from "next/link"
import { Suspense } from "react"

import { PageHeader } from "@/components/ds/PageHeader"
import { RequestBoard } from "@/components/v2/request-board/RequestBoard"

/**
 * Daily — requesty i obłożenie (04.10.2026). Ten sam pulpit co kafelek
 * „Requesty i obłożenie”, ułożony pod spotkanie: „Zmiany od wczoraj” na górze,
 * kategorie jako przyciski i „Następna kategoria →”. Bramka jak cała sekcja
 * `/jobs` (Pipeline); dane — `GET /api/request-board`.
 */
export default function JobsDailyPage() {
  return (
    <div className="space-y-5 p-4 md:p-6">
      <Link href="/dashboard" className="text-sm font-medium text-primary hover:underline">
        ← Pulpit
      </Link>
      <PageHeader
        title="Daily — requesty i obłożenie"
        description="Co zmieniło się od wczoraj, kto nad czym pracuje i komu brakuje rekrutera — kategoria po kategorii."
      />
      {/* `RequestBoard` czyta adres (`useSearchParams`). */}
      <Suspense
        fallback={
          <div className="h-40 animate-pulse rounded-lg bg-muted" aria-busy="true">
            <span className="sr-only">Wczytywanie requestów…</span>
          </div>
        }
      >
        <RequestBoard variant="daily" scope="all" />
      </Suspense>
    </div>
  )
}
