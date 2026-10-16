"use client";

import { Users } from "lucide-react";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { HrSettings } from "@/components/hr/settings/HrSettings";

// Ustawienia → Zespół i dostęp → Kadry („Ludzie w NEXUSIE”). Dni wolne firmy
// zmieniają Kadry, przełączniki modułów — administrator.
export default function HrSettingsPage() {
  return (
    <HrConfigGate>
      {(config) =>
        config.me.people_admin || config.me.is_admin ? (
          <div className="mx-auto max-w-7xl space-y-6">
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
                <Users className="h-5 w-5 text-primary" aria-hidden />
                Kadry
              </h1>
              <p className="text-sm text-muted-foreground">
                Dni wolne firmy i moduły „Ludzi w NEXUSIE”.
              </p>
            </div>
            <HrSettings config={config} />
          </div>
        ) : (
          <div className="p-6 text-muted-foreground">
            Ustawienia Kadr zmienia osoba z uprawnieniem „Kadry” albo administrator.
          </div>
        )
      }
    </HrConfigGate>
  );
}
