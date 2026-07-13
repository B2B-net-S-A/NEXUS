# Generator CV B2B — koniec „tekst nachodzi na siebie" (klauzula RODO)

> Naprawa nakładania się treści CV na klauzulę zgody RODO w pobranym DOCX/PDF.
> PR 2026-07-13. Dotyczy `backend/app/services/cv_generator_b2b/docx_renderer.py`.

## Problem (zgłoszenie)

W wygenerowanym CV **tekst nachodzi na siebie**: ostatnie linie treści (np.
`Technologie: Java, Spring Boot, PostgreSQL, Kafka`) nakładały się na klauzulę
RODO przypiętą do dołu strony — klauzula była nieczytelna, dokument wyglądał na
zepsuty.

## Przyczyna

Klauzula RODO (`add_bottom_pinned_rodo`) to pływająca ramka DrawingML przypięta
do dolnego marginesu strony (PR #659). Ramka używała **`wrapNone`** —
`wrapNone` **nie rezerwuje miejsca** w przepływie tekstu. Gdy treść CV wypełniała
stronę aż do pasma, w którym siedzi przypięta ramka, tekst przepływał **pod** nią
(`allowOverlap="1"`), a ostatnie linie **nakładały się** na klauzulę.

Jednostkowe testy sprawdzały tylko atrybuty XML (ramka istnieje, jest wyjustowana,
przypięta do dołu) — nie wychwytywały nakładania układu, więc błąd przeszedł.

To fundamentalne ograniczenie `wrapNone`: ramka przypięta do dołu przy pełnej
stronie **zawsze** nałoży się na treść (fizyka — brak rezerwacji miejsca).

## Rozwiązanie

Jedna zmiana atrybutu opakowania: **`wrapNone` → `wrapTopAndBottom`**.

`wrapTopAndBottom` sprawia, że ramka **rezerwuje swoje pasmo** u dołu strony —
tekst jest wypychany **nad** nią i nigdy pod nią nie przepływa. Gdy treść CV
sięgnęłaby zarezerwowanego pasma, jej nadmiar (wraz z klauzulą) **spływa na
kolejną stronę** zamiast się nakładać. Klauzula zostaje na dole **ostatniej**
strony, **raz**, wyjustowana, z czerwoną linijką — i **nigdy się nie nakłada**.

Zachowane wymagania zespołu (z PR #659/#639):
- **raz** (nie stopka, która powtarzałaby się na każdej stronie),
- **dół ostatniej strony**,
- brak „RODO na górze strony" (dawna hybryda in-flow — usunięta już w #659).

### Dlaczego nie stopka / nie in-flow

- **Stopka** rezerwuje miejsce i nie nakłada się, ale **powtarza klauzulę na
  każdej stronie** wielostronicowego CV (zespół to odrzucił w #659). Dodatkowo
  Word (evenAndOdd=off → footer1 pusty/default) i LibreOffice (renderuje
  footer2 „even" z logami) wybierają **różne** części stopki — kruche.
- **In-flow** nie nakłada się, ale przy przelaniu strony klauzula ląduje pod
  ostatnią linią przy **górze** ostatniej strony („RODO na górze" — odrzucone).

`wrapTopAndBottom` to zmiana minimalna (1 atrybut), zgodna z obraną architekturą
(pływająca ramka, raz, dół) i **ściśle lepsza** od `wrapNone`.

## Weryfikacja (LibreOffice DOCX→PDF, ground truth klienta)

Klient dostaje **DOCX** (brak serwerowej konwersji do PDF) → renderuje Word;
podgląd w apce = docx-preview; LibreOffice = proxy weryfikacyjne (jak w #659).

Wyrenderowano **14 rozmiarów CV** (1–7 stanowisk × 1–7 obowiązków), DOCX→PDF
przez LibreOffice, pomiar nakładania i pozycji klauzuli przez PyMuPDF:

| stan | wynik |
|---|---|
| przed (`wrapNone`) | `s5_full` (5×4): treść `Technologie:` nakłada się na RODO o ~3.8pt (repro 1:1 ze zgłoszeniem) |
| po (`wrapTopAndBottom`) | **overlaps=0 we wszystkich 14 przypadkach**; RODO zawsze ~83–84% (dół ostatniej strony) |

Najciaśniejszy przypadek graniczny (`j5_r4`, 5×4): odstęp treść→RODO = 16.9pt
(~0.6 cm) — czysty, bez nakładania. Wizualnie potwierdzone (screenshot).

99% CV (treść niesięgająca samego dołu) — **bez zmiany**: RODO ląduje raz na dole
istniejącej ostatniej strony. Tylko CV wypełniające ostatnie ~13% strony (dawniej
= nakładanie) teraz spływają czysto na kolejną stronę.

## Zmienione pliki

- `backend/app/services/cv_generator_b2b/docx_renderer.py`
  - `add_bottom_pinned_rodo`: `<wp:wrapNone/>` → `<wp:wrapTopAndBottom/>`;
    zaktualizowany docstring + komentarz przy wywołaniu (rationale rezerwacji pasma).
- `backend/tests/test_cv_generator_b2b_pipeline.py`
  - `test_rodo_clause_pinned_to_page_bottom_on_short_cv` i `…_on_full_cv`:
    asercja `wrapNone` → `wrapTopAndBottom` **+ nowy guard `assert "wrapNone" not
    in body`** (regresja: `wrapNone` = nakładanie).

## Znane ograniczenia (bez zmian, poza zakresem)

- Klauzula RODO nadal **niewidoczna w podglądzie „Podgląd"** (docx-preview nie
  pozycjonuje pływających ramek `wps:txbx`) — stan sprzed tej zmiany, osobny wątek.
  Widoczna w pobranym DOCX/PDF (plik wysyłany do klienta).
- CV wypełniające ostatnie ~13% strony zyskują kolejną stronę z klauzulą na dole
  (świadomy trade-off: czysta strona zamiast nakładania — brak wolnego lunchu, bo
  klauzula w polu treści zawsze potrzebuje miejsca).

## Uruchamialne sprawdzenie (bez lokalnego venv backendu)

`ruff check` + `ruff format --check` na `docx_renderer.py` — zielone.
Asercje obu testów RODO przeszły na świeżo wyrenderowanym DOCX (short + full CV).
Pełny pytest — w CI (`Backend (ruff + pytest)`).
