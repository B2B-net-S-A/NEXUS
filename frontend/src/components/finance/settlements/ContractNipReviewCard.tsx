"use client";

// „Umowy B2B z NIP-em innej firmy” nad Rozliczeniami (audyt 25.11.2026, decyzja Artura):
// kontrakty, których `partner_nip` z generatora umów wskazuje inkubator albo firmę innej
// osoby. Faktury z takiego NIP-u nie wiążą się już same (tylko przy kwocie równej
// rozliczeniu), więc czekają na karcie osoby jako „NIP kontraktora do zatwierdzenia”.
// Pusta lista = brak karty; awaria zapytania ma własny komunikat, nie znika po cichu.
import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import { useContractNipReview } from "@/lib/api/client-settlements";

export function ContractNipReviewCard() {
  const review = useContractNipReview();
  const [open, setOpen] = useState(false);

  if (review.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(review.error, "Nie udało się sprawdzić NIP-ów z umów B2B.")}
        onRetry={() => review.refetch()}
      />
    );
  }
  const items = review.isSuccess ? (review.data?.items ?? []) : [];
  if (items.length === 0) return null;

  return (
    <section className="rounded-xl border border-warning/40 bg-warning-muted px-3 py-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left text-sm font-medium"
      >
        <StatusDot tone="warning" />
        <span className="min-w-0 flex-1">
          Umowy B2B z NIP-em innej firmy: {items.length}
          <span className="ml-2 font-normal text-muted-foreground">
            faktury z tych NIP-ów czekają na zatwierdzenie na karcie osoby
          </span>
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{open ? "Zwiń" : "Pokaż"}</span>
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-border/60 text-sm">
          {items.map((item) => (
            <li key={item.contract_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5">
              <Link href={`/contracts/${item.contract_id}`} className="font-medium text-primary hover:underline">
                {item.person ?? `Kontrakt ${item.contract_id}`}
              </Link>
              {item.client_name && <span className="text-muted-foreground">{item.client_name}</span>}
              <span className="tabular-nums text-muted-foreground">NIP z umowy {item.partner_nip}</span>
              <span className="basis-full text-xs text-muted-foreground">
                {item.reasons.map((r) => r.label).join(" · ")}
                {item.partner_name ? ` · Partner w umowie: ${item.partner_name}` : ""}
                {item.sellers.length > 0
                  ? ` · Sprzedawca w KSeF: ${item.sellers.map((s) => `${s.name} (${s.invoices})`).join(", ")}`
                  : " · Brak faktur z tego NIP-u w KSeF"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
