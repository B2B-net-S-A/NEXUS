# Uwagi „bez pokrycia” w CV — pomiar na produkcji (17.10.2026)

Rekruterzy skarżą się, że panel „Do poprawy” w edytorze CV pokazuje uwagi
„bez pokrycia”. Przez nie przepuszczają CV przyciskiem „Przekaż mimo uwag…”.
Pomiar za zgodą Artura z 17.10.2026: tylko odczyt, same liczby, bez treści CV
i nazwisk. Zakres: wszystkie przebiegi QC od startu (23.09) i bieżący kod QC
na produkcji (79fa7b5af).

## W skrócie

- **Najwięcej uwag „bez pokrycia” daje kontrola AI, nie QC.** Niezależna
  kontrola AI generatora (`final_review`, prefiks „BRAK POKRYCIA (kontrola
  AI)”) ma w bieżących CV średnio 4,5 takiej uwagi na CV i pojawia się
  w 88% CV. **Co najmniej 32% z nich to fałszywy alarm:** zakwestionowany cytat
  stoi dosłownie w oryginale CV. W kolejnych 38% co najmniej 80% słów stoi
  w źródłach. Na prawdziwy brak pokrycia wygląda tylko 14%.
- **QC liczone kodem jest dziś spokojne:** 3,26 pozycji na CV (13.10: 4,72,
  wcześniej 8,13). Ale 80% pozycji największego sprawdzenia (`must_in_cv`) to
  „brak w CV, w oryginale i w rozmowie — zapytaj kandydata”, czyli luka
  kandydata, a nie błąd CV do poprawy.
- **Blokada `no_unsupported` jest prawdziwa według reguł, ale obchodzona.**
  Termin rzeczywiście nie występuje w źródłach (79 z 82), a stoi głównie na
  liście umiejętności i w podsumowaniu. Za 24 z 47 obejść stoi właśnie ta
  blokada, często z powodem „Kandydat potwierdził to w rozmowie”.
- **„Jakość QC” nie ma z czego liczyć.** Przez 30 dni zespół użył „To
  nieprawda” 4 razy, a przepuścił 47 CV mimo uwag. Trafność 100% w panelu
  `/settings/ai/qc-quality` oznacza brak danych, nie brak błędów.

## Skąd się biorą uwagi w panelu „Do poprawy”

| źródło | w bieżących CV | uwagi |
|---|---|---|
| QC liczone kodem (`cv_qc`) | 295 par | 3,26 pozycji na CV; 75 par z blokadą, 220 zaliczonych |
| Kontrola AI generatora (`final_review`) | 151 CV z dokumentem z 30 dni | 678 × „BRAK POKRYCIA” (4,49 na CV, w 133 CV) i 51 × „… i N kolejnych”, bo lista jest ucinana na 8 |
| Uwagi generatora (kod) | te same 151 CV | 153 × „WERYFIKUJ: technologia / umiejętność…”, 44 inne „WERYFIKUJ”, 12 × „BRAK POKRYCIA” z kodu; 272 × „MUST-HAVE” (panel chowa te, które pokrywa QC), informacje: 286 × „NICE-TO-HAVE”, 104 × nakładające się okresy |
| Kontrola AI edytora (`cv_editor_review`, ten sam weryfikator `verify_final_cv`) | 93 CV z wersją z 30 dni | 3 „verified”, 43 „unverified”, 47 „reviewed” z 249 uwagami; przy nich jest „Usuń” z komunikatem „Usunięto zdanie bez pokrycia.” |

Przebiegi QC od 23.09: 786 przebiegów, 231 par. Obejścia: 47 par (20%);
38 z nich w tygodniu od 12.10. Powody obejść:

| powód | obejścia |
|---|---|
| „Inny powód” (wolny tekst) | 33 (13 krótszych niż 20 znaków) |
| „Kandydat potwierdził to w rozmowie” | 8 |
| „To wymaganie nie dotyczy tej roli” | 4 |
| „Klient prosił o krótsze CV” | 2 |

Niezaliczone sprawdzenia w przebiegach obejść: `must_in_cv` (uwaga) 34,
`no_unsupported` 24, `title_matches_role` 20, `critical_skills` 15,
`must_bolded` 15, `must_in_roles` 11, `client_rules` 7 (zgoda RODO),
`bold_unsupported` 6, `cv_present` 4.

## 1. Kontrola AI: „BRAK POKRYCIA (kontrola AI)” — najgorsza trafność

Dla każdej uwagi z bieżących CV (151 CV, 740 uwag razem z powtórzeniami w jednym CV) skrypt wycina cytat
twierdzenia i szuka go w oryginale CV, notatkach i odpowiedziach ze
screeningu — tych samych źródłach, które czyta QC:

| koszyk | uwag | udział | co znaczy |
|---|---|---|---|
| cytat dosłownie w oryginale | 239 | 32% | fałszywy alarm |
| dosłownie tylko w notatkach / odpowiedziach | 11 | 1,5% | weryfikator mógł ich nie widzieć |
| ≥ 80% słów w źródłach | 280 | 38% | najpewniej fałszywy albo drobne przeformułowanie |
| 50–80% słów | 94 | 13% | do sprawdzenia |
| < 50% słów | 104 | 14% | wygląda na prawdziwy brak (81 z nich to CV w innym języku niż oryginał — część to tłumaczenie) |
| bez słów (daty, liczby) | 12 | 1,6% | — |

Według pola CV:

| pole | uwag | dosłownie w oryginale | ≥ 80% słów | < 50% | cytat ≤ 20 znaków |
|---|---|---|---|---|---|
| doświadczenie / experience | 312 | 160 (51%) | 46 | 59 | 248 |
| umiejętności / skills | 240 | 44 (18%) | 158 (66%) | 9 | 8 |
| edukacja / education | 115 | 17 (15%) | 37 | 25 | 108 |
| certyfikaty / certifications | 51 | 12 | 32 | 4 | 8 |
| języki, stanowisko, imię | 22 | 6 | 7 | 7 | — |

**Klasy błędów (opisane, bez cytowania CV):**

- **Krótkie pola doświadczenia** (firma, stanowisko, daty — 80% cytatów ma
  do 20 znaków) stoją dosłownie w oryginale, a weryfikator i tak zgłasza
  „brak potwierdzenia”. Prompt (`factual_verification.VERIFICATION_PROMPT`)
  wymaga, żeby CAŁE pole wynikało z cytatu dla tej samej roli i projektu,
  więc model odrzuca nawet nazwę firmy, gdy nie umie zacytować kontekstu.
- **Umiejętności:** prawie zawsze inny zapis tej samej technologii
  (rdzeń słowa jest w źródłach, dosłownego ciągu nie ma).
- **Edukacja:** nazwy uczelni i kierunków po przetłumaczeniu albo
  ujednoliceniu (generator od #2244 pisze polskie uczelnie po polsku).
- **Certyfikaty:** nazwa z rokiem — rok i słowa stoją w źródłach.

Ta sama kontrola stoi za uwagami w edytorze („Usunięto zdanie bez
pokrycia.”). Przycisk „Usuń” przy takiej uwadze może więc skasować prawdziwe
zdanie.

## 2. `must_in_cv` „zapytaj kandydata” — najwięcej szumu w QC

Bieżący kod: 584 pozycje w 196 z 295 par (66%) — 59% wszystkich pozycji QC.

| `fix` | pozycji | co mówi uwaga |
|---|---|---|
| `ask_candidate` | 469 (80%) | „Brak w CV, w oryginale i w rozmowie — zapytaj kandydata.” |
| brak (`None`) | 85 | „Brak w CV — kandydat mówił o tym w rozmowie, dopisz.” |
| `ai` | 30 | „Brak w CV — w oryginale jest, dopisz w roli.” |

Uwaga „zapytaj kandydata” mówi prawdę (wymagania nie ma w żadnym źródle),
ale w CV nie da się jej poprawić: to luka kandydata do rozmowy. W panelu
stoi jednak obok rzeczy do poprawienia i nabija licznik. Obejście
przepuszcza ją za każdym razem (34 z 47 obejść).

## 3. `no_unsupported` — prawdziwa blokada, którą zespół obchodzi

Bieżący kod: 82 pozycje w 46 parach (62 must, 20 nice).

- Termin nie występuje w źródłach nawet jako podciąg w 79 z 82 — dopasowanie
  się nie myli.
- Gdzie stoi w CV: lista umiejętności 56, podsumowanie „dlaczego ten
  kandydat” 32, doświadczenie 15, technologie 4. W 34 pozycjach (41%)
  **wyłącznie** na liście umiejętności — generator dopisuje wymagania klienta
  do umiejętności.
- Obejścia: 24 z 47 niosą tę blokadę; „Kandydat potwierdził to w rozmowie”
  8 razy. Rekruter wie z rozmowy to, czego nie ma w notatkach ani
  odpowiedziach, więc QC nie ma skąd tego wziąć.

## Pozostałe

- `title_matches_role`: 38 pozycji; w 20 nagłówek ma co najmniej połowę słów
  oczekiwanego tytułu (5 — co najmniej 75%), w 7 żadnego. Kandydat do
  złagodzenia w następnej kolejności.
- `dates`: 59 pozycji w 12 CV (około 5 na CV) — skupione w kilku CV.
- `role_order` (od 16.10): 23 pary.
- Poprawki QC jednym kliknięciem: 42 w 30 dni (`cv_qc_fix_applied`).

## Decyzje

- **D1 · Kontrola AI** (najpilniejsza).
  - **A (rekomendacja):** kod po weryfikatorze. Uwaga, której cytat stoi
    dosłownie w oryginale, notatkach albo odpowiedziach, znika (−32%). Przy
    ≥ 80% słów w źródłach „BRAK POKRYCIA” zmienia się na „WERYFIKUJ”: nie
    liczy się do „Do poprawy” i nie ma „Usuń” jednym kliknięciem (−38%).
    Ta sama reguła dla kontroli AI generatora i edytora. Pomiar przed i po:
    `qc_ai_review_coverage.py`.
  - **B:** schować kontrolę AI z panelu do czasu oceny na etykietach.
  - **C:** zmienić prompt weryfikatora — krótkie pola (firma, stanowisko,
    daty) sprawdzać kodem, nie modelem. Większa praca, wymaga zestawu
    ewaluacyjnego.
- **D2 · `must_in_cv` „zapytaj kandydata”.** Zamiast 469 pozycji „do
  poprawy” — jedna linia „Luki kandydata (N) — do rozmowy” poza licznikiem
  i poza obejściem. „Dopisz z oryginału” i „mówił w rozmowie” zostają
  uwagami.
- **D3 · `no_unsupported` po rozmowie.** Obejście z powodem „Kandydat
  potwierdził to w rozmowie” zapisuje „Potwierdzone z kandydatem” (istniejąca
  notatka) dla każdego zablokowanego terminu. Fakt zostaje w źródłach,
  a kolejne QC i kolejne CV tej osoby przechodzą bez obejścia. Osobno:
  sprawdzić, czy CV z terminami tylko na liście umiejętności powstały przed
  „silnikiem bez wypełniacza” (13.10) czy po nim.
- **D4 · Etykiety zamiast obejścia.** W oknie „Przekaż mimo uwag…” przy każdej
  blokadzie dwa przyciski: „QC się myli” / „Prawda, ale przepuszczam”.
  Daje to „Jakości QC” dane: dziś są 4 etykiety na 47 obejść.

**Decyzja do podjęcia.** Rekomenduję D1-A jako pierwszy PR. Zdejmuje około
70% uwag „bez pokrycia” z panelu i wyłącza „Usuń” jednym kliknięciem przy
twierdzeniach, które stoją w oryginale. To deterministyczny filtr po modelu,
więc nie zmienia generatora, kosztów AI ani wyniku QC. D2 i D4 to zmiany
panelu i okna obejścia, a D3 zmienia zapis notatek przy obejściu. Każda
z nich może iść osobnym PR-em po D1, w kolejności, którą wskażesz.

## Jak powtórzyć pomiar

Tylko odczyt, wynik to same liczby. `<prod>`, `<postgres>` i `<backend>` to
host i kontenery z notatek operacyjnych (nie w repo). Długi bieg potrzebuje
`ServerAliveInterval`, a wdrożenie w trakcie restartuje kontener i ucina
pomiar.

```bash
ssh -o ServerAliveInterval=30 <prod> "docker exec -i <backend> python -u -" < backend/scripts/qc_ai_review_coverage.py
ssh -o ServerAliveInterval=30 <prod> "docker exec -i <backend> python -u -" < backend/scripts/qc_item_features.py
ssh -o ServerAliveInterval=30 <prod> "docker exec -i -e QC_AUDIT_DAYS=30 <backend> python -u -" < backend/scripts/qc_truth_audit.py
```

Obejścia i pominięcia (psql z `SET default_transaction_read_only = on`):
liczby z `cv_qc_runs.override_reason` (prefiksy gotowych powodów z
`cv_qc.OVERRIDE_REASONS`), `cv_finding_dismissals` (źródło × sprawdzenie ×
powód) i niezaliczonych sprawdzeń w `result->'checks'` przebiegów
z `override_reason`.
