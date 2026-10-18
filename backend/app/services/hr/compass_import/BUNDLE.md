# Paczka eksportu Compassa (`compass-bundle`, wersja 1)

Specyfikacja dla skryptu eksportu po stronie Compassa: które tabele i kolumny
czytają importery NEXUSA. Eksport to same `SELECT`-y (bez zapisu). Kolumn
spoza listy nie eksportujemy — paczka niesie dane osobowe, więc tylko to,
czego import potrzebuje.

```json
{
  "format": "compass-bundle",
  "version": 1,
  "exported_at": "2026-11-13T18:05:00+01:00",
  "tables": {"profiles": [{...}], "leave_requests": [{...}]}
}
```

- Wiersz = obiekt JSON z kolumnami jak w bazie Compassa (nazwy bez zmian).
- `uuid` jako tekst, `date` jako `RRRR-MM-DD`, `timestamptz` w ISO 8601
  ze strefą, `numeric` jako liczba albo tekst, `text[]` i `jsonb` jako tablice
  i obiekty JSON, `NULL` jako `null`.
- Brak tabeli w paczce = pusta tabela (moduł ma wtedy zero wierszy).
- Rozmiar do 64 MB. Plik leży poza repozytorium, z dostępem tylko dla osoby
  importującej, i jest kasowany po imporcie.
- Jedna paczka może zasilić wszystkie moduły. Kolejność importu:
  `profiles → leave → time → payroll → lifecycle → cases → care`
  (każdy moduł mapuje osoby przez kartoteki z `profiles`).

## Osoby (wszystkie moduły)

| Tabela | Kolumny |
|---|---|
| `profiles` | `id`, `email`, `role`, `is_external`, `employment_type`, `employment_status`, `default_location`, `hired_at`, `work_start_date`, `termination_date`, `can_log_overtime`, `job_title`, `department`, `phone`, `leave_entitlement_days`, `leave_carried_over_days`, `leave_used_initial_days`, `manager_id` |

Osoba Compassa (`profiles.id`) → konto NEXUSA przez mapę id kartotek, przez
`employee_profiles.compass_profile_id` albo przez e-mail z `profiles`.

## `leave` — urlopy

| Tabela | Kolumny |
|---|---|
| `leave_requests` | `id`, `user_id`, `leave_type`, `status`, `start_date`, `end_date`, `half_day`, `note`, `substitute_id`, `forward_mail_enabled`, `oof_internal_message`, `oof_external_message`, `paid_days`, `unpaid_days`, `decided_by`, `decided_at`, `decision_note`, `created_by`, `created_on_behalf`, `source`, `documentation_url` (tylko czy jest), `created_at` |

Pliki załączników (`documents/leave-proofs`) nie przechodzą.

## `time` — Mój miesiąc

| Tabela | Kolumny |
|---|---|
| `timesheets` | `id`, `user_id`, `year`, `month`, `status`, `submitted_at`, `approved_by`, `approved_at`, `rejection_note`, `pdf_hash`, `created_at` |
| `timesheet_entries` | `id`, `timesheet_id`, `work_date`, `hours`, `project`, `description`, `source`, `is_overtime_override`, `override_reason`, `override_by` |
| `attendance_records` | `id`, `user_id`, `date`, `status`, `location`, `note` |
| `timesheet_role_defaults` | `id`, `applies_to_role`, `label`, `project`, `default_description`, `is_active`, `sort_order`, `created_by` |
| `timesheet_user_templates` | `id`, `user_id`, `name`, `description`, `project`, `sort_order` |

`attendance_records` można eksportować w całości — import bierze tylko
wyjątki od domyślnego miejsca pracy, statusy urlopowe pomija.

## `payroll` — stawki i premie

| Tabela | Kolumny |
|---|---|
| `user_rates` | `id`, `user_id`, `hourly_rate`, `currency`, `effective_from`, `effective_to`, `reason`, `set_by` |
| `bonuses` | `id`, `recipient_user_id`, `proposed_by`, `amount`, `currency`, `category`, `status`, `period_year`, `period_month`, `period_quarter`, `place_rank`, `reason`, `created_at`, `cancelled_at`, `cancelled_by`, `cancellation_reason`, `client_name`, `sales_client_name`, `sales_service_description`, `delivery_candidate_name`, `delivery_margin_amount`, `delivery_margin_percent`, `recruiter_candidate_name`, `recruiter_margin_per_hour`, `recruiter_calculated_tier`, `custom_email_memo`, `notes` |

Załączniki premii (`bonus-attachments`) nie przechodzą.

## `lifecycle` — wejście i odejście

| Tabela | Kolumny |
|---|---|
| `exit_interviews` | `id`, `user_id`, `is_anonymous`, `manager_snapshot`, `exit_reason`, `status`, `reviewed_at`, `cancelled_at`, `cancelled_by`, `created_at`, `updated_at` |
| `exit_cases` (lustro, jeśli istnieje) | `id`, `person_type`, `person_id`, `is_anonymous`, `manager_snapshot`, `exit_reason`, `status`, `end_date`, `reviewed_at`, `cancelled_at`, `cancelled_by`, `created_by`, `created_at`, `updated_at` |
| `offboarding_tasks` | `id`, `user_id`, `category`, `title`, `responsible_role`, `due_date`, `completed_at`, `completed_by`, `notes`, `position` |
| `onboarding_progress` | `id`, `user_id`, `started_at`, `completed_at`, `cancelled_at`, `cancelled_by`, `created_at`, `updated_at` |
| `onboarding_cases` (lustro, jeśli istnieje) | `id`, `person_type`, `person_id`, `status`, `owner_id`, `start_date`, `started_at`, `completed_at`, `cancelled_at`, `cancelled_by`, `created_by`, `created_at`, `updated_at` |
| `onboarding_tasks` | `id`, `progress_id`, `title`, `category`, `responsible_role`, `due_date`, `completed_at`, `completed_by`, `notes`, `position` |

Lustra `exit_cases` / `onboarding_cases` mają te same id co tabele źródłowe
(migracja `20260825170000` usuwa je w repo, na produkcji mogą jeszcze stać) —
wystarczy jedna z par, przy obu wygrywa tabela źródłowa. NIE eksportujemy
`exit_reason_detail`, odpowiedzi ankiety (`nps_score`, `satisfaction_*`,
`what_*`, `knowledge_transfer_notes`) ani `contractor_form`: wolny tekst
powodu odejścia może nieść dane o zdrowiu, a sprawa odejścia w NEXUSIE trzyma
powód wyłącznie ze słownika.

## `cases` — skrzynka administracja@

| Tabela | Kolumny |
|---|---|
| `support_categories` | `id`, `slug` |
| `support_tickets` | `id`, `category_id`, `user_id`, `assignee_id`, `subject`, `body_md`, `status`, `priority`, `resolved_at`, `created_at`, `updated_at` — tylko kategorie `inbox_%` |
| `support_inbox_meta` | `ticket_id`, `priority_level`, `due_date`, `planned_due_date`, `follow_up_date`, `work_area`, `waiting_for`, `checklist`, `materials`, `consultant_id`, `consultant_name`, `consultant_phone`, `client_name`, `external_message_id`, `email_from`, `email_subject`, `email_received_at` |
| `support_ticket_comments` | `id`, `ticket_id`, `author_id`, `body_md`, `created_at` |
| `support_inbox_email_archive` | `ticket_id`, `email_body_text`, `email_body_html`, `external_conversation_id` |

Zamiast `support_categories` wiersz zgłoszenia może nieść `category_slug`.
Rozmów kontraktorów (`contractor_%`) i helpdesku nie eksportujemy.

## `care` — mapa technologiczna i rozmowy opiekunów

| Tabela | Kolumny |
|---|---|
| `clients` | `id`, `name` |
| `client_areas` | `id`, `client_id`, `name` |
| `vendors` | `id`, `name` |
| `technologies` | `id`, `name`, `aliases` |
| `contractors` | `id`, `full_name`, `nexus_candidate_id`, `nexus_contract_id`, `owner_tcm_id`, `current_client` |
| `contractor_success_settings` | `contractor_id`, `monitoring_status`, `check_in_cadence_days`, `onboarding_program_ends_on`, `onboarding_program_completed_at` |
| `tech_interview_cards` | `id`, `contractor_id`, `client_id`, `client_area_id`, `tcm_id`, `created_by`, `interview_date`, `status`, `is_draft`, `finalized_at`, `satisfaction`, `satisfaction_comment`, `hiring`, `hiring_source`, `hiring_roles`, `project_end_month`, `project_end_year`, `project_end_unknown`, `team_size`, `team_externals`, `memorable_quote`, `tech_old_new`, `vendors_note`, `title`, `professional_insurance`, `created_at` |
| `tech_interview_card_technologies` | `card_id`, `technology_id` |
| `tech_interview_card_vendors` | `card_id`, `vendor_id` |
| `tech_interview_card_initiatives` | `card_id`, `name`, `kind`, `priority` |
| `tech_card_sales_status` | `card_id`, `status`, `atlas_deal_title`, `reason`, `handled_by_name`, `handled_at` |
| `contractor_conversations` | `id`, `contractor_id`, `conversation_date`, `client_snapshot`, `category`, `status`, `note`, `follow_up_date`, `tcm_id`, `created_by`, `created_at` |

Z `contractors` import bierze kotwice NEXUSA i `full_name` (od 18.10.2026).
Kolejka „Tożsamość NEXUS” nie ma ani jednej kotwicy, więc karta bez kotwicy
łączy się z kontraktem po kliencie, imieniu i nazwisku konsultanta i dniu
rozmowy (decyzja Artura „Import + automatyczne parowanie”, reguły
w `app/services/care/card_linking.py`); niepewna czeka przy kliencie na
połączenie przez Delivery Leada, z nazwiskiem na karcie. Rozmowa przechodzi na
kontrakt tylko z kotwicą — bez niej zostaje w Compassie.

Rytm kontaktu i opiekun (etap 3, 17.10.2026): `contractor_success_settings`
daje poziom rytmu (wstrzymany; aktywny w programie wejścia → co 2 tygodnie do
`onboarding_program_ends_on`; inaczej `check_in_cadence_days` ≤ 14 / ≤ 31 /
≤ 93 → co 2 tygodnie / co miesiąc / co kwartał, dalej tylko kamienie;
monitoring nieaktywny → rytm domyślny NEXUSA), a `owner_tcm_id` — opiekuna
kontraktu. Oba tylko przy pewnym kontrakcie: kotwica osoby + klient
z `current_client` (nazwa jak `client_snapshot` rozmów) + dzień eksportu
(`exported_at`) w okresie umowy. Rytm albo opiekun ustawiony już w NEXUSIE
zostaje; reszta idzie do raportu importu.
