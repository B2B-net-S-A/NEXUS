# „Dlaczego nasz kandydat” jako kompetencje, lata „w obszarze, w tym jako X”, miesiące, AI, CEFR (17.11.2026)

<!-- indeks: prompt 14, bez „Specjalizacji”, „Doświadczenie w…”, `_FIT_VERDICT_RE` a „zgodności”, „w tym M lat jako”, branża po średniku, „AI i uczenie maszynowe”, CEFR -->

Pomiar poprawek 17.11.2026 (126 CV zatwierdzonych 09–16.11 z zapisanym startem,
kopia produkcji z 16.11; raport z makietami, prywatny:
https://claude.ai/artifact/K3jm8gcpR3JTajaQW825VY). Decyzja Artura: R1–R4
i poziom języka w CEFR; reguła Nordei z numerem w tytule zostaje.

## Co mówiły dane

- 40% CV zatwierdzonych bez zmian; „Dlaczego nasz kandydat” poprawione w 44%.
- Punkty 3–5: 85% punktów generatora zaczynało się od czasownika w czasie
  przeszłym (jedno zadanie z jednej roli), po poprawce 14%. Rekruterzy piszą
  „Doświadczenie w…”, „Praktyczne doświadczenie z…”, punkty o ok. 40% dłuższe,
  z firmą i kontekstem. Pokrycie umiejętności MUST się nie zmieniało
  (0,51 → 0,49) — to forma, nie słowa kluczowe.
- „Specjalizacja: …” była w 125 ze 126 CV; usunięta ręcznie w 21.
- Lata w punkcie 1: 24 CV w górę, 3 w dół. Główna przyczyna: liczenie samych ról
  o tej nazwie, a rekruter liczy cały staż w obszarze.
- 25 CV z rolą bez miesiąca; w 17 oryginał miał miesiąc przy tym roku.
- Kategoria „Dane i BI” zmieniana na „AI / LLM / RAG” w 4 z 11 poprawek umiejętności.

## Co jest w kodzie (prompt `legacy_v7` wersja 14)

- **Punkt 2** to zdanie o 3–6 głównych technologiach w kontekście („Praktyczne
  doświadczenie z … w …”), bez etykiety i bez gołej listy. Słowa
  „Specjalizacja” w prompcie nie ma także w zakazie, bo samo podsuwało etykietę.
- **Punkty 3–5** nadal po jednym must-have, ale jako kompetencja: zdanie do ~35
  słów od „Doświadczenie w…” / „Praktyczne doświadczenie z…” / „Praktyka w…”,
  z firmą albo projektem ze źródła i dowodem. Wolno łączyć fakty z kilku ról.
  Blind CV dalej bez nazw firm (dodatek blind wygrywa).
- **Punkt 1:** gdy role pokrewne tego samego obszaru dają co najmniej rok więcej:
  „8 lat doświadczenia w IT, w tym 7 lat jako DevOps Engineer”. Role spoza
  obszaru (gastronomia, sklep) nie wchodzą.
  - `_fix_experience_years` przy liczbie ogólnej Z wyliczeniem „w tym” nie
    podstawia sumy wszystkich ról (wliczyłaby kelnerowanie); górną granicę
    pilnuje `_apply_summary_standard`. Sama „N lat w IT” bez „w tym” dalej
    dostaje sumę ról, jak dotąd.
  - `client_sector.apply_client_sector`: punkt z własnym „w tym” dostaje branżę
    jako osobny fakt po średniku („…, w tym 7 lat jako X; 3 lata w sektorze
    bankowym (mBank)”). Wcześniej dopisek przepadał.
- **`_FIT_VERDICT_RE`** łapie „zgodne/zgodny/zgodna/zgodnie”, nie „zgodności”:
  „Doświadczenie w zapewnianiu zgodności z wymaganiami DORA” to fakt, a przy
  punktach od „Doświadczenie w…” stary wzorzec usuwał go z podsumowania.
- **Daty ról:** miesiąc ze źródła zawsze, gdy źródło go podaje (także słownie).
- **Kategorie umiejętności (4b):** „AI i uczenie maszynowe” / „AI and machine learning”.
- **Języki:** gdy źródło podaje CEFR, sam poziom („Angielski – C1”). Opisu słownego
  nie zamieniamy na CEFR (to byłaby ocena, nie fakt); język ojczysty zostaje.
- **„Dopasuj pod rekrutację”** w edytorze (`cv_command_ai.TAILOR_PRESET`) pisze
  punkty 3–5 w tej samej formie.

## Pomiar na Solu przed wdrożeniem (17.11.2026)

6 CV (Orlen ×2, PKO, Alior, Nordea ×2), po 2 biegi przed i po, tryb „tailored”, polityki
centralne jak na produkcji. „Specjalizacja” 12/12 → 0/12; punkty 3–5 od czasownika
w przeszłym 36/36 → 0/36; z firmą lub projektem 14/36 → 34/36; zawsze 5 punktów; mediana
punktów 2–5 148 → 196 znaków (max 31 słów); kategoria AI w 7/12 CV; Blind CV 6 biegów
bez nazwy firmy w punktach. Po pierwszym pomiarze dopisane:

- **Stopień udziału zostaje** („uczestniczyła” nie staje się „projektowaniem”) — model
  zdejmował osłabienie przy formie „Doświadczenie w…”.
- **„w tym M lat jako X”**: M to suma wszystkich ról zawodu, jedno określenie, punkt 1 do
  ~20 słów; `_fix_role_subfigure` podnosi zbyt niskie M do sumy dat pasujących ról (Sol
  napisał „ponad 1 rok jako DevOps” przy ponad 5 latach), nigdy ponad liczbę obszaru.
- **Poziom języka słownie w języku CV** („German basic” w polskim CV → „podstawowy”).
- **Kategoria AI tylko z nazwanymi technologiami**, bez ogólników („artificial
  intelligence” u Scrum Mastera po kursie wstępnym).

Kontrola AI nie recenzuje `why_points` (`factual_verification.NARRATIVE_SECTIONS`, decyzja
z audytu 22.09), więc dłuższe punkty z firmami nie są sprawdzane automatycznie — przy
przeglądzie po tygodniu czytaj je z oryginałem.

## Czego tu nie ma

- Uwagi w edytorze (skąd liczba lat, data końca przed startem, rola bez miesięcy
  przy miesiącach w oryginale) — osobna zmiana w panelu „Do poprawy”.
- Ścieżka v10 (`CV_GENERATION_PIPELINE=v10`) bez zmian.
- CV wygenerowane wcześniej nie zmieniają się same.

## Pomiar po wdrożeniu

Po tygodniu generacji na nowej kopii: `python -m scripts.cv_edit_report --weekly --days 14`
i ten sam podział poprawek „Dlaczego” (forma punktów, lata w punkcie 1, „Specjalizacja”).
Cel: mniej CV z poprawionym „Dlaczego” niż 44% i lata w górę rzadziej niż w 19% CV.
Testy: `backend/tests/test_cv_why_competencies.py`.
