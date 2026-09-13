# P1 — Przepływ: od kandydata z CV do werdyktu hiring managera

| Pole | Wartość |
|---|---|
| Tryb | **W** (zapis) — konto admina, NIE w podglądzie; `wyniki/LOCK` obowiązkowy |
| Moduły | M01 → M03 → M04 → M05 → M12 |
| MUST | **tak** (przepływ dnia pierwszego dla rekrutera) |
| Zależności | Fala 1 zakończona; Fala 0 (D1, D3+D10, D12, D5–D9) |
| Czas | ~2,5 h |
| Akcje AI | 1 generacja CV (z limitu), 1 opis dopasowania |
| CZŁOWIEK | krok 12 (weto HM — jeśli wymaga maila), krok 15 (ewentualne odrzucenie z mailem — POMIJAMY) |

## Cel

Rekruter dostaje CV → zakłada kandydata → notuje rozmowę → dodaje do rekrutacji → przesuwa
po etapach → generuje CV dla klienta → przekazuje je linkiem → hiring manager wydaje werdykt.
Sprawdzamy, że każdy krok zostawia ślad tam, gdzie kolejny krok go czyta.

## Dane

- Nowy kandydat z `cv-02-jan-probny.docx` (Jan Próbny) — zakładany TU, nie D6 (D6 zostaje nietknięty do porównań).
- Rekrutacja D3 u D1, Champion D10, reguła CV D12.
- Persona recruiter w zespole D3 (do weryfikacji widoczności — w podglądzie, między krokami).

## Kroki

| # | Akcja (admin) | Weryfikacja | Co zapisać |
|---|---|---|---|
| 1 | `/candidates` → „Dodaj z CV” → `cv-02-jan-probny.docx` | kandydat utworzony; imię/nazwisko/e-mail/telefon z CV; skille `Spark, SQL, Airflow`; kategoria kompetencji nadana automatycznie (`data_ai` lub `software_development`); daty `03.2020 – 06.2023` | `candidate_id` → `utworzone.json` |
| 2 | ten sam plik jeszcze raz → „Dodaj z CV” | dedup: komunikat o duplikacie (po e-mailu/telefonie) — brak drugiego kandydata; jeśli powstał drugi → **P1** i zapisz oba ID | — |
| 3 | profil → Aktywność → „Dodaj notatkę”: tekst z @wzmianką persony recruiter: „Rozmowa wstępna OK, @{{recruiter}} proszę o kontakt. Stawka oczekiwana 130 zł/h.” → Zapisz | notatka na osi czasu z renderowaną wzmianką; `Activity` utworzone; w podglądzie recruiter: powiadomienie o wzmiance w dzwonku | `note_id` |
| 4 | profil → edytuj „Oczekiwana stawka” = 130 PLN/h, dostępność = 1 mies. → Zapisz | wartości zapisane; lista `/candidates` kolumna „Stawka” = 130; filtr dostępności „1 mies.” zawiera kandydata | — |
| 5 | `/jobs/{{D3}}` → „Dodaj kandydata” → wybierz kandydata z kroku 1 (źródło `quick_add`) | karta na pierwszym etapie kanbanu; nagłówek rekrutacji +1; `/candidates` kolumna „Rekrutacje” pokazuje D3; telemetria: `match_outcomes.reason_code = quick_add` (sprawdź w `GET …/pipeline/{{D3}}/…` lub zapisz jako „nie do sprawdzenia z UI”) | `stage_id` |
| 6 | dock kandydata → „Dopasowanie” | pierścień z liczbą (must D3: Python/PostgreSQL/Docker vs skille Spark/SQL → NISKIE dopasowanie, nie „—”); opis AI bez liczby punktów | wartość |
| 7 | dock → „Screening” → odpowiedz na 2 pytania z Championa → Zapisz | odpowiedzi zapisane; widoczne po F5; w generatorze CV (krok 10) trafiają do źródeł („odpowiedzi screeningowe”) | — |
| 8 | przesuń kartę: etap 1 → „Weryfikacja” → „CV Wysłane” **(zatrzymaj się PRZED „CV Wysłane” — patrz krok 11)**; najpierw tylko → Weryfikacja | ruch zapisany; historia etapu w docku „W procesie”; kanban D3 zaktualizowany bez F5 (oba klucze cache) | — |
| 9 | przesuń kandydata Z POWROTEM o etap (jeśli szablon dopuszcza) | ruch wstecz zapisany; historia ma oba ruchy; Insights → Placementy NIE liczy niczego (brak `hired`) | — |
| 10 | `/cv-generator` → z bazy → kandydat z kroku 1 → rekrutacja D3 → `tailored` → Generuj (**generacja 1 z P1**) | dokument; rola „Senior Backend Developer”; w źródłach: CV + notatka z kroku 3 + odpowiedzi z kroku 7; stawka 130 **NIE** występuje w dokumencie (P0, jeśli występuje) | `cv_document_id` |
| 11 | `/jobs/{{D3}}` → dock kandydata → „Przekazanie CV” → wybierz CV z kroku 10 → „Przekaż klientowi” | KOLEJNOŚĆ: ruch na „CV Wysłane” → link → (stawka). Karta na „CV Wysłane”; zakładka „Linki i historia” ma 1 link (`OneTimeLinkField`); link celuje w etap SPRZED ruchu; toast „skopiowano” tylko po udanym kopiowaniu | `share_token` (prefiks) |
| 12 | incognito: otwórz link z kroku 11 | CV widoczne (classic); brak stawek/notatek; **link nie idzie do nikogo** | zrzut |
| 13 | dock decyzji → „Decyzja” → werdykt HM: „Zaprosić na rozmowę”, komentarz `[QA-E2E] werdykt` → Zapisz | wiersz werdyktu z `author = admin`, `can_edit = true`; w podglądzie recruiter (w zespole): widzi werdykt, formularz `can_record` zgodny z regułą; finance (spoza zespołu): tylko odczyt | `feedback_id` |
| 14 | podgląd DL → ten sam werdykt → „Edytuj” (**bez zapisu**, 403 w podglądzie) | przycisk widoczny dla DL (DL nadpisuje cudzy werdykt) | — |
| 15 | admin: przesuń na „Interview Klient” → dock „Rozmowy” → wynik „Dalej” | etap zapisany; **NIE klikaj „Zaproś na rozmowę” (kalendarz → mail)**; **NIE odrzucaj z mailem** | — |
| 16 | kandydat → profil → Aktywność | oś czasu ma: utworzenie, notatkę, dodanie do D3, 4 ruchy, CV wygenerowane, link utworzony, werdykt — w kolejności czasowej, po polsku | zrzut |
| 17 | `/jobs/{{D3}}` → dock „Historia” | te same zdarzenia od strony rekrutacji | — |
| 18 | odwołaj link z kroku 11 → incognito F5 | wygasł (404/410) | — |
| 19 | `/candidates` → filtr rekrutacja D3 + etap „Interview Klient” | kandydat na liście; kolumna „Przeniósł na etap” = admin | — |

## Weryfikacja końcowa (API)

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const c = await fetch('https://api.nexus.dynaminds.pl/api/candidates/{{candidate_id}}',{headers:h}).then(r=>r.json());
console.log(c.expected_hourly_rate, c.competence_category, c.stages?.map(s=>[s.job_id,s.stage]));
const acts = await fetch('https://api.nexus.dynaminds.pl/api/activities?candidate_id={{candidate_id}}&limit=50',{headers:h}).then(r=>r.json());
console.table((acts.items??acts).map(a=>({t:a.created_at,type:a.action})));
```

## Sprzątanie (na końcu P1 — kandydat zostaje do P2!)

Kandydat z kroku 1 JEST potrzebny w P2 (zatrudnienie). NIE usuwaj. Odwołaj link (krok 18).
Zapisz wszystko w `utworzone.json` z `cleaned:false`. Sprzątanie całości — po P4.

## Kryteria PASS przepływu

Wszystkie kroki 1–19 PASS; brak P0/P1. Jeśli krok 2 (dedup) FAIL — przepływ nadal może iść dalej
(zapisz drugi ID do sprzątania), ale P1 blokuje start produkcyjny.
