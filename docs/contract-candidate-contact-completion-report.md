# E-mail i telefon kandydata w widoku kontraktu — raport z wdrożenia

**Data:** 16.09.2026 · **Migracja:** `0320_contract_candidate_contact`

## Problem

E-mail i telefon wpisywane w „Danych Partnera" generatora umów B2B nie
docierały nigdzie poza `b2b_generated_contracts.render_payload` i treść DOCX-a.
Karta „Informacje o kontrakcie" nie pokazywała żadnego kontaktu do konsultanta,
więc Delivery, chcąc do kogoś napisać, wychodziło z kontraktu do profilu
kandydata.

## Rozwiązanie

Kontakt widoczny w jednym wierszu pod „Typ kontraktu", edytowalny w miejscu,
ze źródłami w kolejności **umowa z generatora → profil kandydata → puste**.

### Decyzje produktowe (Artur, 16.09.2026)

1. **Fallback jest ŻYWY, nie zamrożony.** Kolumny `contracts.candidate_email` /
   `candidate_phone` są NADPISANIEM — trzymają wartość tylko wtedy, gdy przyszła
   z generatora albo ktoś wpisał ją ręcznie. Pusto = odczyt bierze dane
   z profilu kandydata i oznacza je „z profilu". Dzięki temu poprawiony w profilu
   telefon jest na umowie widoczny od razu. Backfill kopiuje **wyłącznie poziom
   pierwszy**; materializacja profilu dałaby umowy z kontaktem starzejącym się
   w ciszy.
2. **Bez nowej powierzchni uprawnień.** Edycja stoi na istniejącym
   `PATCH /api/contracts/{id}` (`TacPlus`), a ołówek na froncie na istniejącym
   `canEditContract` — tym samym, który odsłania przycisk „Edytuj".

## Co powstało

| Warstwa | Plik |
|---|---|
| Schemat | `alembic/versions/0320_contract_candidate_contact.py` + lustro DDL w `entrypoint.sh`, `models/contract.py` |
| Reguła źródeł | `services/contract_candidate_contact.py` (czysty moduł, wspólny dla ekranu i raportu) |
| API | `schemas/contract.py` (`ContractUpdate`, `ContractDetailResponse` +6 pól), `api/contracts.py` (`_to_detail`, normalizacja w PATCH) |
| Zapis z generatora | `services/b2b_contract_automation.py::fill_candidate_contact` (podpis obustronny), `api/b2b_contract_generator.py` (`POST /render`) |
| RODO | `api/candidates.py` — twarde usunięcie kandydata zeruje obie kolumny |
| Backfill | `services/contract_candidate_contact_backfill.py` + blok w `entrypoint.sh` |
| Raport braków | `services/contract_candidate_contact_report.py`, `GET /api/contracts/candidate-contact-report` (Admin) |
| Front | `components/contracts/ContractCandidateContactRow.tsx`, `app/contracts/[id]/page.tsx` |
| Harness | `/preview/contract-candidate-contact` (publiczny, zero zapytań) |

### Reguły, które łatwo cofnąć

- **Wyczyszczenie pola przywraca fallback** — pusty string i jawny `null`
  w PATCH normalizują się do `NULL`.
- **Za długa wartość jest ODRZUCANA (422), nie przycinana** — ucięty numer
  telefonu wygląda na kompletny i nie da się go odróżnić od literówki.
- **Zapis z generatora jest FILL-ONLY** — ręczna poprawka Delivery wygrywa
  z dokumentem podpisanym wcześniej. `POST /render` stempluje umowę tylko wtedy,
  gdy para (kandydat, rekrutacja) ma DOKŁADNIE JEDEN nie-`void` kontrakt; przy
  zeru albo kilku pomija (fallback do profilu i tak pokrywa).
- **Backfill dopasowuje po `b2b_generated_contracts.contract_id`**, nigdy po
  kandydacie/rekrutacji — to byłoby zgadywanie, a wpisanie cudzego numeru jest
  gorsze niż jego brak.
- **Raport wypisuje braki liczone regułą ekranu**, nie zapytaniem o pustą
  kolumnę — inaczej wysyłałby zespół do przepisywania danych, które już widać.
- **`contract_merge` musi znać nowe kolumny** — scalanie duplikatów blokuje się
  na „nieklasyfikowanych kolumnach". Dopisane do `_MERGEABLE_FIELDS` jako
  dodatkowe (puste ← wypełnione), tak jak `client_pm_email`.

## Weryfikacja

- `pytest tests/test_contract_candidate_contact.py` — **13 passed**
  (kolejność źródeł, wyczyszczenie, PATCH częściowy, 422 na za długiej wartości,
  umowa bez kandydata, niezaładowana relacja bez lazy-loada, RODO).
- `pytest tests/test_contract_candidate_contact_backfill_0320.py` — **9 passed**
  (fill-only, idempotencja, brak materializacji profilu, kształt kluczy
  paragonu, 409 raportu przed korektą, zawartość arkusza).
- `pytest tests/test_b2b_signature_automation.py` — **41 passed** (w tym 2 nowe:
  podpis kopiuje kontakt, nie nadpisuje ręcznej poprawki).
- Przegląd regresji `-k "contract or b2b or erasure or rodo or section_ceiling
  or route_authz"` na czystej bazie — **1748 passed, 0 failed**; łańcuch
  migracji liniowy (`test_only_one_alembic_head` zielony po przenumerowaniu
  na `0320`, bo upstream zajął `0316`).
- Front: `tsc --noEmit` czysty, `next lint` czysty, `vitest` **583 passed**
  (w tym 8 nowych dla wiersza kontaktu i 119 dla middleware).
- Przeglądarka, harness `/preview/contract-candidate-contact`: cztery stany,
  edycja → odznaka znika, wyczyszczenie → wraca profil, brak w obu źródłach →
  „—", bez uprawnień → brak ołówka, 375 px bez poziomego przewijania.
- Przeglądarka, PRAWDZIWY ekran `/contracts/589` na żywym backendzie: wiersz
  pod „Typ kontraktu", zapis telefonu przez PATCH (odznaka znika, wartość
  w bazie), wyczyszczenie przywraca numer z profilu i odznakę.

## Znane, niezwiązane

`tests/test_contract_analytics_fx.py` ma dwa testy asertujące ABSOLUTNE sumy
zbiorcze. Przechodzą na świeżej bazie (8/8 z tym kodem), a padają na bazie,
w której nazbierały się dane innych plików — padają też uruchomione SAME, bez
żadnego kodu tego PR-a w przebiegu. To wcześniejsza słabość izolacji, którą CI
maskuje świeżą bazą per job; zgłoszone osobno.

## Znane ograniczenia (świadome)

- **`render_payload` starych dokumentów zostaje nietknięty** — kontakt
  w podpisanym dokumencie jest zapisem tego, co strony podpisały. Usunięcie
  kandydata zeruje kolumny na umowie, ale nie czyści `render_payload`; to stan
  sprzed tej zmiany i osobna decyzja.
- **Raport braków nie ma przycisku w interfejsie** — jak `order-sync-report`.
  Administrator pobiera go adresem.
- **`POST /generate`** (ścieżka szkicu umowy) nie niesie kontaktu w ogóle —
  `B2BGenerateRequest` nie ma pól Partnera. Pokrywa to fallback do profilu.
