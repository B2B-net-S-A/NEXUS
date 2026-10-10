# PR2 (23.09.2026): multiposting, scalanie kandydatów, tagi, mail aplikacji, przepięcie kontraktu, anulowanie zamówień MD

Migracje `0364_application_confirmation`, `0365_order_group_cancel`,
`0366_job_portals` (lustra w `entrypoint.sh`, test `test_pr2_migration_mirror.py`).

- **Multiposting (Pracuj.pl, JustJoinIT) to szkielet za flagami OFF** (JustJoin.IT i RocketJobs mają od 0381 prawdziwy adapter — sekcja „Publikacja na RocketJobs i JustJoin.IT”; zaślepką zostaje Pracuj.pl)
  (`PORTAL_PRACUJ_ENABLED`, `PORTAL_JJIT_ENABLED` + `_API_URL`/`_API_KEY`) —
  brak dokumentacji API portali. `services/job_portals/` (adaptery
  `PendingDocumentationAdapter` mówią „czeka na dokumentację”, nigdy nie udają
  publikacji jak dawne `SIM-…`), kolejka w `job_postings` (`publishing` →
  worker `tasks/job_portal_worker.py` z `SKIP LOCKED` → `published`/`failed`
  z polskim `last_error`), częściowy UNIQUE jednej żywej publikacji na portal.
  Treść WYŁĄCZNIE z zatwierdzonego opisu publicznego (`public_job_payload`),
  link aplikacji = link rekrutacji na stronie kariery; bez nich 409. Worker
  kończy się przed pętlą przy obu flagach OFF; `checks.job_portals`
  informacyjne (`unconfigured` dziś). Sekcja „Portale ogłoszeniowe” w oknie
  zlecenia renderuje się tylko przy `GET /api/job-portals/config` → `any_ready`.
  Harness `/preview/job-portals`.
- **Scalanie duplikatów kandydatów** (`services/candidate_merge.py`,
  `GET …/{id}/merge-preview?other=`, `POST …/{id}/merge`, admin + HoR,
  „Scal z…” w menu profilu, harness `/preview/candidate-merge`). Referencje
  z KATALOGU w chwili uruchomienia (FK do `candidates.id` o dowolnej nazwie
  kolumny + kolumny `candidate_id` bez FK + FK z modeli); konflikt unikalności
  rozstrzygany PER WIERSZ (para z tym samym kluczem → zostaje nowszy wiersz,
  starszy znika, reszta przepięta — nigdy „usuń wszystkie wiersze
  duplikatu”); `activities`/`notifications`(+link)/`traffit_entity_links`
  przepinane jawnie. Konflikt pól = wybór człowieka; kontakt duplikatu
  zostaje w `custom_fields.merged_duplicates`. Duplikat z Traffita oddaje
  ocalałemu `external_id` (inaczej nocny sync go odtworzy); oba z tego samego
  systemu = 409 `both_external`. Odcisk jak w `contract_merge`. Historia
  zdarzeń `candidate.merge` bez nazwisk. Skrypt
  `scripts/merge_duplicate_candidates.py` ZOSTAJE (partie Talent Radar,
  własne testy) — do scalania pojedynczych par używaj UI.
- **Tagi kandydata:** `POST/DELETE /api/candidates/{id}/tags` zmienia JEDEN
  tag pod blokadą wiersza (obiekty importu Traffita nietknięte, tag
  porównywany bez wielkości liter), `GET /api/candidates/tags/suggest`
  (kształt jak `/companies/suggest`). Nie wracaj do zapisu całej listy
  z przeglądarki — PATCH zastępuje listę i kasował cudze tagi. Filtr „Tagi”
  w „Więcej filtrów” → „Inne” (URL `tags`, cały tag).
- **Mail potwierdzenia aplikacji** (`services/application_confirmation_email.py`,
  rodzaj `application_confirmation` w `notification_delivery.CATALOG`,
  domyślnie OFF): wołany IDENTYCZNIE z obu gałęzi `submit_application`
  (nowy e-mail / już w bazie) i budowany wyłącznie z formularza i linku —
  treść nie może zdradzić, że osoba była w bazie. Tytuł tylko z
  ZATWIERDZONEGO opisu publicznego. Dedup (HMAC adresu, klucz linku) 24 h
  w `application_confirmation_sends`; nieudana wysyłka zwalnia rezerwację.
- **Przepięcie kontraktu na innego klienta** (admin;
  `GET /api/contracts/{id}/client-reassign-preview?client_id=`, `POST …/client-reassign`,
  akcja w szczegółach kontraktu): przenosi `contracts.client_id`, zamówienia,
  wygenerowane umowy B2B (nazwa WYDRUKOWANA zostaje), otwarte braki; otwarte
  alerty DL starego klienta zamyka jako `resolved`. **409 z listą** przy
  zamówieniu pod umową ramową/wykonawczą, linii zamówienia MD/kosztowego,
  PM-ie z innej firmy, czekającej decyzji offboardingu. `ContractUpdate` nadal
  NIE ma `client_id` — to jedyna droga. Historia zdarzeń bez nazwisk (same
  kody blokerów).
- **Anulowanie zamówienia MD/kosztowego z przywróceniem**
  (`POST …/order-groups/{id}/cancel` i `…/restore`, cykl życia zamówienia):
  tylko BEZ rozliczeń (ta sama reguła co usunięcie, 409 z listą); grupa
  `cancelled` pamięta `status_before_cancel`, linie `cancelled`, statusy linii
  w payloadzie `order_cancelled` — „Przywróć anulowane” je odtwarza (osoba,
  której okres minął, wraca jako zakończona). Anulowane zamówienie jest tylko
  do odczytu (PATCH, zakończenie, przedłużenie, linie, rozliczenia → 409),
  a zwykłe „Przywróć” (reopen) go nie rusza. Filtry automatów pytają
  pozytywnie o `active`/`exhausted`/`completed`, więc anulowane samo z nich
  wypada — nowy filtr pisz tak samo, nie jako „≠ completed”.
