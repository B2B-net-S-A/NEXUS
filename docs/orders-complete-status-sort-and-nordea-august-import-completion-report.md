[← docs](./)

# Zamówienia: przycisk, statusy, sort + sierpniowy import Nordea — raport

> 2026-08-24. Kod: [#1248](https://github.com/artur-t-96/Nexus/pull/1248) (`82cf9f2`,
> zmergowany, prod zweryfikowany) + follow-up [#1250](https://github.com/artur-t-96/Nexus/pull/1250).
> Cztery tickety modułu **Klienci → Zamówienia**. Trzy weszły kodem, czwarty był
> operacją na importerze, który już istniał.

## Premisa dwóch ticketów była błędna — i to jest najważniejsze ustalenie

**#1** mówił, że „Uzupełnij zamówienie" jest *włączone wybranym klientom* (Nordea).
Nie było żadnej listy klientów. Przycisk wisiał na `{activeOrder && …}`, więc
renderował się wyłącznie tam, gdzie **istniał już wiersz `ClientOrder`**. Nordea
ma je z importu, inni klienci nie — **różnica DANYCH, nie konfiguracji**.

Ta sama klasa błędu była już raz naprawiana dla pól inline; komentarz przy
[`saveOntoOrder`](../frontend/src/components/OrdersAndContractsTab.tsx) opisuje ją
wprost („u Aliora te pola działają wyłącznie dlatego, że jego zamówienia zostały
kiedyś zaimportowane"). Tamta poprawka ominęła jedną powierzchnię: sam przycisk.

Dowód z produkcji sprzed wdrożenia: u **samej Nordei** karta renderowała **169**
przycisków „Dodaj przedłużenie" i tylko **28** „Uzupełnij zamówienie".

**#2** mówił, że uzupełnienie pól nie przenosi zamówienia do „Aktywni". Promocja
`draft → active` **działała** w backendzie (`_auto_activate_unless_status_explicit`,
a `EditOrderDialog` nie wysyła `status`, więc nic jej nie tłumiło). Kłamała
**warstwa liczenia**: `PILL_PREDICATES` czytały `contract_status`, a uzupełnianie
zmienia status **zamówienia**.

## Kod

| Ticket | Zmiana |
|---|---|
| #1 | Przycisk bez bramki `activeOrder`; `EditOrderDialog` przyjmuje `order: … \| null`; `POST /orders` dopiero **przy zapisie** (anulowanie nie zostawia „(bez numeru)"); PDF jedzie w tym samym POST-cie |
| #2 | `active` obejmuje też kontrakt **szkicowy** z aktywnym zamówieniem; `drafts` przestaje trzymać szkicowy kontrakt, gdy ma już aktywne zamówienie |
| #3 | `consultant_asc` / `consultant_desc` w `OrderListControls` — kontrolka jest wspólna, więc jedna zmiana obsługuje **oba widoki i wszystkie pięć pigułek** |

Świadomie **nie** dodano „kontraktor bez zamówienia" do Draftu — to cała populacja
z #1, licznik urósłby o ludzi, których nikt tam nie szukał.

## Cztery defekty złapane po napisaniu kodu

Trzy z przeglądu adwersarialnego (16 agentów, 6 potwierdzonych / 6 odrzuconych),
czwarty dopiero z produkcji. Wszystkie wprowadził ten PR.

1. **Duplikat zamówienia (HIGH).** Guard „czy szkic już istnieje" siedział
   w `saveOntoOrder`; ścieżka dialogowa wołała `createDraftOrder` wprost.
   Nieudana dopłata stawki kosztowej zostawiała okienko otwarte w trybie
   tworzenia → drugie „Zapisz" zakładało DRUGIE zamówienie, a pierwsze zostawało
   sierotą w pigułce Draft.
   **Pierwsza poprawka nie wystarczyła:** dialog dostaje `createDraftOrder`
   przez stan rodzica, więc trzyma **jedną instancję** przez całe życie —
   zamrożone domknięcie widziało `draftOrderId === null` mimo świeżo założonego
   szkicu. Guard musi czytać **ref**. Wykrył to dopiero test.
2. **Pigułka „Aktywni" (MEDIUM)** wciągała kontrakty `ended`/`void` z wiszącym
   wierszem `active` (zamówienia domyka nocny skaner po dacie, więc to norma) —
   kontraktor pokazywałby się w „Aktywni" i „Zakończeni" naraz.
3. **Sort (LOW).** `consultant_display_name` zwraca `„—"` dla linii bez kandydata;
   myślnik wypada przed każdą literą.
4. **Sort, znaleziony NA PRODUKCJI (#1250).** Listę otwierał wiersz
   `{ } Wojciech Łazowski`. To nie był nowy defekt danych, tylko **rozjazd
   warstw**: `normalize_person_name_part` (backend) sprowadza nazwisko do
   `[a-z0-9]`, więc import ten wiersz dopasował bez problemu — sortowanie było
   jedynym miejscem czytającym nazwisko dosłownie.

Testy: **1568 zielonych**. Każdy nowy test zweryfikowany odwrotnie — przy
cofniętej poprawce pada; guard duplikatu wywala dodatkowo 4 testy istniejące.

## Import (#4) — kodu nie było trzeba

`nordea_order_import.py` + `POST /api/admin/clients/{id}/nordea-orders/import` +
panel istniały na `main`. Sierpniowy CSV przechodzi produkcyjnym parserem bez
zmian (295 wierszy, `195,8 → 195.80`, zamówienie 13-osobowe zachowane).

### Co zablokowało pełny plik

Apply zwraca **409 i nie zapisuje niczego**, dopóki jest choć jeden wiersz
niedopasowany. Pierwszy dry-run: **19 niedopasowanych + 1 niejednoznaczny**.

Rozbiór tej dziewiętnastki okazał się ważniejszy niż sama liczba — **pięć osób
BYŁO w Nexusie**, tylko inaczej zapisanych, co widać dopiero po zestawieniu
`unmatched_file` z `nexus_only`:

| W pliku | W Nexusie | Kto miał rację |
|---|---|---|
| Mariusz Szewczyk | `[acive/ Mariusz Szewczyk` | **Nexus zepsuty** — marker statusu w imieniu |
| Wiktoria Typer-Dentko | Wiktoria Typer | Nexus nieaktualny |
| Łukasz Domżał - Drzewicki | Łukasz Domżał | Nexus nieaktualny |
| Dawid **K** Wróbel | Dawid Wróbel | **plik** dokłada inicjał |
| Tomasz Styp | Tomasz Styp**-Rekowski** | **plik** ucina człon |

Dlatego korekta poszła **w obie strony**: trzy nazwiska poprawione w Nexusie
(32303, 12538, 26203), dwa w kopii pliku. Przemianowanie całej piątki „zgodnie
z arkuszem Finansów" skasowałoby Tomaszowi człon nazwiska.

### Co zostało poza importem i dlaczego

| Kogo | Ile wierszy | Powód |
|---|---|---|
| Zamówienie **274607** | 13 | Nikt z nich nie miał kontraktu u Nordei. **Domknięte w drugim przebiegu** — patrz niżej |
| Filip Jabłoński | 2 | **Trzy** rekordy kandydata (kontrakty 344/346/348) — trafienie w zły podmienia numer, okres i stawkę żywemu zamówieniu, bezpowrotnie |
| Kamil Kowalczyk | (w 274607) | **Sześć** identycznych rekordów kandydata |

Mateusz Śladewski dostał kontrakt (**#578**, 283965, 20.08–31.12.2026, 187/h) —
jego zaangażowanie biegnie do końca roku, więc ma realną wartość operacyjną.

### Wynik zastosowanego importu

Plik: 280 wierszy · `sha256 29830bc1…`

| | |
|---|---|
| Dopasowanych osób | **277 / 277** |
| Zamówienia | 262 nowe · 17 zaktualizowanych · 1 bez zmian |
| Stawki ramowe | 279 nowych · 1 zaktualizowana |
| **Zmienione stawki kosztowe** | **0** ← wymóg ticketu |
| Niedopasowane / niejednoznaczne | 0 / 0 |
| Dopasowania „miękkie" | 17 — **wszystkie bezpieczne** |

„Miękkie" dopasowania warto rozumieć, zanim ktoś się ich przestraszy: każde
nadpisało **auto-tytuł** w rodzaju `Jan Kowalski — Nordea: Data Engineer (41950)`
prawdziwym numerem zamówienia. Zero nadpisań realnego numeru — sprawdzone przed
zapisem na `order_changes` z podglądu (`before.order_number` nigdzie nie był
6-cyfrowy).

Pigułki po imporcie: **Aktywni 302 → 321**, **Kończące się 30d 0 → 26**,
**Draft 39 → 20**.

### Osoby w Nexusie spoza pliku (18)

Arkadiusz Stępień · Artur Królak · Błażej Kanczkowski · Rajan Chellappa ·
Piotr Ciszek · Dominik Czesuła · Dawid Krzysztoń · Michał Dyzma ·
Piotr Dziubiński · Filip Jabłoński · Łukasz Grądzki · Igor Taras ·
Jarosław Pastuszak · Sergey Karelin · Marcin Orecki · Mateusz Polanski ·
Sebastian Nowak · Patryk Tatarek

## Drugi przebieg: domknięcie 274607 (tego samego dnia)

Zamówienie **nie było wygasłe** — kończy się 31.08.2026, czyli 7 dni po imporcie,
więc dane wciąż miały wartość operacyjną. Decyzja właściciela: założyć kontrakty,
przyjmując **stawkę kosztową = ramowa 56,47** (świadome założenie: plik nie niesie
kosztowej, a ramowa jest baseline'em, nie tym, co płacimy — stąd marża −0,07/h).

Założono **12 kontraktów** (579–590), wszystkie `hourly`, 160 h/mc, koszt 56,47,
przychód 56,4, okres 2025-09-01 → 2026-08-31 (Burdalski i Błaszczak od 2025-09-18).
**Kamil Kowalczyk pominięty** — sześć identycznych rekordów kandydata, a trafienie
w zły przypisałoby pieniądze niewłaściwej osobie.

Import wierszy 274607 (12 wierszy, `sha256 90284439…`): **12/12 dopasowanych**,
7 zamówień utworzonych, 5 bez zmian, **12 harmonogramów stawki ramowej**,
**0 zmian stawki kosztowej**, 0 niedopasowanych. Rozbicie 7/5 jest spójne
z tym, jak powstały kontrakty: pięć pierwszych założono formularzem „Nowy
kontraktor / zamówienie", który tworzy Contract **razem z Order**, więc import
zastał je gotowe; siedem kolejnych powstało przez `POST /api/contracts`, który
zamówienia nie zakłada — te importer dołożył.

### Czego nauczyła ta część

- **Formularz zakłada Contract + Order, API tylko Contract.** Stąd „7 utworzonych,
  5 bez zmian" — nie rozjazd, tylko dwa różne źródła.
- **`Return` w tym formularzu wysyła go od razu**, zanim zdąży się przestawić
  „Jednostkę stawki". Pierwszy kontrakt (578) powstał przez to z 187/**mc** zamiast
  187/h i wymagał poprawki. Jednostkę ustawiaj `form_input`-em, nigdy klawiszem.
- **Picker kandydatów renderuje BŁĄD jak pustkę.** „Brak wyników dla …" pojawiło się
  dla osoby, którą `/api/candidates` zwraca bez problemu — to była chwilowa awaria
  zapytania, nie brak rekordu. Ta sama klasa defektu co `failure-must-not-render-as-empty`,
  tyle że w `NewContractorOrderDialog`. Warto naprawić osobno.
- **Nazwiska wpisuj bez diakrytyki** — wyszukiwarka i tak składa `ł`/`ę`, a wpisanie
  polskich znaków bywało zawodne.

## Weryfikacja na produkcji

- `/api/health` → `82cf9f2`, `healthy`.
- Kontraktor **bez zamówienia** (kontrakt 514) renderuje oba przyciski i podpowiedź
  „Brak zamówień — uzupełnij numer, okres i stawki powyżej, a zamówienie powstanie
  automatycznie jako szkic" — czyli dokładnie kryterium #1.
- Kontrakt #578 (szkic) z aktywnym zamówieniem wszedł do **Aktywni**, nie został
  w Draft — kryterium #2.
- `<select>` sortowania ma „Konsultant — A→Z" i „Z→A" — kryterium #3.
- Wiersze niosą numery, okresy i stawki przychodowe z pliku przy **nietkniętej**
  stawce kosztowej (np. Adam Formela: 284498, przychód 158/h, koszt 118/h).

## Do decyzji właściciela danych

1. **`{ } Wojciech Łazowski`** (kontrakty 514, 533) — kod jest już odporny (#1250),
   ale sam wiersz nadal niesie klamry.
2. **Stawka kosztowa 56,47 na kontraktach 274607 to ZAŁOŻENIE**, nie liczba z pliku
   (kolumna G to stawka ramowa). Do potwierdzenia z Finansami — dziś daje marżę
   −0,07/h na dwunastu kontraktach.
3. **Duplikaty kandydatów** — Filip Jabłoński (3 rekordy), Kamil Kowalczyk (6).
   Dopóki istnieją, import będzie ich świadomie pomijał; ich wiersze nadal czekają.
4. **`NewContractorOrderDialog` pokazuje awarię zapytania jako „Brak wyników"** —
   mylące przy zakładaniu kontraktu komuś, kto w bazie jest.
