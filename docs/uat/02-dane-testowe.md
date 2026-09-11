# 02 — Dane testowe

> Wszystko, co UAT tworzy na produkcji, ma prefiks i jest sprzątane. Repo jest publiczne:
> żadnych prawdziwych CV, nazwisk, e-maili, telefonów — ani w danych, ani w raportach.

## 1. Konwencja

- Prefiks nazwy: `[QA-E2E-YYYY-MM-DD]` (data założenia). Helper:
  `frontend/e2e/helpers/test-entities.ts` (`uniqueName`, `EntityTracker`).
- Każda encja zapisana w `wyniki/<karta>/utworzone.json`:
  `[{ "endpoint": "/api/candidates", "id": 123, "name": "[QA-E2E-2026-09-12] kandydat-a3f7" }]`.
- Sprzątanie: odwrotna kolejność tworzenia (dziecko przed rodzicem), `DELETE endpoint/id`;
  404 przy sprzątaniu = OK. Co nie da się usunąć przez API — zapisz w raporcie jako
  „do ręcznego usunięcia” z ID.
- Osoby fikcyjne mają e-maile w domenie `example.invalid` i telefony zaczynające się od
  `+48 000 000 …`. Dzięki temu żaden mail nie wyjdzie, a dedup po telefonie nie
  skleji ich z prawdziwym kandydatem.

## 2. Zestaw bazowy (zakłada Fala 0, żyje do końca Fali 2)

| # | Encja | Jak założyć | Uwagi |
|---|---|---|---|
| D1 | Klient `[QA-E2E-…] Klient Testowy` | Klienci → Dodaj (lub `POST /api/clients`) | NIP fikcyjny `0000000000`; przypisz DL z listy person (zakładka „Delivery Lead” w profilu klienta) |
| D2 | Klient `[QA-E2E-…] Klient Wieloosobowy` | jw. | jego ID dopisz do `MULTI_CONSULTANT_ORDER_CLIENT_IDS` (Coolify set env) |
| D3 | Rekrutacja `[QA-E2E-…] Senior Backend Developer` u D1 | Rekrutacje → Nowa | typ Body Leasing; must-have: `Python`, `PostgreSQL`, `Docker`; nice: `Kubernetes`; widełki 120–160 PLN/h; zdalnie |
| D4 | Rekrutacja `[QA-E2E-…] Data Engineer` u D2 | jw. | must-have: `Spark`, `SQL`; bez widełek (do testu gotowości) |
| D5–D9 | 5 kandydatów fikcyjnych | Kandydaci → Dodaj z CV (pliki z §3) | imiona z listy §3; jeden bez CV (D9) do testu „brak pliku” |
| D10 | Profil Championa dla D3 | Rekrutacja → Champion → import DOCX z §3 | sekcja 3 (stack) wypełniona: must `Python, PostgreSQL, Docker`, nice `Kubernetes` |
| D11 | Karta klienta D1 | Klient → Zasady współpracy | SLA 5 dni, min 3 kandydatów, limit 2 CV/proces |
| D12 | Reguła CV klienta D1 | Ustawienia → Reguły CV → D1 | język PL, nazwa pliku `CV_{Imie}_{Nazwisko}`, „Zapisz i zatwierdź” |

**Nie zakładaj:** kontraktów, zamówień, umów B2B w Fali 0. Powstają w przepływach P2–P4 i
są sprzątane po każdym przepływie.

## 3. Pliki fikcyjne (`docs/uat/fixtures/` — do wygenerowania, NIE commitować prawdziwych)

Wygeneruj lokalnie skryptem (python-docx / reportlab) i trzymaj w `wyniki/fixtures/`:

| Plik | Treść |
|---|---|
| `cv-01-anna-testowa.pdf` | „Anna Testowa”, `anna.testowa@example.invalid`, `+48 000 000 001`; 3 role: Python/PostgreSQL/Docker (2019–obecnie), Java (2016–2019), staż (2015); Warszawa; zgoda RODO w stopce |
| `cv-02-jan-probny.docx` | „Jan Próbny”, Data Engineer: Spark, SQL, Airflow; Kraków; daty w formacie `03.2020 – 06.2023` |
| `cv-03-maria-fikcyjna.pdf` | „Maria Fikcyjna”, Frontend: React, TypeScript; zdalnie; CV po angielsku |
| `cv-04-piotr-wzorcowy.pdf` | „Piotr Wzorcowy”, DevOps: Kubernetes, Terraform, Docker; brak dat miesięcznych (tylko lata) — test bezpieczników lat |
| `cv-05-skan.pdf` | jedna strona będąca SAMYM OBRAZEM (skan) — test OCR/pominięcia strony |
| `champion-D3.docx` | wzór Championa v4 (wygeneruj `backend/scripts/generate_champion_template.py --out-dir …`) wypełniony pod D3; stawka „do 160 zł/h netto” |
| `zamowienie-jednoosobowe.pdf` | „Zamówienie nr QA/001/2026”, okres 01.10.2026–31.12.2026, stawka 1200 PLN/MD netto, 60 MD, konsultant „Anna Testowa” |
| `zamowienie-wieloosobowe.pdf` | „Zamówienie nr QA/002/2026”, 3 pozycje: Anna Testowa 40 MD × 1200, Jan Próbny 30 MD × 1100, Piotr Wzorcowy 20 MD × 1300; bezterminowo |
| `zamowienie-kosztowe.pdf` | „Zlecenie nr QA/003/2026”, kwota 150 000 PLN netto, 2 osoby, bez MD |
| `md-import.xlsx` | arkusz z nagłówkiem tytułowym na 1. arkuszu, dane na 2.: kolumny `Konsultant`, `Ilość MD`, `Średnia Stawka MD`, `Nr zamówienia`, `Kwota`; wiersze dla 3 osób z QA/002 + 1 wiersz „Nieznany Człowiek” (test „brak zamówienia”) + 1 wiersz z nazwiskiem w odwrotnej kolejności |
| `zgoda-rodo.png` | zrzut fikcyjnego maila „Wyrażam zgodę…” od `anna.testowa@example.invalid` |

## 4. Sprzątanie po całym UAT (koniec Fali 2)

Kolejność: zamówienia i grupy → kontrakty → umowy B2B (`DELETE /api/contracts/b2b/generated/{id}` zwalnia numer) →
etapy kandydatów → kandydaci (`DELETE /api/candidates/{id}` — kaskada na CV, notatki, wyniki wyszukiwań) →
rekrutacje → reguła CV, karta klienta → klienci. Na końcu usuń ID klienta D2 z
`MULTI_CONSULTANT_ORDER_CLIENT_IDS`.

Weryfikacja: `GET /api/candidates?q=QA-E2E`, `GET /api/clients?q=QA-E2E`,
`GET /api/jobs?q=QA-E2E` → puste. Sprawdź też Insights → Rekrutacja → Placementy: żaden
placement testowy nie może zostać w rankingach (zatrudnienia z P2 liczą się do Hall of Fame
i — jeśli robione kontem rekrutera — do miesięcznych wyścigów z nagrodami; dlatego P2
robi się kontem admina, którego rankingi pomijają).
