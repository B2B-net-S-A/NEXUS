"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { MyWhoCountsPanel } from "@/components/insights/sections/WhoCountsPanel";

/**
 * Zwijana lista „Kto się liczy” w „Mój miesiąc” — u rekrutera i u Delivery
 * Leada. Link „Zobacz, kto się liczy” z panelu celów niesie `kto=` w adresie
 * i rozwija listę, także gdy ekran już stoi otwarty (miękka nawigacja nie
 * montuje widoku od nowa). 29.10.2026: po #2593 DL nie miał listy wcale,
 * a u rekrutera link lądował na zwiniętej sekcji.
 */
export function MyWhoCountsSection() {
  const linked = useSearchParams().get("kto");
  const [open, setOpen] = useState(linked !== null);

  useEffect(() => {
    if (linked !== null) setOpen(true);
  }, [linked]);

  return (
    <section className="rounded-xl border border-border bg-card shadow-xs">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center justify-between gap-3 px-4 text-left text-sm font-semibold text-foreground"
      >
        Kto się liczy do celów — osoby za liczbami
        <span className="text-primary">{open ? "Zwiń ▴" : "Pokaż ▾"}</span>
      </button>
      {open ? (
        <div className="border-t border-border p-4">
          <MyWhoCountsPanel />
        </div>
      ) : null}
    </section>
  );
}
