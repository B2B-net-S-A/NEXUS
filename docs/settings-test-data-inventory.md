# Ślady testów w Ustawieniach — inwentarz produkcji (20.10.2026)

Odczyt produkcji wyłącznie w trybie `SET default_transaction_read_only = on`
(psql w kontenerze Postgresa przez SSH). Nic nie zostało zmienione ani usunięte.
Usuwanie dopiero po zgodzie Artura na konkretną listę, osobnym krokiem.

Konta osób opisane rolą i id — repo i logi Actions są publiczne.

## Jak szukano

1. Tabele konfiguracyjne Ustawień: `clients`, `client_cv_rules`, `client_playbooks`,
   `pipeline_templates`, `pipeline_stage_defs`, `rejection_reasons`,
   `contract_templates`, `email_templates`, `user_email_templates`, `dictionaries`,
   `dictionary_items`, `entity_field_defs` (pusta), `rate_benchmarks`,
   `required_document_templates`, `lifecycle_templates`, `hr_agreement_templates`,
   `equipment_protocol_templates`, `timesheet_templates`, `competence_categories`,
   `role_profiles`, `skills`, `teams_notification_channels`, `service_accounts`,
   `service_account_keys`, `oauth_clients`, `dr_api_keys`, `users`.
2. Dwa przebiegi wyrażeń regularnych po nazwach, opisach i e-mailach:
   `smoke|e2e|zzz|claude|test…|testow…|dummy|fake|lorem|[qa|qa-test|playwright|pytest|codex|próbn…|sandbox`
   oraz `acme|foo|asdf|qwer|xxx|example|tmp|temp|nie rusza|audyt|[|demo|alpha|beta|RRRR-MM-DD`.
3. Dla każdego trafienia: wszystkie klucze obce wskazujące na wiersz
   (`information_schema` + `\gexec`, liczone tylko niezerowe) i reguła `ON DELETE`.

Trafienia odrzucone jako prawdziwe dane: profile ról o testerach (`role_profiles`
2, 8, 23, 34, 70, 71, 6303, 21723), umiejętności `Playwright`, `pytest`,
`Manual/Performance/Penetration Testing`, `Test Automation` (`skills` 170–200),
konta serwisowe `compass-integration` i `automatyzacje-rozliczenia`.

## Znalezione wiersze

| # | Tabela · id | Nazwa | Utworzono | Kto | Gdzie widać w Ustawieniach |
|---|---|---|---|---|---|
| 1 | `clients` 64636 | [QA-E2E-2026-09-13] Klient Testowy | 2026-09-13 | brak kolumny autora | Reguły CV klientów, przypisania Delivery Leada, portfele |
| 2 | `clients` 64637 | [QA-E2E-2026-09-13] Klient Wieloosobowy | 2026-09-13 | brak kolumny autora | portfele |
| 3 | `clients` 77196 | klient z audytu UI z datą 2026-09-26 w nazwie | 2026-09-26 | — | — (decyzja z PR #2421: zostaje) |
| 4 | `pipeline_templates` 73 | ZZZ-claude-reorder-smoke-1780661184 | 2026-06-05 | konto 9 (admin, nieaktywne) | Procesy rekrutacyjne z „pokaż zarchiwizowane”, powody odrzucenia |
| 5 | `contract_templates` 1 | Umowa B2B — szablon domyślny (smoke test) | 2026-04-23 | konto 9 | Wzory umów (wybór wzoru w szkicu umowy) |
| 6 | `service_accounts` 1 + klucz | `claude-traffit-ops` (klucz „claude-session”) | 2026-08-11 | konto 82 (admin) | Konta serwisowe |
| 7 | `users` 9, 10, 13, 19 | konta z „test/smoke” w e-mailu lub nazwie | 2026-04-22 … 2026-05-05 | — | tylko z filtrem nieaktywnych |

### 1–2. Klienci QA-E2E (64636, 64637)

Powiązania (liczba wierszy, reguła usuwania):

| Tabela | 64636 | 64637 | ON DELETE |
|---|---|---|---|
| `jobs` | 4 (603652, 680768, 680769, 693761 — wszystkie `closed`) | 1 (603653, `closed`) | NO ACTION |
| `recruitment_processes` | 581 | 36 | SET NULL |
| `calendar_events` | 2 | 0 | NO ACTION |
| `candidate_search_runs` | 1 | 0 | NO ACTION |
| `cv_generated_documents` | 5 | 1 | SET NULL |
| `client_interview_slot_requests` | 2 | 0 | SET NULL |
| `client_cv_rules` | 1 (id 965) | 0 | CASCADE |
| `client_cv_rule_events` / `_publications` | 1 / 1 | 0 | CASCADE |
| `client_playbooks` / `client_playbook_events` | 1 (id 644) / 1 | 0 | CASCADE |
| `delivery_lead_client_assignments` | 1 (id 37, DL konto 30) | 0 | CASCADE |
| `client_portfolio_scopes` | 1 (id 172) | 1 (id 173) | CASCADE |
| `interview_questions` | 1 | 0 | CASCADE |

**Klienta nie da się usunąć bez skutków ubocznych.** Na jego rekrutacjach siedzą
prawdziwi kandydaci: rekrutacja 603652 ma 481 wierszy `candidate_stages`, z czego
479 w kolumnie „Ogłoszenia” (`posting`) dodało konto 244 (rola TCM) między 16 a
23.09.2026; 381 tych osób ma też inne rekrutacje. 480 procesów
(`recruitment_processes`) na tym kliencie ma status `open` mimo zamkniętych
rekrutacji. Usunięcie klienta wymagałoby najpierw usunięcia rekrutacji i kart
prawdziwych kandydatów.

**Co da się usunąć bez skutków ubocznych** — wiersze konfiguracyjne, które
wstawiają klienta 64636/64637 do list Ustawień (żaden nie ma powiązań FK):
`client_cv_rules` 965, `client_cv_rule_events` i `client_cv_rule_publications`
klienta 64636 (po 1), `client_playbooks` 644 i jego zdarzenie (1),
`delivery_lead_client_assignments` 37, `client_portfolio_scopes` 172 i 173.
Lista `/settings/cv-rules` (`client_cv_rules.py:1399`) łączy reguły z klientami
bez filtra statusu, więc to usunięcie reguły zdejmuje klienta z tej listy.
Sam klient (status `inactive`) i jego rekrutacje zostają jako ślad audytu.

### 3. Klient z audytu UI (77196)

7 rekrutacji, 3 kontrakty, karta klienta, portfel. Sprzątanie kontraktów i osób
testowych tego klienta idzie PR-em #2421 (zgoda Artura 20.10); klient i rekrutacje
zostają z decyzji z tamtego PR-a. Poza zakresem tego inwentarza.

### 4. Szablon procesu `ZZZ-claude-reorder-smoke-…` (73)

`archived = true`, `is_default = false`, 0 rekrutacji (`jobs.pipeline_template_id`).
Ma 4 etapy (749 „Alpha”, 750 „Beta”, 751 „Zweryfikowany”, 10764 „Ogłoszenia”),
każdy z 0 użyć w `candidate_stages` i bez innych powiązań FK, oraz 3 powody
odrzucenia (1004 i 1005 `work_mode_mismatch` aktywne, 19 `legacy_unknown`
nieaktywny — zaślepka importu sadzona per szablon), 0 użyć w
`candidate_stages.rejection_reason_id`. Etapy i powody idą `ON DELETE CASCADE`.
**Usuwalny bez skutków ubocznych.** Audyt powodów odrzucenia
(`docs/settings-rejection-reasons-audit.md`) liczył 2 powody — trzeci jest
nieaktywny.

### 5. Wzór umowy „(smoke test)” (1)

Treść 1 680 znaków (wzory 2 i 3 mają po ok. 37–38 tys.), od 20.10 nie jest
domyślny. Wskazuje na niego `contracts.draft_template_id` w 5 kontraktach
(15, 49 — `ended`; 21, 643, 668 — `active`); reguła `ON DELETE SET NULL`.
Treść szkicu tych umów leży w `contracts.draft_content_html` i zostaje;
po usunięciu wzoru w szkicu znika tylko informacja „z jakiego wzoru”
(`contracts.py:4851`). Wcześniej warto sprawdzić, czy szkice tych trzech
aktywnych kontraktów nie powstały z tego krótkiego wzoru.
**Usuwalny z małym skutkiem** (utrata wskazania wzoru w 5 kontraktach).

### 6. Konto serwisowe `claude-traffit-ops` (1)

Aktywne, 1 nieodwołany klucz, ostatnie użycie 2026-08-14. Sync Traffita jest
wyłączony na stałe od 14.10.2026 (`traffit_retired.py`, 410), więc konto nie ma
już pracy. To nie dane testowe, tylko nieużywany dostęp — właściwy krok to
odwołanie klucza i dezaktywacja konta (zostaje w historii), nie usunięcie.

### 7. Konta użytkowników 9, 10, 13, 19

Wszystkie `is_active = false`. Konto 9 (admin, ostatnio widziane 2026-06-11) ma
tysiące powiązań: 3 374 wydarzenia kalendarza, 1 684 powiadomienia, 183 wpisy
aktywności, 172 e-maile, 12 ruchów kart, autor szablonów 1 i 73. Konta 10, 13,
19 mają tylko wpis w `role_session_migration_audit` (13 także 16 w
`kpi_nudge_log`). Usuwanie kont przepisuje historię — **zostawić**; nieaktywne
konta nie trafiają do wyborów osób (`users.py:140`).

## Propozycja listy do usunięcia

| Pozycja | Wiersze | Skutek |
|---|---|---|
| A. Klient QA-E2E znika z Ustawień | `client_cv_rules` 965 + zdarzenie i publikacja reguły; `client_playbooks` 644 + zdarzenie; `delivery_lead_client_assignments` 37; `client_portfolio_scopes` 172, 173 | brak — klient, rekrutacje i kandydaci zostają |
| B. Szablon procesu 73 | `pipeline_templates` 73 (kaskadowo 4 etapy, 3 powody) | brak — 0 użyć |
| C. Wzór umowy 1 | `contract_templates` 1 | 5 kontraktów traci wskazanie wzoru (treść zostaje) |
| D. Konto serwisowe 1 | odwołanie klucza + `is_active = false` (bez usuwania) | Traffit wyłączony, brak użytkownika |

Wykonanie: faza startu z paragonem w `app_settings` (wzór jak PR #2421),
każdy `DELETE` z warunkiem na id i oczekiwaną liczbę wierszy.
