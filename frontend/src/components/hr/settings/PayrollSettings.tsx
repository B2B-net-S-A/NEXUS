"use client";

import { Wallet } from "lucide-react";

import { BonusRulesCard } from "@/components/hr/payroll/BonusRulesCard";
import type { HrConfig } from "@/lib/api/hr";

/** Kto zmienia reguły premii — lustro `require_hr_payroll_admin` (Płace, admin zawsze). */
export function canEditPayrollSettings(config: Pick<HrConfig, "me">): boolean {
  return config.me.payroll || config.me.is_admin;
}

/**
 * Ustawienia → Zespół i dostęp → Płace (17.10.2026): reguły premii
 * z placementów i z Ligi. Do 17.10 karta stała w „Kadrach”, do których osoba
 * z samym uprawnieniem „Płace” (Finanse) nie wchodziła, choć API ją wpuszczało.
 */
export function PayrollSettings({ config }: { config: HrConfig }) {
  if (!canEditPayrollSettings(config)) {
    return (
      <div className="p-6 text-muted-foreground">
        Reguły premii zmienia osoba z uprawnieniem „Płace” albo administrator.
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <Wallet className="h-5 w-5 text-primary" aria-hidden />
          Płace
        </h1>
        <p className="text-sm text-muted-foreground">
          Reguły premii z placementów i z Ligi Mistrzów. Stawki i premie osób są w „Ludzie → Płace”.
        </p>
      </div>
      {config.open_modules.payroll ? (
        <BonusRulesCard />
      ) : (
        <p className="text-sm text-muted-foreground">
          Moduł płac nie jest jeszcze włączony — reguły premii ustawisz po jego włączeniu
          (Ustawienia → Kadry → „Moduły”).
        </p>
      )}
    </div>
  );
}
