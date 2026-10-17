# „Stawka w CV” w QC — fałszywe blokady i propozycja reguły (17.10.2026)

Rekruterzy zgłaszają uwagi QC „bez pokrycia”. Najostrzejsza z nich to
„Reguły klienta → Stawka w CV”: blokada, której nie da się pominąć („To
nieprawda” → 422), więc przy fałszywej stawce zostaje tylko „Przekaż mimo
uwag…”. Zmiana reguły QC to decyzja Artura — gałąź
`claude/qc-rate-in-cv-rule`, bez PR-a.

**Wynik pomiaru na produkcji (17.10.2026, tylko odczyt): problem dziś nie
występuje.** Od startu QC (23.09) w 786 zapisanych przebiegach 231 par nie
było ani jednej uwagi „Stawka w CV”; reguły klienta blokowały wyłącznie brak
zrzutu zgody RODO (31 par) i e-mail kandydata (1 para). Przeliczenie QC
bieżących CV wszystkich 295 par starą, ścisłą i nową regułą: zero bloków ze
stawką w każdej, ten sam wynik QC (220 par zaliczonych, 18 z niezaliczonymi
regułami klienta). Zmiana jest więc zapobiegawcza: na dziś nie zmienia żadnej
pary, chroni przed fałszywymi blokadami w CV płacowych i łapie stawki bez
waluty, których stara reguła nie widzi.

## Co jest nie tak

1. **QC bierze walutę z początku słowa.** `rate_mentions` (`cv_qc.py`) szuka
   w całym bloku słowa o pieniądzach („wynagrodz”, „stawk”, „rate”) i luźnego
   `_AMOUNT` („liczba + zł/pln/eur…” bez granicy słowa): „250 zleceniobiorców”
   to dla niego 250 zł, „3 europejskich” — 3 EUR.
2. **„Usuń stawkę” liczy inną regułą niż uwaga.** Edytor (PR #2290) usuwa
   zdania według ścisłego `money_text.is_rate_text`, więc przy fałszywej
   uwadze kończy komunikatem „W CV nie ma stawki…”.
3. **Ścisłe `is_rate_text` ma własne fałszywe stawki w CV.** Pisane dla
   notatek („stawka 150 obecnie” to stawka) bierze liczbę po słowie
   o pieniądzach: „Naliczanie wynagrodzeń 300 pracowników”, „System
   wynagrodzeń 2.0”, „Error rate 0.1 po wdrożeniu”. Proste podstawienie go
   w QC wymieniłoby jedne fałszywe blokady na inne.
4. **Uśpiony błąd na produkcji.** CV z punktami „Moduł wynagrodzeń dla 250
   zleceniobiorców.” i „Naliczanie wynagrodzeń 300 pracowników w SAP HCM.”:
   QC zgłasza pierwszy, a „Usuń stawkę” zostawia go i kasuje drugi
   (sprawdzone kodem z `main`). Rekruter traci prawdziwą treść CV, a uwaga
   zostaje. Przycisk pojawia się tylko przy uwadze o stawce, a takich dziś nie
   ma (pomiar wyżej), więc błąd nikogo jeszcze nie dotknął.
5. **Prawdziwe stawki, które dziś przechodzą QC:** „Stawka 150 B2B”,
   „Stawka: 150”, „Stawka 150 za godzinę”, „Wynagrodzenie: 18 000”, „Rate
   140” — bez waluty `_AMOUNT` ich nie widzi.
6. **Koszt:** `_AMOUNT` wraca kwadratowo na długim ciągu cyfr — blok
   „stawka” + 20 tys. cyfr to 7 s CPU na każde liczenie QC. (Ten sam problem
   w `money_text` dla notatek naprawił B2B-net-S-A/NEXUS#2295, na produkcji
   od 17.10.2026; `_AMOUNT` w QC zostaje do decyzji.)

## Propozycja (na gałęzi)

- `money_text.is_cv_rate_text` — reguła stawki dla treści CV:
  - kwota za czas („150 zł/h”) — zawsze;
  - kwota z walutą, także słowem („150 złotych”, „50 euros”), w oknie 80
    znaków wokół słowa o pieniądzach — chyba że tuż przed nią stoi budżet
    projektu („o budżecie 2 mln PLN”);
  - liczba bez waluty po słowie o pieniądzach tylko na końcu zdania albo
    przed formą rozliczenia (B2B, netto, „za godzinę”, „+ VAT”, „złotych”)
    i tylko, gdy nie jest rokiem ani datą („Specjalista ds. wynagrodzeń
    2018 – 2022”).
  `is_rate_text` zostaje dla notatek i materiału generatora.
- `rate_mentions` sprawdza cały blok tą funkcją (`_mentions_rate`), a „Usuń
  stawkę” — zdanie po zdaniu tą samą funkcją. Cały blok, nie zdania, bo skrót
  spoza listy („approx.”) dzieliłby stawkę na dwa zdania i QC by ją
  przepuściło; przy blokadzie lepsza uwaga bez poprawki jednym kliknięciem
  niż stawka u klienta. Lista skrótów w `_SENTENCE_PIECE` dostała „approx.”,
  „godz.”, „mies.”, „dz.”, „hr.”, „tys.”, „mln.” — żeby „Usuń stawkę” radziło
  sobie ze „Stawka godz. 150 zł”.
- `_AMOUNT` usunięte. `QC_VERSION` bez zmian: na 295 parach wynik jest ten
  sam, a podbicie przeliczyłoby nieudane pary i zapisało przebiegi bez zmiany
  (`_store_run` porównuje też wersję).
- Testy bez bazy w `tests/test_cv_qc.py` (sekcja „Stawka w CV”): 20 zdań,
  które nie są stawką, 25 stawek (także w pogrubieniu, w środku akapitu, ze
  skrótem i walutą słowem), cytat wskazuje właściwy blok, koszt liniowy na
  200 tys. cyfr, sklejonym słowie i ciągu spacji. Każdy przykład sprawdza
  naraz uwagę QC i „Usuń stawkę”. Na kodzie z `main` 19 z pierwszych 30
  przypadków pada, a test kosztu się nie kończy; na gałęzi przechodzą
  wszystkie (lokalnie 486 testów bez bazy z plików, które dotykają kwot;
  24 czerwone to te same testy z Postgresem co na `main` — sprawdza je CI).
- **Przegląd kodu (python-reviewer, 17.10.2026)** znalazł w pierwszej wersji
  kwadratowy koszt na sklejonym słowie i ciągu spacji, stawki ze skrótem
  i walutą słowem, które przestawały blokować, lata stanowisk jako „stawkę”
  i słowa z CV w wyjściu skryptu. Każde zgłoszenie sprawdziłem i poprawiłem;
  przypadki są w testach.

## Przykłady (wynik kodu, nie ocena ręczna)

„QC dziś” = `qc-truth-1` na produkcji; „ścisłe” = to, co dziś usuwa „Usuń
stawkę” (zdanie po zdaniu, podział zdań z produkcji); „propozycja” = gałąź.
Kod uruchomiony lokalnie: `main` jako produkcja, gałąź jako nakładka.

| Zdanie | Stawka? | QC dziś | ścisłe `is_rate_text` | propozycja |
|---|---|---|---|---|
| Moduł wynagrodzeń dla 250 zleceniobiorców. | nie | blokuje | — | — |
| Wdrożenie systemu wynagrodzeń w 3 europejskich spółkach. | nie | blokuje | — | — |
| Integracja wynagrodzeń dla 5 złożonych procesów kadrowych. | nie | blokuje | — | — |
| Rate limiting dla 10 zleceń/s. | nie | blokuje | — | — |
| System zarobków dla 40 usługodawców, 2 euroobligacje. | nie | blokuje | — | — |
| Naliczanie wynagrodzeń 300 pracowników w SAP HCM. | nie | — | blokuje | — |
| System wynagrodzeń 2.0 w SAP. | nie | — | blokuje | — |
| Wynagrodzenia 500+ pracowników miesięcznie. | nie | — | blokuje | — |
| Naliczanie wynagrodzeń 300 za pomocą SAP. | nie | — | blokuje | — |
| Error rate 0.1 po wdrożeniu. | nie | — | blokuje | — |
| Wdrożyła moduł wynagrodzeń o budżecie 2 mln PLN. | nie | — | blokuje | — |
| Stawki VAT 23% i 8% w module fakturowania. | nie | — | — | — |
| Specjalista ds. wynagrodzeń 2018 – 2022 | nie | — | blokuje | — |
| Analityk wynagrodzeń 2021 | nie | — | blokuje | — |
| Kierownik ds. wynagrodzeń 03.2019 - 05.2021 | nie | — | blokuje | — |
| Raport wynagrodzeń 2024 | nie | — | blokuje | — |
| Zarządzanie stawkami 2020–2023 | nie | — | blokuje | — |
| Compensation &amp; Salary 2020 | nie | — | blokuje | — |
| Rate 100 per request | nie | — | blokuje | — |
| Zarobki 300/500 pracowników | nie | — | blokuje | — |
| Payroll: wynagrodzenia dla 3 spółek, koszt licencji 40 000 PLN rocznie. | nie | blokuje | blokuje | blokuje |
| Moduł Salary 360. | nie | — | blokuje | blokuje |
| Stawka: 150 zł/h B2B. | tak | blokuje | blokuje | blokuje |
| Oczekiwana stawka: 120 PLN netto/h | tak | blokuje | blokuje | blokuje |
| Stawka: **150 zł/h** | tak | blokuje | blokuje | blokuje |
| **Stawka:** 150 zł/h | tak | blokuje | blokuje | blokuje |
| Stawka 150 B2B | tak | — | blokuje | blokuje |
| Stawka 150 za godzinę | tak | — | blokuje | blokuje |
| Stawka: 150 | tak | — | blokuje | blokuje |
| Stawka 150 + VAT | tak | — | blokuje | blokuje |
| Wynagrodzenie: 18 000 | tak | — | blokuje | blokuje |
| Zarobki 20k netto | tak | — | blokuje | blokuje |
| Rate 140 | tak | — | blokuje | blokuje |
| Daily rate: 900 EUR | tak | blokuje | blokuje | blokuje |
| Expected rate: 900 EUR per day | tak | blokuje | blokuje | blokuje |
| Stawka dzienna: 1200 PLN netto. | tak | blokuje | blokuje | blokuje |
| Hourly rate 45 USD | tak | blokuje | blokuje | blokuje |
| Stawka 150 zł, budżet projektu 2 mln PLN. | tak | blokuje | blokuje | blokuje |
| Zna branżę płatności. Oczekiwana stawka 150 zł/h netto. Dostępna od zaraz. | tak | blokuje | blokuje | blokuje |
| Daily rate approx. 600 EUR | tak | blokuje | — | blokuje |
| Expected salary approx. 20 000 PLN | tak | blokuje | — | blokuje |
| Wynagrodzenie mies. 18 000 PLN | tak | blokuje | — | blokuje |
| Stawka godz. 150 zł | tak | blokuje | — | blokuje |
| Rate hr. 50 USD | tak | blokuje | — | blokuje |
| Stawka: 150 złotych za godzinę | tak | blokuje | blokuje | blokuje |
| Rate: 50 euros per hour | tak | blokuje | blokuje | blokuje |
| Stawka godzinowa 150 złotych | tak | blokuje | — | blokuje |
| Oczekiwania finansowe: 150 zł/h netto | tak | — | — | — |
| Stawka: 2000 | tak | — | blokuje | — |
| Stawka godzinowa: 150 B2B | tak | — | — | — |

Propozycja blokuje każdą stawkę z tabeli, którą blokuje dzisiejsze QC, i 7
kolejnych. Z treści CV nowa fałszywa blokada to tylko „Moduł Salary 360.”
(liczba po słowie o pieniądzach na końcu zdania). Zostaje w obu regułach:
„koszt licencji 40 000 PLN” w zdaniu ze słowem „wynagrodzenia”. Nie łapie
ani dziś, ani po zmianie: kwoty za czas bez słowa o pieniądzach
(„Oczekiwania finansowe: 150 zł/h netto”), liczby po przymiotniku („Stawka
godzinowa: 150 B2B”) i gołego roku-kwoty („Stawka: 2000”). To pierwsze można
łapać osobno (kwota z walutą i „/h” w dowolnym miejscu), ale wymaga zmiany
„Usuń stawkę” przy kwocie w pogrubieniu — poza tą propozycją.

## Co się zmieni po wdrożeniu

- **Dziś nic w wynikach** — żadna z 295 par nie zmienia wyniku QC ani
  uwag reguł klienta, więc kolejka Delivery Leada i obejścia „Przekaż mimo
  uwag…” (D6) zostają jak są.
- **Nowe CV:** fałszywa „stawka” z waluty w słowie („250 zleceniobiorców”)
  i z lat stanowiska nie zablokuje wysyłki; prawdziwa stawka bez waluty
  („Stawka 150 B2B”, „Rate 140”) zablokuje — przy już przepuszczonej parze to
  nowy klucz blokady, więc trzeba ją usunąć albo przepuścić jeszcze raz (D6).
- **„Usuń stawkę”** usuwa tylko zdania, które QC uznaje za stawkę, i radzi
  sobie ze skrótem („Stawka godz. 150 zł”).

## Pomiar na produkcji (17.10.2026, za zgodą Artura)

Tylko odczyt, same liczby; kod gałęzi przebazowanej na f76589572 (to, co
było na produkcji) jako nakładka w procesie kontenera, ok. 4 min.

| | stara (`_AMOUNT`) | ścisła (`is_rate_text`) | propozycja |
|---|---|---|---|
| pary z CV (z przebiegiem QC od 23.09) | 295 | 295 | 295 |
| pary z „Stawką w CV” | 0 | 0 | 0 |
| bloki ze stawką | 0 | 0 | 0 |
| pary z niezaliczonymi regułami klienta | 18 | 18 | 18 |
| pary zaliczone QC | 220 | 220 | 220 |

Zmiany wyniku (`fail_to_pass`, `pass_to_fail`), odrzucone i nowe bloki: brak.
Błędy: 0 (9 par bez CV pominiętych). Zapisane przebiegi (SQL): 786 przebiegów,
231 par, 0 pozycji „Stawka w CV”; `client_rules` nie zaliczone — „Klient
wymaga zrzutu zgody RODO” 77 pozycji / 31 par, „CV zawiera e-mail” 2 / 1.
`qc_truth_audit.py` i `qc_eval_dismissals.py` nie były potrzebne: pomiar
liczył pełne QC każdej pary i liczba zaliczonych jest ta sama, a
`client_rules` nie ma pominięć „To nieprawda”.

Komendy (`<prod>`, `<postgres>`, `<backend>` — host i kontenery z notatek
operacyjnych, nie w repo):

1. **Zapisane przebiegi:**

   ```bash
   ssh <prod> "docker exec -i <postgres> psql -U nexus -d nexus -P pager=off" <<'SQL'
   SET default_transaction_read_only = on;
   WITH r AS (
     SELECT candidate_id, job_id, override_reason IS NOT NULL AS ovr,
            EXISTS (SELECT 1 FROM jsonb_array_elements(result->'checks') c,
                           jsonb_array_elements(coalesce(c->'items', '[]'::jsonb)) i
                    WHERE c->>'key' = 'client_rules'
                      AND i->>'detail' LIKE 'Stawka w CV%') AS rate
     FROM cv_qc_runs WHERE created_at > now() - interval '30 days')
   SELECT count(*) AS pairs,
          count(*) FILTER (WHERE rate) AS pairs_with_rate,
          count(*) FILTER (WHERE rate AND ovr) AS pairs_with_rate_overridden
   FROM (SELECT candidate_id, job_id, bool_or(rate) AS rate, bool_or(ovr) AS ovr
         FROM r GROUP BY 1, 2) p;
   SQL
   ```

2. **Trzy reguły na tych samych parach** (gałąź musi stać na commicie
   z produkcji plus zmiana; długi bieg bez wyjścia zrywa SSH, a wdrożenie
   restartuje kontener — 17.10 pierwszy bieg zabiło wdrożenie #2295):

   ```bash
   cd backend
   python3 scripts/qc_overlay.py scripts/qc_rate_mentions_eval.py \
       app/services/money_text.py app/services/cv_qc.py \
     | ssh -o ServerAliveInterval=30 <prod> \
       "docker exec -i -e QC_AUDIT_DAYS=60 <backend> python -u -"
   ```

   Warunek merge'u: `dropped_blocks.cv:currency_word`, `cv:per_time`
   i `cv:rate_word_then_number` = 0 (spełniony — `dropped_blocks` puste).

## Poza zakresem

- Koszt `money_text` w notatkach (`is_rate_text`, `strip_rates_and_availability`)
  — naprawione w B2B-net-S-A/NEXUS#2295 (na produkcji f76589572). Zostało
  kwadratowe: własny `_MONEY_EXTRA` w `cv_command_ai` i bezpośrednie
  `MONEY_RE.finditer` w `cv_qc._amounts` (mogą przejść na `money_matches`).

## Decyzja

Czy scalić „Stawkę w CV” liczoną tą samą regułą dla treści CV co „Usuń
stawkę” (`is_cv_rate_text`, bez podbicia `QC_VERSION`)? Pomiar pokazał, że
dziś nie zmienia to wyniku żadnej z 295 par, więc koszt wdrożenia (kolejka
Delivery Leada, obejścia D6) jest zerowy. Zysk jest na przyszłość: znika
fałszywa „stawka” z waluty w słowie i z lat stanowiska w CV płacowych, QC
zaczyna blokować stawki bez waluty („Stawka 150 B2B”, „Rate 140”), „Usuń
stawkę” przestaje kasować cudze zdania, a QC przestaje liczyć kwadratowo.
Rekomendacja: tak, jako zwykły PR z auto-merge. Skargi rekruterów na uwagi
„bez pokrycia” nie dotyczą tej reguły — warto zmierzyć „Jakość QC” dla
`no_unsupported` i pozostałych sprawdzeń.
