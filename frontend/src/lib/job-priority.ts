import type { JobPriority } from "@/types/client-profile";

/**
 * Priorytet rekrutacji (`Job.priority`) — te same cztery wartości i etykiety,
 * co w `JobFormFields` (`components/AppShell.tsx`, `<FieldGroup label="Priorytet">`).
 * Wyniesione tutaj, żeby `JobSettingsPanel` (dok „Zespół", krok 02) nie
 * duplikował literałów, które przy zmianie backendu łatwo rozjechać.
 */
export const JOB_PRIORITY_OPTIONS: { value: JobPriority; label: string }[] = [
  { value: "low", label: "Niski" },
  { value: "medium", label: "Średni" },
  { value: "high", label: "Wysoki" },
  { value: "urgent", label: "Krytyczny" },
];

export const JOB_PRIORITY_LABEL: Record<JobPriority, string> = Object.fromEntries(
  JOB_PRIORITY_OPTIONS.map((option) => [option.value, option.label]),
) as Record<JobPriority, string>;
