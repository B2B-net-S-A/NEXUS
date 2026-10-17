# „Stawka w CV” w QC — fałszywe blokady i propozycja reguły (17.10.2026)

Rekruterzy zgłaszają uwagi QC „bez pokrycia”. Najostrzejsza z nich to
„Reguły klienta → Stawka w CV”: blokada, której nie da się pominąć („To
nieprawda” → 422), więc przy fałszywej stawce zostaje tylko „Przekaż mimo
uwag…”. Zmiana reguły zmienia wynik QC, dlatego to propozycja do decyzji
Artura — gałąź `claude/qc-rate-in-cv-rule`, bez PR-a.

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
4. **Błąd na produkcji dziś (8d0d97564).** CV z punktami „Moduł wynagrodzeń
   dla 250 zleceniobiorców.” i „Naliczanie wynagrodzeń 300 pracowników
   w SAP HCM.”: QC zgłasza pierwszy, a „Usuń stawkę” zostawia go i kasuje
   drugi (sprawdzone kodem z `main`). Rekruter traci prawdziwą treść CV,
   a uwaga zostaje.
5. **Prawdziwe stawki, które dziś przechodzą QC:** „Stawka 150 B2B”,
   „Stawka: 150”, „Stawka 150 za godzinę”, „Wynagrodzenie: 18 000”, „Rate
   140” — bez waluty `_AMOUNT` ich nie widzi.
6. **Koszt:** `_AMOUNT` wraca kwadratowo na długim ciągu cyfr — blok
   „stawka” + 20 tys. cyfr to 7 s CPU na każde liczenie QC.

## Propozycja (na gałęzi)

- `money_text.is_cv_rate_text` — reguła stawki dla treści CV: kwota za czas
  („150 zł/h”); kwota z walutą przy słowie o pieniądzach, chyba że tuż przed
  nią stoi budżet projektu; liczba bez waluty po takim słowie tylko na końcu
  zdania albo przed formą rozliczenia (B2B, netto, „za godzinę”, „+ VAT”).
  `is_rate_text` zostaje dla notatek i materiału generatora.
- `rate_mentions` sprawdza blok zdanie po zdaniu tą samą funkcją co „Usuń
  stawkę” (`_mentions_rate`) — uwaga, której nie da się pominąć, zawsze ma
  działającą poprawkę, a poprawka usuwa tylko to, co QC zgłosiło.
- `QC_VERSION` `qc-truth-1` → `qc-truth-2`; `_AMOUNT` usunięte.
- Testy bez bazy w `tests/test_cv_qc.py` (sekcja „Stawka w CV”): 12 zdań,
  które nie są stawką, 17 stawek (także w pogrubieniu i w środku akapitu),
  cytat wskazuje właściwy blok, koszt na 200 tys. cyfr. Każdy przykład
  sprawdza naraz uwagę QC i „Usuń stawkę”. Na kodzie z `main` 19 z nich
  pada, a test kosztu nie kończy się; na gałęzi wszystkie przechodzą
  (lokalnie 467 testów bez bazy z plików, które dotykają kwot; 24 czerwone to
  wyłącznie brak Postgresa — sprawdza je CI).

## Przykłady (wynik kodu, nie ocena ręczna)

„QC dziś” = `qc-truth-1` na produkcji; „ścisłe” = to, co dziś usuwa „Usuń
stawkę”; „propozycja” = gałąź.

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
| Payroll: wynagrodzenia dla 3 spółek, koszt licencji 40 000 PLN rocznie. | nie | blokuje | blokuje | blokuje |
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
| Oczekiwania finansowe: 150 zł/h netto | tak | — | — | — |

Zostaje w obu regułach: „koszt licencji 40 000 PLN” w zdaniu ze słowem
„wynagrodzenia” (kwota z walutą przy słowie o pieniądzach) i kwota za czas
bez takiego słowa („Oczekiwania finansowe: 150 zł/h netto” — dziś też
przechodzi). To drugie można łapać osobno (kwota z walutą i „/h” w dowolnym
miejscu), ale wymaga zmiany „Usuń stawkę” przy kwocie w pogrubieniu — poza tą
propozycją.

## Co się zmieni po wdrożeniu

- **Pary z fałszywą stawką** przy przeliczeniu (`recompute_outdated`, tylko
  nieudane pary sprzed wysłania) tracą blokadę; jeśli nic innego nie blokuje,
  przechodzą QC z przebiegiem z dnia wdrożenia — od tej daty kolejka Delivery
  Leada liczy ich oczekiwanie.
- **Obejścia „Przekaż mimo uwag…” (D6)** zostają: znikające blokady to
  podzbiór zgody. Nowa blokada prawdziwej stawki („Stawka 150 B2B”) ma nowy
  klucz, więc dla tej pary trzeba będzie przepuścić jeszcze raz albo usunąć
  stawkę — zgodnie z D6.
- **Zaliczone pary** nie są przeliczane; nowa blokada pojawi się przy
  następnym liczeniu QC (okno, bramka ruchu liczy na żywo).

## Pomiar na produkcji — czeka na zgodę Artura

Liczb z produkcji tu nie ma: odczyt produkcji wymaga zgody w czacie.
Wszystko tylko do odczytu, wynik to same liczby. `<prod>`, `<postgres>`
i `<backend>` — host i kontenery z notatek operacyjnych (nie w repo).

1. **Jak często dziś** (zapisane przebiegi, 30 dni):

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

2. **Stara i nowa reguła na tych samych parach** (kod gałęzi jako nakładka
   na obraz produkcji, przez stdin):

   ```bash
   cd backend
   python3 scripts/qc_overlay.py scripts/qc_rate_mentions_eval.py \
       app/services/money_text.py app/services/cv_qc.py \
     | ssh <prod> "docker exec -i -e QC_AUDIT_DAYS=30 <backend> python -"
   ```

   Pokaże per reguła (`legacy`, `strict`, `cv`): pary i bloki ze stawką, pary
   z niezaliczonymi regułami klienta i zaliczone QC, a dla `cv`:
   `fail_to_pass` (tyle par przestanie blokować), `pass_to_fail` (nowe
   blokady), `pairs_rate_gone` / `pairs_rate_new` i cechy bloków, które
   przestają blokować. **Warunek merge'u:** `dropped_blocks.cv:currency_word`,
   `cv:per_time` i `cv:rate_word_then_number` = 0 — inaczej któryś blok może
   być prawdziwą stawką i trzeba go obejrzeć w aplikacji. `QC_RATE_WORDS=1`
   dopisze słowa, w których stara reguła widziała walutę, i słowa po liczbie
   w nowych blokadach (same słowa, bez zdań).

3. **Reguła z `qc-to-nieprawda-i-jakosc-qc.md`** przed podbiciem
   `QC_VERSION`: `qc_truth_audit.py` i `qc_eval_dismissals.py` bez nakładki
   i z nakładką — tak samo jak w kroku 2, z ich nazwą zamiast
   `qc_rate_mentions_eval.py`. Oczekiwane: `blocking_items` niższe o liczbę
   fałszywych stawek, pozostałe sprawdzenia bez zmian (`client_rules` nie ma
   pominięć „To nieprawda”, więc `qc_eval_dismissals` nie powinien się
   zmienić).

## Decyzja

Czy „Stawka w CV” w QC ma liczyć się tą samą regułą dla treści CV, co „Usuń
stawkę” (`is_cv_rate_text`, `qc-truth-2`)? Za: znikają fałszywe blokady
z walutą w słowie („250 zleceniobiorców”, „3 europejskich”), QC zaczyna
blokować stawki bez waluty („Stawka 150 B2B”, „Rate 140”), „Usuń stawkę”
przestaje kasować zdania płacowe („Naliczanie wynagrodzeń 300 pracowników”),
a QC nie liczy już kwadratowo. Przeciw: wynik QC się zmienia — nieudane pary
dostają przebieg z dnia wdrożenia, a pary z nową, prawdziwą blokadą tracą
obejście D6. Rekomendacja: tak, po pomiarze z kroku 2 (warunek: zero
odrzuconych bloków z walutą jako słowem, kwotą za czas albo liczbą zaraz po
„stawka”). Jeśli zmiana QC ma poczekać, sam błąd z punktu 4 (kasowanie
cudzego zdania) da się naprawić osobno, bez zmiany wyniku QC: „Usuń stawkę”
na `is_cv_rate_text`, a QC bez zmian.
