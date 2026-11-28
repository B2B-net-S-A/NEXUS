# Docling jako drugi czytnik CV — pomiar 28.11.2026, decyzja „nie bierzemy”

Przegląd narzędzi z 28.11.2026 dał Docling (MIT, LF AI & Data) jako kandydata
na drugi czytnik CV dla trudnych układów (dwie kolumny, tabele języków,
nagłówki graficzne), pod warunkiem że korpus pokaże poprawę. Pomiar jej nie
pokazał, więc w kodzie nic się nie zmienia: odczyt zostaje przy
`cv_text_extractor` (pdfplumber → pdfminer.six, OCR tesseractem, python-docx,
LibreOffice).

## Jak mierzone

- **Pliki:** 89 oryginałów CV (84 PDF, 5 DOCX) z przypadków korpusu z produkcji
  (`~/.nexus-staging/corpus/cv/`, eksport 26.11.2026), pobrane z kopii stagingu.
  Do repo nie trafiają.
- **Wersje:** Docling 2.154.0, torch 2.15.0+cpu, model układu Heron i TableFormer,
  Python 3.15 w obrazie workera, kontener bez sieci, limit 4 GB i 4 rdzenie
  (laptop, aarch64). Docling bez OCR (`do_ocr=False`), wynik `export_to_markdown`.
  Obecny czytnik: `extract_cv_text`, tak jak przy wgraniu.
- **Prawda:** zapis generatora z przypadku (firmy, stanowiska, uczelnie, języki,
  rok początku stanowiska). Liczone na tekście, bez modelu:
  pokrycie faktów, linie z faktami z dwóch sekcji naraz (sklejone kolumny)
  i rok początku stanowiska w promieniu 160 znaków od nazwy firmy.

## Wynik

| | obecny | Docling |
|---|---|---|
| firma znaleziona w tekście | 497/536 (92,7%) | 480/536 (89,6%) |
| stanowisko | 482/552 (87,3%) | 465/552 (84,2%) |
| uczelnia | 106/144 (73,6%) | 106/144 (73,6%) |
| rok przy firmie | 473/487 (97,1%) | 426/471 (90,4%) |
| pliki ze sklejonymi kolumnami (prawdziwe, po przejrzeniu) | 5 | 0 |
| pusty tekst | 0 | 4 |
| czas na CV, proces na plik (mediana / p90 / max) | 2,4 / 3,2 / 6,3 s | 6,5 / 10,9 / 19,3 s |
| czas, model w pamięci (mediana / max) | — | 2,4 / 18,8 s |
| szczytowy RSS | 0,2 GB | 1,2 GB mediana, 1,75 GB max; 2,4 GB proces ciepły |
| obraz workera | 2,32 GB | 5,69 GB (+2 GB pakiety, +0,67 GB wagi modeli) |

- **Gdzie Docling wygrywa:** rozdziela kolumny. W 5 CV, w których obecny tekst
  ma w jednej linii język z poziomem i stanowisko z datą, Docling daje czyste
  sekcje.
- **Gdzie przegrywa:** 3 PDF-y z normalnym tekstem (2,3–4,3 tys. znaków u nas)
  dały pusty wynik, bo model układu uznał stronę za obraz; jeden zgubił 5 z 8
  stanowisk. W wielu CV kolumnę dat odcina w osobny blok przed firmami, stąd
  spadek „rok przy firmie”. Włączony OCR (RapidOCR) tego nie ratuje: 961, 367
  i 2 358 znaków wobec 4 298, 2 297 i 3 503, 20–35 s na plik, 2,7 GB RSS.
- **Wybór tylko przy sklejonych kolumnach** (linia z językiem, poziomem i rokiem
  naraz) oznacza właśnie te 5 CV, bez fałszywych trafień. Na nich Docling
  daje łącznie +2 trafienia (+1, +1, +1, −1, 0).
- **Najważniejsze:** we wszystkich 8 CV, w których obecny tekst skleja kolumny,
  Nowe CV ma poprawne języki i daty stanowisk (sprawdzone z tekstem pliku). Model odczytu rozplątuje
  sklejone linie, więc błąd tekstu nie dochodzi do pól, które widzi rekruter.

Zysk +2 trafień na ok. 6% CV nie pokrywa kosztu: ok. 1,5 GB pamięci na odczyt
w workerze z limitem 4 GB, 3–4 razy dłuższy odczyt i obraz większy o 3,4 GB
przy każdym wdrożeniu.

## Kiedy wrócić

- korpus CV dostanie przypadek, w którym sklejone kolumny psują pole Nowego CV
  (język, data, firma) mimo modelu, albo
- czytnik ma obsłużyć skany i grafiki lepiej niż tesseract.

Wtedy ten sam pomiar na nowej wersji Docling (albo lżejszej ścieżce: sam
`docling-parse` z kolejnością czytania, bez torcha) i porównanie z tą tabelą.
Skrypty pomiaru leżą lokalnie w `~/.nexus-staging/eval/claude-docling/`.
