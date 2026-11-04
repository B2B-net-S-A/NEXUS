/**
 * Trzy fakty w nagłówku rekrutacji: klient, budżet, tryb pracy (decyzja
 * Artura 02.10.2026 — mają się rzucać w oczy). Reszta dawnej linijki
 * (rekruter, Delivery Lead, hiring manager, termin, obsada) mieszka w widoku
 * „Zlecenie i Champion”.
 */

import { formatJobBudgetLabel, type JobBudgetSource } from "@/lib/job-budget";
import { officeDaysLabel } from "@/lib/office-days";

export interface JobHeaderFactsSource extends JobBudgetSource {
  client_name?: string | null;
  /** Serwer: budżet istnieje, nawet gdy kwota jest dla tej roli ukryta. */
  has_budget_hourly?: boolean | null;
  remote_policy?: string | null;
  onsite_days_per_week?: number | null;
  onsite_days_per_month?: number | null;
  location?: string | null;
}

export type JobHeaderFactKey = "client" | "budget" | "work_mode";

export interface JobHeaderFact {
  key: JobHeaderFactKey;
  label: string;
  /** `null` = nie podano (nagłówek mówi to wprost, nie zostawia pustki). */
  value: string | null;
}

/** Etykiety trybu pracy — lustro `RemotePolicy` (`backend/app/models/job.py`). */
const REMOTE_POLICY_LABEL: Record<string, string> = {
  onsite: "Stacjonarnie",
  hybrid: "Hybrydowo",
  remote: "Zdalnie",
};

/** „Hybrydowo · 2 dni w tygodniu · Warszawa”, „Zdalnie”, „Stacjonarnie · Gdańsk”. */
export function jobWorkModeFact(job: JobHeaderFactsSource): string | null {
  const mode = job.remote_policy ? REMOTE_POLICY_LABEL[job.remote_policy] : undefined;
  if (!mode) return null;
  if (job.remote_policy === "remote") return mode;
  const days =
    job.remote_policy === "hybrid"
      ? officeDaysLabel(job.onsite_days_per_week, job.onsite_days_per_month)
      : null;
  return [mode, days, job.location?.trim() || null].filter(Boolean).join(" · ");
}

export function jobHeaderFacts(job: JobHeaderFactsSource): JobHeaderFact[] {
  const budget = formatJobBudgetLabel(job);
  return [
    { key: "client", label: "Klient", value: job.client_name?.trim() || null },
    {
      key: "budget",
      label: "Budżet",
      value:
        budget != null
          ? budget
          : job.has_budget_hourly
            ? "ukryty dla Twojej roli"
            : null,
    },
    { key: "work_mode", label: "Tryb pracy", value: jobWorkModeFact(job) },
  ];
}
