"use client"

import { RequestReview } from "@/components/v2/request-review/RequestReview"
import { hasRole, useAuthStore } from "@/store/auth"

/** Rekrutacje → „Porządek w requestach” (0371, decyzje Artura 24.09.2026). */
export default function RequestReviewPage() {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>
  }
  if (!hasRole(user, "admin", "delivery_lead", "head_of_recruitment")) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Brak dostępu — ekran dla Delivery Leadów, Head of Recruitment i administratora.
      </div>
    )
  }
  return (
    <div className="mx-auto max-w-[1440px] space-y-5 p-4 md:p-6">
      <div>
        <p className="text-sm text-muted-foreground">Rekrutacje</p>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">
          Nad którymi requestami naprawdę pracujemy?
        </h1>
        <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
          W Traffit nikt nie zamyka rekrutacji, więc lista „otwartych” jest dużo dłuższa niż
          praca zespołu. System podpowiada stan z historii kandydatów, a Ty zatwierdzasz
          jednym kliknięciem. Tylko „Szukamy kandydatów” dostaje ludzi z przydziału i jest na
          daily.
        </p>
      </div>
      <RequestReview />
    </div>
  )
}
