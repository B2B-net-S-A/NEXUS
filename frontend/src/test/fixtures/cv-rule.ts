import type { ClientCvRule, ClientCvRuleListItem } from "@/lib/cv-rules";

/**
 * Pełna reguła CV do testów i harnessów. Typ reguły ma ~35 pól; literał
 * w każdym teście starzeje się przy pierwszej migracji, a fabryka nie.
 */
export function makeCvRule(overrides: Partial<ClientCvRule> = {}): ClientCvRule {
  return {
    client_id: 1,
    client_name: "Nordea Bank Abp",
    filename_pattern: "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
    spaces_to_underscores: false,
    cv_language: "en",
    requires_en_copy: false,
    requires_rodo_consent_block: false,
    notes: null,
    generator_instructions: null,
    generator_instructions_en: null,
    content_mode: null,
    content_mode_locked: false,
    require_screening_notes_min_chars: null,
    require_project_ref: false,
    require_position: false,
    require_champion: false,
    auto_second_language: false,
    omit_sections: [],
    max_roles: null,
    max_bullets_per_role: null,
    max_bullet_chars: null,
    why_points_max: null,
    date_format: null,
    glossary: [],
    version: 1,
    cv_content_mode_cap: null,
    cv_interactive_enabled: true,
    seed_key: null,
    confirmed_at: "2026-08-31T10:00:00Z",
    confirmed_by_name: "Artur",
    is_active: true,
    client_policy: "nazwa pliku, język EN",
    filename_preview: "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ...overrides,
  };
}

export function makeCvRuleRow(
  overrides: Partial<ClientCvRuleListItem> = {},
): ClientCvRuleListItem {
  return {
    ...makeCvRule(),
    template_label: null,
    template_url: null,
    updated_at: "2026-08-31T10:00:00Z",
    ...overrides,
  };
}
