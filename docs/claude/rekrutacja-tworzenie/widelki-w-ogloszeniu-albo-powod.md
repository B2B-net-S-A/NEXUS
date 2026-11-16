# Ogłoszenie na portalu bez widełek wychodzi tylko z powodem
<!-- indeks: strażnik widełek (16.11.2026), Dz.U. 2025 poz. 807, `no_salary_reason` w `job_postings.options`, 422 `salary_reason_required`, tekst UoP vs B2B, `lib/postingSalaryGuard.ts` -->

Decyzja Artura z 15.11.2026 (radar „Przepisy”, sonda `postings_without_salary`).
Od 24.12.2025 (Dz.U. 2025 poz. 807) kandydat na umowę o pracę poznaje
wynagrodzenie albo widełki przed rozmową, a pracodawca nie pyta o jego obecne
wynagrodzenie. NEXUS nie blokuje ogłoszenia bez widełek, ale każda wysyłka bez
nich jest świadoma i ma zapisany powód — bo przy kontroli trzeba umieć
powiedzieć, dlaczego dane ogłoszenie wyszło bez kwot.

## Co działa

- Dotyczy publikacji przez API portalu, czyli wierszy `job_postings`:
  okno „Ogłoszenie” → „Opublikuj na JustJoin.IT” (`POST /portal-ad/jjit`,
  także aktualizacja), sekcja „Portale ogłoszeniowe” (`POST …/publish`,
  `PATCH …/options`) i krok portali na `/jobs/new`.
- Bez widełek front pyta przez `useConfirmV2().askReason` (nigdy natywne
  `confirm`) o „Powód publikacji bez widełek” (3–300 znaków). Pytanie pada przy
  każdej wysyłce bez widełek, także ponownej i przy zmianie ustawień; powód z
  poprzedniej wysyłki nie przechodzi po cichu. „Wróć i wpisz widełki” niczego
  nie wysyła.
- Powód leży w `job_postings.options.no_salary_reason` (bez migracji;
  `jjit_payload.normalize_options` czyści go, gdy widełki są). Do portalu nie
  idzie — `employment_types` czyta tylko `salary`.
- Serwer pilnuje tego sam: bez widełek i bez powodu `_checked_options` zwraca
  422 `salary_reason_required` po brakach w ustawieniach (`listing_invalid`
  ma pierwszeństwo). Worker i aktualizacja treści po zatwierdzeniu opisu
  (`queue_content_update`) nie pytają — to nie jest decyzja człowieka.

## Tekst zależy od formy umowy

- **Umowa o pracę:** „prawo wymaga” z datą i Dz.U.
- **B2B:** „zalecane” i „czy przepisy obejmują ogłoszenia B2B, sprawdzamy
  z prawnikiem”. Nie przesądzaj zakresu prawa dla B2B, dopóki Artur nie
  przekaże opinii prawnika — wtedy zmienia się tylko tekst
  (`salary_guard.missing_salary_message` i lustro `noSalaryDescription`).
- Formę bierze `salary_guard.contract_form(public_params(job)["contract"])`.
  Dziś każda rekrutacja to B2B (`bez-typow-rekrutacji.md`, portal dostaje
  `employmentTypes: b2b`), więc w praktyce pada tekst B2B; front ma stałą
  `NEXUS_AD_CONTRACT_FORM`. Ogłoszenie na UoP = podłącz formę w obu miejscach.

## Czego nie robić

- Nie wyliczaj widełek z budżetu rekrutacji ani stawki Championa, żeby
  ominąć pytanie (decyzja 25.09.2026 zostaje: widełki wpisuje człowiek).
- Nie dodawaj pytania o obecne wynagrodzenie do formularza aplikacji ani
  screeningu. Przegląd 16.11.2026: formularz kariery pyta o oczekiwaną
  stawkę (`expected_rate_hourly`, opcjonalnie), screening o „Stawkę
  kandydata” (`salary_expectation`); pytania o obecne zarobki nie było
  w kodzie ani w pytaniach do rozmów na kopii produkcji.
- Ogłoszenia wklejane ręcznie (Pracuj.pl mailem, „Oznacz jako opublikowane”)
  nie mają pola widełek w NEXUSIE; strażnik ich nie obejmuje.

Testy: `backend/tests/test_posting_salary_guard.py`,
`test_job_boards_queue.py` (oba przypadki 422 i zapis powodu),
`frontend/src/lib/__tests__/postingSalaryGuard.test.ts`, `JjitPublish.test.tsx`,
`JobPortalsSection.test.tsx`, `NewJobPage.test.tsx`.
