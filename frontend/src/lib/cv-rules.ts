/**
 * Reguły CV per klient — typy i wywołania API współdzielone przez edytor
 * (`components/cv-rules/*`), ekran `/settings/cv-rules`, baner w generatorze
 * i generator (blokady).
 *
 * Reguła to pełna recepta Delivery Leada (migracje 0255 → 0266 → 0267):
 * nazwa pliku i język → instrukcje dla modelu → blokady (tryb treści,
 * wymagane wejścia, druga wersja językowa), polityka prezentacji
 * egzekwowana w kodzie, słownik, wersja + historia + CV próbne.
 */

import api from "@/lib/api";
import type { CvContentMode } from "@/lib/cv-generator";

export type CvRuleLanguage = "pl" | "en";
export type CvRuleSectionKey =
  | "education"
  | "certifications"
  | "languages"
  | "skills";
export type CvRuleDateFormat = "MM.YYYY" | "MM/YYYY" | "YYYY-MM" | "YYYY";

export const CV_RULE_SECTIONS: ReadonlyArray<{
  value: CvRuleSectionKey;
  label: string;
}> = [
  { value: "education", label: "Wykształcenie" },
  { value: "certifications", label: "Certyfikaty" },
  { value: "languages", label: "Języki" },
  { value: "skills", label: "Umiejętności" },
];

export const CV_RULE_DATE_FORMATS: ReadonlyArray<{
  value: CvRuleDateFormat;
  label: string;
}> = [
  { value: "MM.YYYY", label: "MM.RRRR (03.2019)" },
  { value: "MM/YYYY", label: "MM/RRRR (03/2019)" },
  { value: "YYYY-MM", label: "RRRR-MM (2019-03)" },
  { value: "YYYY", label: "Same lata (2019)" },
];

export const GENERATOR_INSTRUCTIONS_MAX_LENGTH = 2000;

export interface GlossaryEntry {
  from: string;
  to: string;
}

/** Odpowiedź `GET /api/clients/{id}/cv-rule` (także dla klienta bez reguły). */
export interface ClientCvRule {
  client_id: number;
  client_name: string | null;
  filename_pattern: string | null;
  spaces_to_underscores: boolean;
  cv_language: CvRuleLanguage | null;
  requires_en_copy: boolean;
  requires_rodo_consent_block: boolean;
  notes: string | null;
  generator_instructions: string | null;
  generator_instructions_en: string | null;
  content_mode: CvContentMode | null;
  content_mode_locked: boolean;
  require_screening_notes_min_chars: number | null;
  require_project_ref: boolean;
  require_position: boolean;
  require_champion: boolean;
  auto_second_language: boolean;
  omit_sections: CvRuleSectionKey[];
  max_roles: number | null;
  max_bullets_per_role: number | null;
  max_bullet_chars: number | null;
  why_points_max: number | null;
  date_format: CvRuleDateFormat | null;
  glossary: GlossaryEntry[];
  version: number;
  cv_content_mode_cap: CvContentMode | null;
  cv_interactive_enabled: boolean;
  seed_key: string | null;
  confirmed_at: string | null;
  confirmed_by_name: string | null;
  is_active: boolean;
  /** `null` = brak wiersza; `""` = wiersz jest, ale nie obowiązuje. */
  client_policy: string | null;
  filename_preview: string | null;
}

export interface ClientCvRuleListItem extends ClientCvRule {
  template_label: string | null;
  template_url: string | null;
  updated_at: string | null;
}

export interface UnassignedTemplate {
  seed_key: string;
  label: string;
  template_url: string | null;
}

export interface CvRulesOverview {
  rules: ClientCvRuleListItem[];
  unassigned_templates: UnassignedTemplate[];
}

/** Payload `PUT /api/clients/{id}/cv-rule`. */
export interface ClientCvRulePayload {
  filename_pattern: string | null;
  spaces_to_underscores: boolean;
  cv_language: CvRuleLanguage | null;
  requires_en_copy: boolean;
  requires_rodo_consent_block: boolean;
  notes: string | null;
  generator_instructions: string | null;
  generator_instructions_en: string | null;
  content_mode: CvContentMode | null;
  content_mode_locked: boolean;
  require_screening_notes_min_chars: number | null;
  require_project_ref: boolean;
  require_position: boolean;
  require_champion: boolean;
  auto_second_language: boolean;
  omit_sections: CvRuleSectionKey[];
  max_roles: number | null;
  max_bullets_per_role: number | null;
  max_bullet_chars: number | null;
  why_points_max: number | null;
  date_format: CvRuleDateFormat | null;
  glossary: GlossaryEntry[];
  cv_content_mode_cap: CvContentMode | null;
  cv_interactive_enabled: boolean;
  confirm: boolean;
}

export interface RuleEvent {
  id: number;
  rule_version: number;
  action: string;
  changes: Record<string, { from: unknown; to: unknown } | unknown>;
  actor_name: string | null;
  created_at: string | null;
}

export interface RuleFeedback {
  days: number;
  generated_total: number;
  with_skipped_instructions: number;
  with_policy_enforced: number;
  skipped_by_instruction: Array<{ text: string; count: number }>;
  recent: Array<{
    id: number;
    candidate_name: string;
    language: string;
    content_mode: string;
    created_at: string | null;
    created_by_name: string | null;
    client_rule_version: number | null;
    skipped: string[];
    policy_enforced: boolean;
  }>;
}

export interface LintFinding {
  field: "generator_instructions" | "generator_instructions_en" | "notes";
  index: number;
  line: string;
  verdict: "ok" | "adds_facts" | "unclear";
  reason: string;
  suggestion: string;
}

export interface LintResponse {
  findings: LintFinding[];
  ok_count: number;
  adds_facts_count: number;
  unclear_count: number;
}

export interface PromptPreview {
  language: CvRuleLanguage;
  block: string;
  is_active: boolean;
}

export interface PreviewVariant {
  payload: Record<string, unknown> | null;
  warnings: string[];
  filename: string | null;
}

export interface RulePreview {
  id: number;
  client_id: number;
  candidate_id: number | null;
  stage_id: number | null;
  language: string;
  status: "processing" | "ready" | "failed";
  error_message: string | null;
  prompt_block: string | null;
  with_rule: PreviewVariant | null;
  without_rule: PreviewVariant | null;
  created_at: string | null;
}

export const cvRulesApi = {
  overview: async () =>
    (await api.get<CvRulesOverview>("/api/settings/cv-rules")).data,
  get: async (clientId: number) =>
    (await api.get<ClientCvRule>(`/api/clients/${clientId}/cv-rule`)).data,
  save: async (clientId: number, payload: ClientCvRulePayload) =>
    (await api.put<ClientCvRule>(`/api/clients/${clientId}/cv-rule`, payload))
      .data,
  confirm: async (clientId: number) =>
    (await api.post<ClientCvRule>(`/api/clients/${clientId}/cv-rule/confirm`))
      .data,
  remove: async (clientId: number) => {
    await api.delete(`/api/clients/${clientId}/cv-rule`);
  },
  copyFrom: async (clientId: number, sourceClientId: number) =>
    (
      await api.post<ClientCvRule>(
        `/api/clients/${clientId}/cv-rule/copy-from/${sourceClientId}`,
      )
    ).data,
  history: async (clientId: number) =>
    (await api.get<RuleEvent[]>(`/api/clients/${clientId}/cv-rule/history`))
      .data,
  feedback: async (clientId: number, days = 90) =>
    (
      await api.get<RuleFeedback>(`/api/clients/${clientId}/cv-rule/feedback`, {
        params: { days },
      })
    ).data,
  lint: async (
    clientId: number,
    body: {
      generator_instructions: string | null;
      generator_instructions_en: string | null;
      notes: string | null;
    },
  ) =>
    (
      await api.post<LintResponse>(`/api/clients/${clientId}/cv-rule/lint`, body, {
        timeout: 60_000,
      })
    ).data,
  promptPreview: async (clientId: number, language: CvRuleLanguage) =>
    (
      await api.get<PromptPreview>(
        `/api/clients/${clientId}/cv-rule/prompt-preview`,
        { params: { language } },
      )
    ).data,
  enqueuePreview: async (
    clientId: number,
    body: { candidate_id: number; stage_id: number; language: CvRuleLanguage },
  ) =>
    (await api.post<RulePreview>(`/api/clients/${clientId}/cv-rule/preview`, body))
      .data,
  getPreview: async (clientId: number, previewId: number) =>
    (
      await api.get<RulePreview>(
        `/api/clients/${clientId}/cv-rule/preview/${previewId}`,
      )
    ).data,
};

/** Czy odpowiedź opisuje ISTNIEJĄCY wiersz (także niezatwierdzony). */
export function hasStoredRule(rule: ClientCvRule | null | undefined): boolean {
  return !!rule && rule.client_policy !== null;
}

/** Formularz edytora — stringi zamiast `null`, żeby kontrolki były sterowane. */
export interface CvRuleForm {
  filename_pattern: string;
  spaces_to_underscores: boolean;
  cv_language: "" | CvRuleLanguage;
  requires_en_copy: boolean;
  requires_rodo_consent_block: boolean;
  notes: string;
  generator_instructions: string;
  generator_instructions_en: string;
  content_mode: "" | CvContentMode;
  content_mode_locked: boolean;
  require_screening_notes_min_chars: string;
  require_project_ref: boolean;
  require_position: boolean;
  require_champion: boolean;
  auto_second_language: boolean;
  omit_sections: CvRuleSectionKey[];
  max_roles: string;
  max_bullets_per_role: string;
  max_bullet_chars: string;
  why_points_max: string;
  date_format: "" | CvRuleDateFormat;
  glossary: GlossaryEntry[];
  cv_content_mode_cap: "" | CvContentMode;
  cv_interactive_enabled: boolean;
}

export function ruleToForm(rule: ClientCvRule): CvRuleForm {
  return {
    filename_pattern: rule.filename_pattern ?? "",
    spaces_to_underscores: rule.spaces_to_underscores,
    cv_language: rule.cv_language ?? "",
    requires_en_copy: rule.requires_en_copy,
    requires_rodo_consent_block: rule.requires_rodo_consent_block,
    notes: rule.notes ?? "",
    generator_instructions: rule.generator_instructions ?? "",
    generator_instructions_en: rule.generator_instructions_en ?? "",
    content_mode: rule.content_mode ?? "",
    content_mode_locked: rule.content_mode_locked,
    require_screening_notes_min_chars:
      rule.require_screening_notes_min_chars != null
        ? String(rule.require_screening_notes_min_chars)
        : "",
    require_project_ref: rule.require_project_ref,
    require_position: rule.require_position,
    require_champion: rule.require_champion,
    auto_second_language: rule.auto_second_language,
    omit_sections: [...(rule.omit_sections ?? [])],
    max_roles: rule.max_roles != null ? String(rule.max_roles) : "",
    max_bullets_per_role:
      rule.max_bullets_per_role != null ? String(rule.max_bullets_per_role) : "",
    max_bullet_chars:
      rule.max_bullet_chars != null ? String(rule.max_bullet_chars) : "",
    why_points_max: rule.why_points_max != null ? String(rule.why_points_max) : "",
    date_format: rule.date_format ?? "",
    glossary: (rule.glossary ?? []).map((g) => ({ from: g.from, to: g.to })),
    cv_content_mode_cap: rule.cv_content_mode_cap ?? "",
    cv_interactive_enabled: rule.cv_interactive_enabled,
  };
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formToPayload(form: CvRuleForm, confirm: boolean): ClientCvRulePayload {
  return {
    filename_pattern: form.filename_pattern.trim() || null,
    spaces_to_underscores: form.spaces_to_underscores,
    cv_language: form.cv_language || null,
    requires_en_copy: form.requires_en_copy,
    requires_rodo_consent_block: form.requires_rodo_consent_block,
    notes: form.notes.trim() || null,
    generator_instructions: form.generator_instructions.trim() || null,
    generator_instructions_en: form.generator_instructions_en.trim() || null,
    content_mode: form.content_mode || null,
    content_mode_locked: !!form.content_mode && form.content_mode_locked,
    require_screening_notes_min_chars: intOrNull(
      form.require_screening_notes_min_chars,
    ),
    require_project_ref: form.require_project_ref,
    require_position: form.require_position,
    require_champion: form.require_champion,
    auto_second_language: form.auto_second_language,
    omit_sections: [...form.omit_sections],
    max_roles: intOrNull(form.max_roles),
    max_bullets_per_role: intOrNull(form.max_bullets_per_role),
    max_bullet_chars: intOrNull(form.max_bullet_chars),
    why_points_max: intOrNull(form.why_points_max),
    date_format: form.date_format || null,
    glossary: form.glossary
      .map((g) => ({ from: g.from.trim(), to: g.to.trim() }))
      .filter((g) => g.from && g.to),
    cv_content_mode_cap: form.cv_content_mode_cap || null,
    cv_interactive_enabled: form.cv_interactive_enabled,
    confirm,
  };
}

/** Etykiety akcji historii — warstwa prezentacji, nie kontrakt API. */
export const RULE_EVENT_LABELS: Record<string, string> = {
  saved: "Zapisano jako propozycję",
  saved_and_confirmed: "Zapisano i zatwierdzono",
  confirmed: "Zatwierdzono",
  deleted: "Usunięto regułę",
  copied: "Skopiowano z innego klienta",
};

export const RULE_FIELD_LABELS: Record<string, string> = {
  filename_pattern: "Wzór nazwy pliku",
  spaces_to_underscores: "Podkreślenia zamiast spacji",
  cv_language: "Wymagany język",
  requires_en_copy: "Obie wersje językowe",
  requires_rodo_consent_block: "Zrzut zgody RODO",
  notes: "Notatka DL",
  generator_instructions: "Instrukcje dla generatora",
  generator_instructions_en: "Instrukcje dla generatora (EN)",
  content_mode: "Tryb obróbki treści",
  content_mode_locked: "Tryb zablokowany",
  require_screening_notes_min_chars: "Min. długość notatek",
  require_project_ref: "Wymagany numer projektu",
  require_position: "Wymagane stanowisko",
  require_champion: "Wymagany profil Championa",
  auto_second_language: "Druga wersja językowa automatycznie",
  omit_sections: "Pomijane sekcje",
  max_roles: "Maks. stanowisk",
  max_bullets_per_role: "Maks. punktów na stanowisko",
  max_bullet_chars: "Maks. znaków w punkcie",
  why_points_max: "Maks. punktów „dlaczego ten kandydat”",
  date_format: "Format dat",
  glossary: "Słownik",
  cv_content_mode_cap: "Sufit trybu treści",
  cv_interactive_enabled: "Interaktywne CV na linku",
  source_client_id: "Skopiowano z klienta",
};
