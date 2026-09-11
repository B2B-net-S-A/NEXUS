# M08 — Kontrakty, kontraktorzy i Generator Umów B2B

| Pole | Wartość |
|---|---|
| Tryb | **R** — generowanie dokumentu umowy B2B dla osoby TESTOWEJ jest dozwolone (tworzy wiersz i numer umowy; sprzątanie przez DELETE zwalnia numer); potwierdzenie podpisu → P2 |
| Persony | delivery_lead (D1), finance, talent_community_manager, head_of_recruitment, recruiter (podgląd); admin |
| Zależności | Fala 0; najlepiej po P2 (kontrakt D5 u D1 istnieje) |
| Czas | ~3 h |
| Głębokość | pełna — pieniądze i dokumenty prawne |
| Akcje AI | nie |

## Zakres

- `/contracts` — rejestr kontraktów: domyślny filtr **Aktywne + Kończące się**, `status=all`,
  licznik „N kontraktorów / M aktywnych kontraktów”, eksport Excel, analityka (`/contracts/analytics`).
- `/contracts/[id]` — szczegóły: stawki (harmonogramy: kandydata, klienta, ramowa), okres,
  „Koniec zamówienia u klienta” (`client_order_*`), aneksy, wypowiedzenie, status, powiązane zamówienia.
- `/contracts/new` — nowy kontrakt (formularz; walidacja aktywacji: `start_date`, obie stawki, `contract_type`; **bez `end_date`**).
- `/contractors` — Kontraktorzy (lista osób, filtr statusu, „Brak aktywnego zamówienia”).
- `/contracts/b2b-generator` — Generator Umów B2B: 3 zakładki **„Umowy aktywne i w trakcie podpisu” · „Umowy bez projektu” · „Zakończone umowy”**, generowanie DOCX z szablonu, rejestr, wyszukiwanie, historia statusów, „Potwierdź podpis” (**STOP**).
- `/settings/contract-templates` — szablony (odczyt; M11).
- `/sign/[token]` — publiczny podpis (M12).

## Przed startem

ID D1, D5; po P2 — ID kontraktu D5@D1 i ID umowy B2B z P2. Jeden PRAWDZIWY kontrakt aktywny
z harmonogramem stawek (≥ 2 kroki) i jeden `ending` (tylko ID) — do S06–S08.

## NIE KLIKAJ

„Potwierdź podpis” / „Potwierdź obustronny podpis”, „Wypowiedz”, „Zakończ”, „Aneks” → Zapisz,
„Usuń kontrakt”, „Usuń umowę” (poza WŁASNĄ testową z S20), „Wyślij do podpisu” (Autenti/QES → mail),
„Zmień status” na prawdziwej umowie, „Zawieś”/„Przywróć” na prawdziwej umowie.

## Scenariusze — rejestr `/contracts`

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | delivery_lead | `/contracts` bez parametrów | filtr = Aktywne + Kończące się; licznik „N kontraktorów / M aktywnych kontraktów” liczy CAŁY zbiór obowiązujących | P1 |
| S02 | delivery_lead | filtr pojedynczy: Aktywne / Kończące się / Zakończone / Szkic; `status=all` | wyniki i licznik zmieniają się; URL niesie filtr | P2 |
| S03 | delivery_lead | wyszukaj „Testowa” | kontrakt D5 (po P2) | P1 |
| S04 | finance | kolumny stawek | widoczne (view_finance) | P1 |
| S05 | head_of_recruitment / tac / tcm | kolumny stawek | „—” | P1 |
| S06 | admin | prawdziwy kontrakt z ≥ 2 krokami harmonogramu → szczegóły | stawka „obecna” = krok obowiązujący dziś; przyszły krok pokazany jako zaplanowany z datą | P1 |
| S07 | admin | prawdziwy kontrakt `ending` | data końca w przyszłości (≤ 30 dni); status „Kończący się”; w rejestrze domyślnym OBECNY | P1 |
| S08 | admin | eksport Excel rejestru | plik; kolumny zgodne z widocznymi; kwoty tylko dla ról z finansami (sprawdź eksport w podglądzie HoR → brak kolumn kwot albo 403) | P1 |
| S09 | admin | `/contracts/analytics` | wykresy ładują się; brak `NaN`; okres zmienia liczby | P2 |
| S10 | recruiter | `/contracts` ręcznie | odmowa | P1 |

## Scenariusze — szczegóły kontraktu D5@D1 (po P2)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S11 | delivery_lead (D1) | `/contracts/{{ID}}` | status Aktywny; start = start umowy; `end_date` PUSTA (bezterminowa); stawka kosztowa z umowy (godzinowa); stawka przychodowa i „Koniec zamówienia u klienta” z zamówienia (po P3) | P1 |
| S12 | delivery_lead (D1) | sekcja harmonogramów | krok `client_rate_schedule` z `source_order_id` (z zamówienia) oznaczony inaczej niż krok ręczny | P2 |
| S13 | delivery_lead (D1) | formularz PATCH — podgląd walidacji „Kończący się” bez daty końca (**nie zapisuj**; w podglądzie 403) | frontendowe lustro: komunikat „Kończący się wymaga daty końca” | P2 |
| S14 | delivery_lead (D1) | powiązane zamówienia | lista z P3; link do klienta `?tab=zamowienia` | P2 |
| S15 | finance | `/contracts/{{ID}}` | odczyt kwot; przycisk aneksu/wypowiedzenia — sprawdź obecność i zapisz (zapis finansowy wymaga `manage_finance`) | P2 |

## Scenariusze — `/contracts/new` (formularz bez zapisu)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S16 | admin | wypełnij: kandydat D6, klient D1, start dziś, obie stawki, typ; `end_date` PUSTE → status „Aktywny” → walidacja frontu | brak błędu o `end_date` (bezterminowa jest legalna); komunikaty PL z `CONTRACT_FIELD_LABELS`; **Anuluj** | P1 |
| S17 | admin | jw. bez stawki przychodowej → „Aktywny” | błąd „brakuje: stawka klienta” (nazwa pola PL) | P2 |

## Scenariusze — `/contractors`

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S18 | delivery_lead | `/contractors` | lista osób; D5 (po P2); dopisek „Brak aktywnego zamówienia” dla osób bez zamówienia obejmującego dziś; filtr statusu | P1 |
| S19 | head_of_recruitment | `/contractors` | nazwiska tak, kwoty „—” | P1 |

## Scenariusze — Generator Umów B2B

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S20 | admin | `/contracts/b2b-generator` → „Generuj” → kandydat D5, klient D1, rekrutacja D3, stawka 120 PLN/h, start 01.10.2026 → Generuj | DOCX; wiersz w zakładce 1 ze statusem podpisu „w trakcie”; numer umowy nadany; klauzula stawki liczbowo i słownie; nazwa klienta z D1; **numer i ID zapisz — sprzątanie w P2 lub DELETE na końcu karty** | P1 |
| S21 | admin | pobierz DOCX z S20 | otwiera się; brak `{{placeholder}}`; stawka jako liczba całkowita (zaokrąglenie wg reguły generatora) | P1 |
| S22 | admin | rejestr: 3 zakładki | zakładka 1 = `active + in_progress`; 2 = `suspended`; 3 = `closed`; etykieta „Zakończona” (nie „Zamknięta”) | P1 |
| S23 | admin | wyszukiwarka `q=`: numer umowy z S20, „Testowa”, „Anna Testowa”, „%” | znajduje po numerze/partnerze/kandydacie (pełne imię i nazwisko jednym ciągiem też); „%” szuka ZNAKU (nie zwraca całej listy); debounce ~300 ms | P1 |
| S24 | admin | pusta lista z filtrem vs bez | komunikaty różne: „Brak umów pasujących do wyszukiwania” vs „Brak umów aktywnych i w trakcie podpisu”; padnięte zapytanie → gałąź błędu z „Ponów” | P2 |
| S25 | admin | wiersz S20 → „Historia statusów” | dziennik pusty lub z utworzeniem; brak 500 | P2 |
| S26 | admin | kolumna akcji | ikonowa (`aria-label` + `title`); autor pod datą w „Wygenerowano”; przy 1366 px nic nie zasłania „Status podpisu” | P2 |
| S27 | admin | „Zmień status” na S20 → podgląd okna (bez zapisu) | dla `in_progress` opcja „Zawieś” NIEDOSTĘPNA (zawiesić można tylko `active`); powody katalogu: no_client_budget / contractor_found_other_project / … / other; `other` wymaga tekstu | P1 |
| S28 | admin | edycja `client_name` na S20 (autor = admin) → podgląd | dostępna dla autora/admina; dla podpisanej byłaby 409 — sprawdź tooltip/blokadę na PRAWDZIWEJ podpisanej umowie (tylko odczyt) | P2 |
| S29 | recruiter / sourcer / finance / tac | `/contracts/b2b-generator` | dostępne dla KAŻDEJ roli (decyzja 20.08); lista widoczna; „Generuj” widoczny (zapis 403 w podglądzie) | P1 |
| S30 | delivery_lead (D1) | `/contracts/b2b-generator` | widzi umowy klientów SWOJEGO portfela (D1 tak, D2 nie); klient bez przypisania → brak na liście | P1 |
| S31 | talent_community_manager | wiersz umowy → akcje | TCM ma „Zmień status” i „Potwierdź podpis” (decyzja 10.09) w całej organizacji — WIDOCZNE; **nie klikaj** | P1 |
| S32 | admin | katalog ról (29) w generatorze | dostępny adminowi; innym — brak | P3 |
| S33 | admin | `DELETE` umowy z S20 (własna, testowa) — jeśli P2 nie użyje jej | usunięta; numer zwolniony; historia statusów skasowana (CASCADE) | P2 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const c = await fetch('https://api.nexus.dynaminds.pl/api/contracts?limit=5',{headers:h}).then(r=>r.json());
console.log('domyślny filtr zwraca statusy:', [...new Set((c.items??c).map(x=>x.status))]); // active, ending
const b = await fetch('https://api.nexus.dynaminds.pl/api/contracts/b2b/generated?contract_status=active&contract_status=in_progress&q=Testowa',{headers:h});
console.log('b2b list', b.status);   // 200 (parametr powtarzalny, NIE contract_status[]=)
const bad = await fetch('https://api.nexus.dynaminds.pl/api/contracts/b2b/generated?contract_status=nope',{headers:h});
console.log('nieznany status →', bad.status); // 422
```
(Ścieżki B2B potwierdź w zakładce sieci przy otwieraniu generatora — zapisz prawdziwe w raporcie.)

## Znane pułapki

- Kontrakt NIE dziedziczy daty końca zamówienia — bezterminowy z okresem zamówienia w osobnych polach. Data końca w `end_date` skopiowana z zamówienia = P1.
- „Zakończeni” w profilu klienta decyduje UMOWA (`contract_end_date < dziś`), nie okres zamówienia.
- Podpis obustronny = kontrakt AKTYWNY od razu bez stawki przychodowej (`activate_without_revenue_gate`).
- Potwierdzenie podpisu przy różnicach warunków = 409 z `conflicts` i `can_keep_existing_terms` (P2 to testuje).

## Do raportu

ID i numer umowy z S20 (do sprzątania), zrzuty 3 zakładek generatora, tabela „rola → widzi generator / stawki w rejestrze / akcje statusu”.
