# Asystent prawny do umów B2B — raport końcowy (25.11.2026)

Plan i decyzje: `docs/asystent-prawny-plan.md`. Reguły: `docs/claude/asystent-prawny/`.

## Co weszło

Asystent działa w tle istniejących ekranów (decyzja Artura 25.11.2026) — bez
osobnego modułu.

| Część | Gdzie w NEXUSIE | Migracja | Funkcja AI |
|---|---|---|---|
| A. Korpus prawa, weryfikator cytatów, terminy, ukrywanie danych osób | `services/legal/`, `/api/legal/*` | `0784_legal_corpus` | F57 `legal_assistant` |
| B. Wzory własne | Generator → Dokumenty → „Nowy wzór z asystentem”, „Wzory własne” w „Nowy dokument” | `0785_custom_document_templates` | F58 `legal_template_draft` |
| C. Orzecznictwo (SAOS) | źródło asystenta, `/api/legal/cases/search` | `0786_legal_case_law` | — |
| D. Popraw dokument (DOCX ze śledzeniem zmian) | rejestr umów Generatora, Dokumenty kontraktu | `0787_legal_redline_ai` | F59 `legal_redline` |
| E. Treść podpisanych dokumentów kontraktu | odczyt umowy/aneksu/wypowiedzenia, narzędzia Jarvisa | `0788_contract_document_chunks` | — |
| F. Pismo na kontrakcie, zadania asystenta, Jarvis | „Napisz pismo”, wiersz pod „Co się dzieje”, pasek na liście kontraktów, `draft_legal_letter` | `0789_legal_assistant_tasks` | (F57) |
| G. Zgodność z umową ramową klienta w tle | zadanie na liście kontraktów, panel w kreatorze aneksu i „Nowej umowie”, okno ustaleń | `0790_legal_client_fit` | F60 `legal_client_fit` |
| H. Przepisy: źródła asystenta i „Przejrzyj wzór” | Przepisy → Źródła i boty | — | — |

Migracje idą po `0783_lost_review` z `main`, jeden head (`0790_legal_client_fit`).
Każda nowa tabela ma lustro w `entrypoint.sh` i sondę w `/api/health/deep`.

## Jak sprawdzone

- **CI (pełny przebieg na gałęzi):** sześć przebiegów; czerwone przebiegi
  wskazały realne błędy (scalanie kontraktów nie znało nowych tabel, odczyt
  Worda, logi, limit uploadu, multipart, link do karty klienta, własne
  ponawianie zapytań, limit zapytań po IP, atrapa w teście) — każdy poprawiony.
- **Przeglądy:** bezpieczeństwa (4 blokery: dane osób bez maski w „Popraw
  dokument”, zagnieżdżone pętle we wzorach, zip bomb, porównanie kwadratowe)
  i kodu (7 blokerów, m.in. weryfikator przepuszczał cytat bez pokrycia,
  500 przy mieszaniu stref czasowych, stan cytatu z przeglądarki, „Zatwierdzam”
  bez kontroli dat z modelu) — poprawione testami, które najpierw padały.
- **Staging (kopia produkcji z 25.11.2026, własna baza i własne pliki):**
  backend z gałęzi na 8101, front na 3101, ekran 1280 × 720, prawdziwy model.
  - Migracje 0784–0790 na kopii, `/api/health/deep` — 9 nowych tabel `healthy`.
  - Korpus: 16 aktów, 27 191 jednostek; orzecznictwo: 40 orzeczeń SAOS;
    treść dokumentów kontraktów klienta testowego: 585 odczytanych
    (34 bez pliku na stagingu, 2 nieczytelne).
  - Delivery Lead: pasek zadań na liście kontraktów (zgodność z umową ramową
    + odpowiedzi na wypowiedzenia), strona kontraktu z „Napisz pismo”,
    pismo na prawdziwej podpisanej umowie starej redakcji: termin „od
    kolejnego miesiąca” zgodny z NEXUSEM, ostrzeżenie o formie pisemnej,
    cytaty 2/2 sprawdzone, „Zatwierdzam” → zadanie zamknięte, DOCX
    w Dokumentach kontraktu. Kreator aneksu z panelem zgodności (luki
    z cytatami z umowy ramowej), Przepisy → źródła.
  - Administrator: „Popraw dokument” na umowie z rejestru (propozycja
    paragrafu z cytatami DORA sprawdzonymi z korpusem), „Nowy wzór
    z asystentem” (szkic z wykrytymi polami).
  - Rekruter bez dostępu do kwot: 403 na zadaniach, zgodności i piśmie;
    lista kontraktów niedostępna.
  - Test na stagingu wykrył trzy błędy jakości pisma (wymyślony znacznik
    i komentarz modelu w treści, litera „c.” w starej redakcji umowy,
    imię w mianowniku zamiast zwrotu) — poprawione i sprawdzone ponownie
    na prawdziwym modelu.

## Niesprawdzone / ograniczenia

- **Jarvis na żywo:** na stagingu Jarvis jest wyłączony — narzędzia
  `draft_legal_letter`, `search_contract_documents`, `read_contract_document`
  sprawdzone testami, nie rozmową.
- **„Otwórz w oknie maila”** nie klikane do wysyłki (staging bez poczty);
  sprawdzone testem komponentu.
- **Pobrany DOCX ze śledzeniem zmian** sprawdzony testami (python-docx),
  nie otwarty w Wordzie ręcznie.
- **Wzory własne:** porównanie zgodności tylko dla wzoru PL w wariancie JDG.
- **Wydajność:** zasilenie korpusu ok. 11 min; pętla odświeżania w workerze,
  na stagingu zablokowana.

## Do decyzji Artura

1. Zadania „Przejrzyj wzór” zapisują się także przy wyłączonym
   `LAW_RADAR_ENABLED` (widać je na ekranie zmian dopiero po włączeniu radaru).
2. Treść podpisanych umów konsultantów idzie do Voyage (wyszukiwanie po
   znaczeniu) z danymi osoby zamienionymi na znaczniki; pełny tekst zostaje
   w bazie. Wybrane jako wariant ostrożny.
3. Klucze AI F57–F60 na Sonnecie 5.5 bez osobnego pomiaru — zmiana modelu
   po pomiarze na modelu z produkcji.

## Po wdrożeniu

- `/api/health` → SHA z `main` z tą zmianą; `/api/health/deep` — 9 nowych tabel.
- Jednorazowo na produkcji (worker): `python -m scripts.legal_corpus_seed`,
  `python -m scripts.seed_legal_case_law`,
  `python -m scripts.backfill_contract_document_text --commit` (w paczkach).
- Przeklikać na produkcji: pasek zadań na liście kontraktów, „Napisz pismo”
  na kontrakcie z wypowiedzeniem, panel zgodności w kreatorze aneksu.
