"use client";

import Link from "next/link";
import { Lock } from "lucide-react";

import { reviewBatchBlock } from "@/lib/api/reviewBatch";

/**
 * Wyszukiwanie zablokowane do minimum porcji (makieta M6). Pokazuj zamiast
 * komunikatu błędu, gdy serwer odpowiedział 423 `REVIEW_MINIMUM_PENDING`.
 * Zwraca `null` dla każdego innego błędu — wtedy ekran pokazuje swój.
 */
export function ReviewBatchBlockedNotice({ error }: { error: unknown }) {
  const block = reviewBatchBlock(error);
  if (!block) return null;
  const overdueOnly = block.overdue > 0 && block.remaining === 0;
  return (
    <div
      className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm space-y-2"
      role="status"
      data-testid="review-batch-blocked"
    >
      <div className="flex items-center gap-2 font-semibold">
        <Lock className="h-4 w-4" aria-hidden="true" />
        {overdueOnly
          ? `Najpierw domknij screeningi po terminie: ${block.overdue}.`
          : `Najpierw porcja od Nexusa: zostało ${block.remaining} z ${block.required} decyzji.`}
      </div>
      <p className="text-muted-foreground">
        Wyszukiwanie ręczne wróci {overdueOnly ? "po wpisaniu wyników albo odrzuceniu" : "po minimum"}. Konkretną osobę znajdziesz po imieniu
        i nazwisku, telefonie albo mailu, a osobę spoza bazy dodasz zawsze.
      </p>
      <Link
        href="/porcja"
        className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
      >
        {overdueOnly ? "Domknij screeningi" : "Przejrzyj teraz"}
      </Link>
    </div>
  );
}
