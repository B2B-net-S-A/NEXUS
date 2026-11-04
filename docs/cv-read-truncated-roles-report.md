# Ucięty odczyt AI oryginału CV — pomiar i propozycja (18.10.2026)

Znalezione przy przeklikaniu produkcji 18.10.2026: u jednego kandydata z
rekrutacji 789131 `candidates.experience` ma 15 stanowisk, a oryginał CV —
24 (brak lat 2008–2015 i 1994–1997). Z uciętego odczytu liczą się potem lata
w CV i QC (osobny wątek: „Zmień” przy latach, PR #2315).

Ten raport to tylko pomiar i propozycja. Na produkcji nic nie zmieniono;
zmiana odczytu czeka na decyzję Artura.

## Skąd cięcie — trzy miejsca w kodzie

1. **Limit 15 stanowisk.** Prompt pełnego odczytu (`llm_prompts.py`, l. 125–126)
   prosi o „ALL jobs … (max 15)”, a `_normalize_experience` w
   `services/cv_parser.py` (`_EXPERIENCE_MAX_ENTRIES = 15`) i tak ucina listę
   po 15. Limit wszedł 14.09.2026 (#1508) w miejsce dawnych 10.
2. **Okno wejścia 24 000 znaków.** `_window_cv_text` przy dłuższym CV bierze
   70% z początku i 30% z końca (`CV_PARSER_INPUT_CHAR_CAP = 24_000`), więc
   wypada **środek** dokumentu — u tego kandydata (32 190 znaków) właśnie
   2008–2015.
3. **Bieg masowy** (Fala 3) czyta `cv_text[:8000]` z sufitem 3000 tokenów —
   długie CV z tej ścieżki tracą całą końcówkę.

U kandydata z 789131 zadziałały 1 i 2 naraz: odczyt ma dokładnie 15 ról, CV
ma 26 zakresów dat (24 stanowiska + 2 szkoły).

## Pomiar na produkcji (read-only, 18.10.2026)

Metoda: transakcja tylko do odczytu w kontenerze backendu, wypisane same
liczby. Dla każdego kandydata z `raw_cv_text` i odczytem (`cv_parsed_at`)
liczę różne zakresy dat w tekście oryginału (formaty `MM.RRRR`, `RRRR-MM-DD`,
nazwy miesięcy PL/EN, „obecnie/present”) i porównuję z liczbą stanowisk +
szkół z odczytu: **luka = zakresy w tekście − (stanowiska + szkoły)**.
Kalibracja na przypadku z 789131: 26 zakresów vs 15 + 2 → luka 9 (zgadza się
z ręcznym przeliczeniem CV).

Miara jest przybliżona: zakres dat stoi też przy projektach, kursach
i certyfikatach, więc luka ≥ 3 to górna granica, a luka ≥ 5 — silny sygnał.

### Odczyty z ery v7 (od 14.09.2026) — 10 271 kandydatów

| Długość CV | Kandydaci | luka ≥ 3 | luka ≥ 5 | odczyt = limit (≥ 15 ról) |
|---|---:|---:|---:|---:|
| ≤ 8 000 znaków | 9 511 | 372 (3,9%) | 120 (1,3%) | 13 |
| 8 000–24 000 | 736 | 158 (21%) | 82 (11%) | 27 |
| > 24 000 (okno tnie środek) | 24 | 6 | 6 | 2 |
| **Razem** | **10 271** | **536 (5,2%)** | **208 (2,0%)** | **42** |

Rozkład liczby ról w odczycie ma garb na 15 (13: 27, 14: 23, **15: 37**,
16+: 5) — to ślad limitu.

Przyczyny wśród 208 odczytów z luką ≥ 5:

| Przyczyna | Kandydaci |
|---|---:|
| limit 15 | 6 |
| limit 15 + okno 24k | 2 |
| tylko okno 24k | 4 |
| ani limit, ani okno | 196 (153 z ≤ 5 rolami w odczycie, 43 z 6–14) |

### Cała baza — 56 785 kandydatów z CV i odczytem

- luka ≥ 5: 2 164 (3,8%), luka ≥ 3: 5 468 (9,6%);
- w CV 8–24 tys. znaków luka ≥ 5 ma 914 z 4 088 (22%);
- 236 profili ma ≥ 15 ról (42 z ery v7; reszta to w większości stanowiska
  z importu, nie z odczytu CV — 147 z nich ma w tekście co najmniej o 3 zakresy
  dat mniej, niż ról w profilu).

## Co z tego wynika

- **Pewne i tanie do naprawy:** limit 15 i okno 24k. Dotykają kilkudziesięciu
  profili z ery v7 (42 na limicie, 24 CV ponad 24k znaków), ale to właśnie
  najdłuższe kariery — seniorzy, u których lata doświadczenia ważą najwięcej.
- **Większa grupa niepewna:** 196 odczytów z luką ≥ 5 bez limitu i bez okna,
  zwykle z ≤ 5 rolami. Część to szum miary (daty projektów i kursów), część
  może pochodzić z biegu masowego `[:8000]`, a część to role pominięte przez
  model. Tego nie da się rozstrzygnąć bez obejrzenia próbki CV (treści nie
  wyciągałem).

## Propozycja (do decyzji)

- **D1. Limit 15 → 40** w prompcie i w `_EXPERIENCE_MAX_ENTRIES`. Koszt: dłuższa
  odpowiedź tylko u długich CV; sufit 8000 tokenów wystarcza (wpis roli ≈ 150
  tokenów). *Rekomendacja: tak.*
- **D2. Drugi odczyt samego doświadczenia dla długich CV.** Gdy tekst > 24k
  znaków albo odczyt ma ≥ limit ról, albo luka dat ≥ 3: drugie, wąskie
  wywołanie (tylko lista stanowisk: firma, rola, start, koniec) na tekście
  w częściach po ~12k znaków z zakładką 1k, scalenie po (firma, start)
  i wpisanie brakujących ról. Bez zmiany pól generatywnych. *Rekomendacja: tak,
  w tym samym PR co D1.*
- **D3. Licznik luki po każdym odczycie** (`zakresy dat w tekście` vs `role`)
  w logu i w metryce — żeby za tydzień zmierzyć efekt i zobaczyć grupę
  „ani limit, ani okno” na nowych CV. *Rekomendacja: tak.*
- **D4. Ponowny odczyt objętych profili** (42 na limicie + 24 długie CV, po
  D1–D2) jednorazowym skryptem z próbą (`--dry-run`) i paragonem bez nazwisk.
  Ręczne poprawki doświadczenia w profilu mają pierwszeństwo — skrypt ich
  nie nadpisuje. *Rekomendacja: tak, po OK na zapis na produkcji.*
- **D5. Próbka 20 CV z grupy „ani limit, ani okno”** obejrzana przez rekrutera
  albo przeze mnie za zgodą na odczyt treści — dopiero wtedy decyzja, czy
  ruszać bieg masowy `[:8000]`. *Rekomendacja: tak, przed ruszaniem biegu
  masowego.*

## Jak powtórzyć pomiar

Skrypt (same liczby, transakcja read-only) uruchamiany przez
`ssh … "docker exec -i <backend> python -u -" < measure.py` — klucz i nazwy
kontenerów jak w reference „read-only dostęp do produkcji”. Regex zakresów dat:
`(miesiąc)? RRRR([./-]MM([./-]DD)?)? [-–—|to|do] ((miesiąc)? RRRR(...)? | obecnie/present)`,
zliczane różne dopasowania.
