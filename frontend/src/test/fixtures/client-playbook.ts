import type { ClientPlaybook, PlaybookEvent } from "@/lib/client-playbooks";

/**
 * Pełna karta klienta do testów i harnessów. Literał w każdym teście
 * starzeje się przy pierwszej zmianie kształtu, a fabryka nie.
 */
export function makeClientPlaybook(
  overrides: Partial<ClientPlaybook> = {},
): ClientPlaybook {
  return {
    client_id: 1,
    client_name: "Nordea Bank Abp",
    exists: true,
    version: 3,
    sla_business_days: 5,
    sla_min_candidates: 3,
    cv_limit_per_process: 4,
    hold_hours: 48,
    multi_project_cooldown_days: 90,
    rate_policy: "Maks. 180 PLN/h B2B, bez negocjacji po wysyłce CV.",
    about_for_candidate:
      "Skandynawski bank, zespoły produktowe, praca po angielsku.",
    priority_rules: "Kandydaci z bankowością w pierwszej kolejności",
    process_rules_md: "## Etapy\n1. Screening HR\n2. Zadanie techniczne",
    onboarding_md: "## Po akceptacji\n- NDA w 3 dni\n- dostęp VPN",
    documents: [
      { name: "NDA klienta", url: "https://b2bnetsa.sharepoint.com/nda" },
    ],
    off_limits: { months: 12, scope: "Cały bank", notes: null },
    seed_key: null,
    updated_at: "2026-09-01T10:00:00Z",
    updated_by_name: "Artur",
    ...overrides,
  };
}

/** Odpowiedź GET dla klienta BEZ karty (`exists=false`, `version=0`, pola puste). */
export function makeEmptyClientPlaybook(
  clientId: number,
  clientName: string | null = null,
): ClientPlaybook {
  return makeClientPlaybook({
    client_id: clientId,
    client_name: clientName,
    exists: false,
    version: 0,
    sla_business_days: null,
    sla_min_candidates: null,
    cv_limit_per_process: null,
    hold_hours: null,
    multi_project_cooldown_days: null,
    rate_policy: null,
    about_for_candidate: null,
    priority_rules: null,
    process_rules_md: null,
    onboarding_md: null,
    documents: [],
    off_limits: null,
    updated_at: null,
    updated_by_name: null,
  });
}

export function makePlaybookEvent(
  overrides: Partial<PlaybookEvent> = {},
): PlaybookEvent {
  return {
    id: 1,
    playbook_version: 3,
    action: "saved",
    changes: { sla_business_days: { from: 3, to: 5 } },
    actor_name: "Artur",
    created_at: "2026-09-01T10:00:00Z",
    ...overrides,
  };
}
