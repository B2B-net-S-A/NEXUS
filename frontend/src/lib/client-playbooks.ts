/**
 * Karta klienta — typy, wywołania API i hooki współdzielone przez kartę do
 * odczytu (`components/client-playbook/ClientPlaybookCard`), formularz
 * (`ClientPlaybookForm`), zakładkę w edytorze reguł CV, profil klienta,
 * stronę rekrutacji i Pomoc → Klienci.
 *
 * Karta to standardy współpracy per KLIENT (SLA, limity, polityka stawek,
 * „co powiedzieć kandydatowi", reguły priorytetu, zasady procesu, onboarding,
 * dokumenty) — tabela-siostra reguł CV (`client_playbooks`, 1:1 z klientem),
 * prowadzona przez Delivery Leada. Zapis = obowiązuje (bez bramki
 * zatwierdzenia jak w regułach CV); wersja + historia zostają.
 *
 * Off-limit NIE jest polem karty — przychodzi tylko do odczytu z warunków
 * umowy ramowej (`client_contract_terms`) i wyłącznie dla ról z odczytem
 * sekcji Delivery; reszta dostaje `null`.
 *
 * Nazwy `playbookToForm` / `playbookFormToPayload` są celowo inne niż
 * `ruleToForm` / `formToPayload` z `cv-rules.ts` — oba moduły spotykają się
 * w `CvRuleEditor`.
 */

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

export interface PlaybookDocument {
  name: string;
  url: string;
}

export interface PlaybookOffLimits {
  months: number | null;
  scope: string | null;
  notes: string | null;
}

/** Odpowiedź `GET /api/clients/{id}/playbook` (także dla klienta bez karty). */
export interface ClientPlaybook {
  client_id: number;
  client_name: string | null;
  /** `false` + `version: 0` = brak wiersza; GET nigdy nie daje 404 na braku karty. */
  exists: boolean;
  version: number;
  sla_business_days: number | null;
  sla_min_candidates: number | null;
  cv_limit_per_process: number | null;
  hold_hours: number | null;
  multi_project_cooldown_days: number | null;
  rate_policy: string | null;
  about_for_candidate: string | null;
  priority_rules: string | null;
  process_rules_md: string | null;
  onboarding_md: string | null;
  documents: PlaybookDocument[];
  /** Tylko do odczytu — z warunków umowy, nie z karty. */
  off_limits: PlaybookOffLimits | null;
  seed_key: string | null;
  updated_at: string | null;
  updated_by_name: string | null;
}

// UWAGA: `interface X extends Y {}` wywala lint (no-empty-object-type) —
// alias, nie pusty interfejs. Wiersz przeglądu jest dziś identyczny z kartą.
export type ClientPlaybookListItem = ClientPlaybook;

/** Payload `PUT /api/clients/{id}/playbook` — pełna podmiana. */
export interface ClientPlaybookPayload {
  sla_business_days: number | null;
  sla_min_candidates: number | null;
  cv_limit_per_process: number | null;
  hold_hours: number | null;
  multi_project_cooldown_days: number | null;
  rate_policy: string | null;
  about_for_candidate: string | null;
  priority_rules: string | null;
  process_rules_md: string | null;
  onboarding_md: string | null;
  documents: PlaybookDocument[];
}

export interface PlaybookEvent {
  id: number;
  playbook_version: number;
  action: string;
  changes: Record<string, { from: unknown; to: unknown }>;
  actor_name: string | null;
  created_at: string | null;
}

/** Limity długości — lustro walidacji Pydantic w `client_playbooks.py`. */
export const PLAYBOOK_LIMITS = {
  rate_policy: 500,
  text: 4000,
  markdown: 20000,
  documents: 50,
} as const;

/**
 * Etykiety — warstwa prezentacji (karta, formularz, historia). Trzymane
 * tutaj, a nie w komponencie, bo używa ich kilka komponentów naraz.
 * W testach mockuj tylko `@/lib/api`, nigdy ten moduł w całości — inaczej
 * etykiety wychodzą jako `undefined`.
 */
export const PLAYBOOK_FIELD_LABELS: Record<string, string> = {
  sla_business_days: "SLA: dni robocze na pierwszego kandydata",
  sla_min_candidates: "Minimum kandydatów w SLA",
  cv_limit_per_process: "Limit CV na proces",
  hold_hours: "Blokada kandydata (godziny)",
  multi_project_cooldown_days: "Karencja między projektami (dni)",
  rate_policy: "Polityka stawek",
  about_for_candidate: "Co powiedzieć kandydatowi o kliencie",
  priority_rules: "Reguły priorytetu",
  process_rules_md: "Zasady procesu rekrutacji (Markdown)",
  onboarding_md: "Onboarding po akceptacji (Markdown)",
  documents: "Dokumenty (nazwa + link)",
  off_limits: "Off-limit (z warunków umowy)",
};

/** Etykiety akcji historii — backend emituje dziś wyłącznie `saved`;
 *  fallback na surowe `action` jest obowiązkowy u konsumenta. */
export const PLAYBOOK_EVENT_LABELS: Record<string, string> = {
  saved: "Zapisano kartę",
};

export const clientPlaybooksApi = {
  get: async (clientId: number) =>
    (await api.get<ClientPlaybook>(`/api/clients/${clientId}/playbook`)).data,
  save: async (clientId: number, payload: ClientPlaybookPayload) =>
    (await api.put<ClientPlaybook>(`/api/clients/${clientId}/playbook`, payload))
      .data,
  history: async (clientId: number, limit = 10) =>
    (
      await api.get<PlaybookEvent[]>(
        `/api/clients/${clientId}/playbook/history`,
        { params: { limit } },
      )
    ).data,
  overview: async () =>
    (
      await api.get<{ items: ClientPlaybookListItem[] }>(
        "/api/settings/client-playbooks",
      )
    ).data,
};

export const CLIENT_PLAYBOOKS_OVERVIEW_KEY = ["settings-client-playbooks"] as const;

/** Karta jednego klienta. Bez `enabled: hydrated` — używana też w harnessie
 *  `/preview/*`, gdzie store nigdy nie jest zhydrowany. */
export function useClientPlaybook(clientId: number | null | undefined) {
  return useQuery({
    queryKey: ["client-playbook", clientId ?? null],
    enabled: !!clientId,
    queryFn: () => clientPlaybooksApi.get(clientId as number),
    staleTime: 60 * 1000,
  });
}

/** Przegląd wszystkich klientów z kartą (Pomoc → Klienci). */
export function useClientPlaybooksOverview() {
  return useQuery({
    queryKey: CLIENT_PLAYBOOKS_OVERVIEW_KEY,
    queryFn: clientPlaybooksApi.overview,
    staleTime: 60 * 1000,
  });
}

export function useClientPlaybookHistory(clientId: number) {
  return useQuery({
    queryKey: ["client-playbook-history", clientId],
    queryFn: () => clientPlaybooksApi.history(clientId, 10),
  });
}

/**
 * `exists=false` LUB wszystkie pola treści puste. `off_limits` NIE liczy się
 * — pochodzi z umowy, nie z karty, więc nie świadczy o tym, że kartę ktoś
 * wypełnił.
 */
export function isPlaybookEmpty(p: ClientPlaybook | null | undefined): boolean {
  if (!p || !p.exists) return true;
  const ints = [
    p.sla_business_days,
    p.sla_min_candidates,
    p.cv_limit_per_process,
    p.hold_hours,
    p.multi_project_cooldown_days,
  ];
  const texts = [
    p.rate_policy,
    p.about_for_candidate,
    p.priority_rules,
    p.process_rules_md,
    p.onboarding_md,
  ];
  return (
    ints.every((v) => v == null) &&
    texts.every((t) => !t?.trim()) &&
    (p.documents ?? []).length === 0
  );
}

export function formatOffLimits(o: PlaybookOffLimits | null): string | null {
  if (!o) return null;
  const parts: string[] = [];
  if (o.months != null) parts.push(`${o.months} mies.`);
  if (o.scope?.trim()) parts.push(o.scope.trim());
  return parts.join(" · ") || null;
}

/** Formularz: null → "" (kontrolki sterowane), liczby jako string dla <input type="number">. */
export interface PlaybookForm {
  sla_business_days: string;
  sla_min_candidates: string;
  cv_limit_per_process: string;
  hold_hours: string;
  multi_project_cooldown_days: string;
  rate_policy: string;
  about_for_candidate: string;
  priority_rules: string;
  process_rules_md: string;
  onboarding_md: string;
  documents: PlaybookDocument[];
}

const str = (v: number | null) => (v != null ? String(v) : "");

export function playbookToForm(p: ClientPlaybook): PlaybookForm {
  return {
    sla_business_days: str(p.sla_business_days),
    sla_min_candidates: str(p.sla_min_candidates),
    cv_limit_per_process: str(p.cv_limit_per_process),
    hold_hours: str(p.hold_hours),
    multi_project_cooldown_days: str(p.multi_project_cooldown_days),
    rate_policy: p.rate_policy ?? "",
    about_for_candidate: p.about_for_candidate ?? "",
    priority_rules: p.priority_rules ?? "",
    process_rules_md: p.process_rules_md ?? "",
    onboarding_md: p.onboarding_md ?? "",
    documents: (p.documents ?? []).map((d) => ({ name: d.name, url: d.url })),
  };
}

// Kopia z `cv-rules.ts` (tam nieeksportowana), z jedną różnicą: liczby
// ujemne wracają jako `null` — CHECK w bazie i tak by je odrzucił.
function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function playbookFormToPayload(form: PlaybookForm): ClientPlaybookPayload {
  return {
    sla_business_days: intOrNull(form.sla_business_days),
    sla_min_candidates: intOrNull(form.sla_min_candidates),
    cv_limit_per_process: intOrNull(form.cv_limit_per_process),
    hold_hours: intOrNull(form.hold_hours),
    multi_project_cooldown_days: intOrNull(form.multi_project_cooldown_days),
    rate_policy: form.rate_policy.trim() || null,
    about_for_candidate: form.about_for_candidate.trim() || null,
    priority_rules: form.priority_rules.trim() || null,
    process_rules_md: form.process_rules_md.trim() || null,
    onboarding_md: form.onboarding_md.trim() || null,
    // Wiersz bez nazwy albo bez linku nie jedzie do bazy — formularz mówi
    // o tym wprost pod listą dokumentów.
    documents: form.documents
      .map((d) => ({ name: d.name.trim(), url: d.url.trim() }))
      .filter((d) => d.name && d.url),
  };
}
