# Edytor CV 2 — PR 5: historia wersji i powrót pliku Word (13.10.2026)

Ostatni z pięciu PR-ów zatwierdzonych przez Artura 12.10.2026 (D4: „Wgraj
poprawiony plik Word”). Reguły: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`,
sekcja „Historia wersji i powrót pliku Word (PR 5)”.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Przycisk „Historia” | Panel z zatwierdzonymi wersjami CV etapu: numer, data, kto zatwierdził, plakietka „bieżąca”, „Porównaj”, „Pobierz DOCX” |
| Porównanie | Lista różnic między wybraną wersją a bieżącą treścią: zmienione, tylko w wersji (dojdzie), tylko w bieżącej treści (zniknie) |
| Przywrócenie | „Przywróć treść wersji N” wstawia jej treść jedną zmianą — całość cofa jedno „Cofnij” |
| Wgraj poprawiony plik Word | Plik .docx poprawiony poza NEXUSEM: najpierw lista różnic, potem „Wstaw treść z pliku Word”. Samo wgranie niczego nie zmienia |
| Klauzula zgody | Zostaje z bieżącego CV, niezależnie od tego, co jest w starej wersji albo w pliku |
| CV po wstawieniu | Nadal podpięte do generatora, z tym samym zrzutem zgody i szablonem — inaczej niż „Użyj innego CV” |

Backend: trzy trasy tylko do odczytu (`GET …/cv/branded/versions`,
`GET …/versions/{n}`, `POST …/import-preview`), bez migracji i bez nowej ścieżki
zapisu. Przy okazji konwerter Worda dostał limit kosztu (niżej).

## Jak powstał (prośba Artura o równoległą pracę)

Kontrakt API został ustalony najpierw (`frontend/src/lib/api/cvEditorHistory.ts`),
potem backend i frontend powstały równolegle w osobnych kopiach repo, a przeglądy
biegły równolegle z integracją. Raporty wykonawców były sprawdzane na zintegrowanej
gałęzi: testy, typy, strażnicy repo, przeklikanie w przeglądarce.

## Decyzje przyjęte domyślnie (do wiadomości Artura)

| Sprawa | Przyjęte | Dlaczego |
|---|---|---|
| Kto zapisuje | Edytor (jedna cofalna zmiana) + zwykły autozapis | Nowa trasa zapisu musiałaby rozstrzygać zgodę, szablon i link do generatora; „Użyj innego CV” robi to po swojemu i odłącza CV |
| Wybór pojedynczych różnic (makieta: „Weź z Worda / Zostaw z NEXUSA”) | Nie weszło — lista różnic i jedno wstawienie całości | Główny przypadek to „NEXUS ma mieć to, co dostał klient”. Po wstawieniu treść ocenia panel „Do poprawy” |
| Ocena zgodności różnic ze źródłami (makieta) | Nie weszła | Tę samą pracę robi QC po wstawieniu |
| Historia szkiców | Nie ma — tylko zatwierdzone wersje | Szkice nie są nigdzie zapisywane (autozapis nadpisuje) |
| Klauzula zgody z pliku albo starej wersji | Odrzucana, zostaje bieżąca (D3) | Także gdy bieżące CV nie ma klauzuli — wtedy zostaje bez niej |
| Treść wersji bez bramki zgody | Tak, jak bieżąca treść w edytorze | Bramka pilnuje plików wychodzących; pobranie Worda wersji nadal jest bramkowane |
| Język | Bez zmiany | Funkcja jest dla tego samego CV; angielski plik w polskim CV zostaje oznaczony „pl” |
| Limit | Podgląd importu 10 na minutę, plik do 10 MB, lista różnic do 600 wierszy | Konwersja Worda jest kosztowna |

## Liczby D5 (pobrania plików)

Odczyt produkcji 13.10.2026 w nocy: 3 wpisy `cv_file_downloaded` (jedna osoba,
pobranie pliku z listy wygenerowanych CV) — zapis pobrań działa od 12.10, więc
to za mało na wnioski. Do ponownego odczytu po tygodniu:
`SELECT details->>'surface', details->>'state', count(*) FROM activities WHERE action='cv_file_downloaded' GROUP BY 1,2`.

## Przeglądy przed PR-em (13.10.2026)

| Przegląd | Wynik | Co naniesione |
|---|---|---|
| Python (backend) | Bez blokerów | — |
| Bezpieczeństwo (backend) | Bez blokerów; istniejąca słabość konwertera Worda, do której podgląd importu dodał drugie wejście: plik z dziesiątkami tysięcy pustych akapitów albo stylów zajmował konwersję na wiele sekund | Limit akapitów i wierszy tabel w całym pliku (także pustych), limit liczby stylów, styl akapitu czytany raz na styl — z testami, które przedtem padały |
| TypeScript (frontend, w trakcie pracy wykonawcy) | Klauzula bez znacznika i akapit dopisany tuż przed nią: wtyczka struktury po cichu odrzucała zmianę | Sprawdzenie, czy zmiana zostanie przyjęta, i podmiana całej treści, gdy nie; sukces ogłaszany dopiero po faktycznej zmianie dokumentu |
| TypeScript (frontend, niezależny) | Lustrzany przypadek: klauzula bez znacznika i końcowy akapit USUNIĘTY tuż przed nią — treść wchodziła, ale „Cofnij” nic nie robiło i blokowało wszystkie wcześniejsze poprawki (wtyczka odrzucała odwrotność zmiany) | Zmiana jest przyjmowana tylko wtedy, gdy wtyczka struktury przyjmie także jej cofnięcie; inaczej cała treść jednym krokiem, a gdy i to nie — odmowa z komunikatem. Test odtwarzający błąd + 60 losowych dokumentów |

Z integracji i przeklikania:

- **Wgranie pliku nie wyszłoby z przeglądarki.** Klient API wysyłał plik bez
  jawnego `multipart/form-data`; strażnik repo to złapał przed PR-em.
- Losowy test różnic (200 dokumentów) przekraczał limit czasu pod obciążeniem —
  60 dokumentów i jawny limit.
- Przy otwartej historii przycisk „Do poprawy” wyglądał na włączony, choć jego
  panel był schowany; przy otwartym planie zmian jest teraz wyłączony.

Znane ograniczenia (nie blokują): lista różnic nie pokazuje zmian samej
struktury (znacznik stanowiska, punkt zamieniony na akapit, kursywa) — przy
równych tekstach panel mówi „Treść jest taka sama.”; lista pokazuje najwyżej 60
różnic („i jeszcze N”), a wstawienie obejmuje wszystkie; `fixStep` w panelu „Do
poprawy” (PR 2) korzysta z tego samego kroku minimalnego i przy klauzuli bez
znacznika może trafić na ten sam przypadek — poprawki QC nie usuwają końcowych
akapitów, więc ryzyko jest małe, ale warto je zamknąć osobno.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Lista i treść wersji | zielone lokalnie | `tests/test_cv_document_versions_unit.py` (bez bazy): „bieżąca” w każdym stanie CV, wersja sprzed 0287, 404, kolizja tras |
| Podgląd importu | zielone lokalnie | `tests/test_cv_docx_import.py`: brak zapisu, bramki, limit 10/min (429), plik bez pliku 422, limit treści |
| Limit kosztu konwertera | zielone lokalnie | tysiące pustych akapitów i stylów odrzucane w ułamku sekundy; styl pamiętany per styl |
| Trasy z bazą | w CI | 6 nowych testów (`test_candidate_stage_cv_branded.py`, `test_stage_cv_copy.py`) i istniejące testy `…/upload` po wydzieleniu wspólnych funkcji |
| Uprawnienia | zielone lokalnie | `authz_golden/candidate_stage_cv.json`, `cv_editor_import.json` — wzorce jak `…/versions/{n}/docx` i `…/upload` |
| Różnice i wstawienie | zielone lokalnie | `lib/__tests__/cv-editor-diff.test.ts` (25) na prawdziwym edytorze, w tym 60 losowych dokumentów: treść przychodząca + bieżąca klauzula, jedno „Cofnij” |
| Panel i sterownik | zielone lokalnie | `CvEditorHistory.test.tsx` (30) |
| Okno i harness | zielone lokalnie | testy okna (w tym wykluczanie się z planem), `cv-editor-harness.test.tsx` (+6, zero sieci) |
| Strażnicy repo | zielone lokalnie | `src/__tests__` i `lib/__tests__` (multipart, kolory, responsywność, inwentarz) |
| Przeglądarka | przeklikane ze zrzutami | harness w Chromium (skrypt Playwright) przy 1280×720, 768×1024 i 390×844: panel i przyciski w oknie, porównanie, przywrócenie + jedno Cmd+Z, wgranie pliku, wstawienie, klauzula na końcu; zero błędów strony |

## Niepotwierdzone

- **Trasy na prawdziwej bazie** — lokalnie nie ma Postgresa; sprawdza CI.
- **Prawdziwy plik Word poprawiony przez rekrutera** — konwersję pokrywają testy
  na plikach budowanych w teście i na szablonie firmy; harness używa treści z pamięci.
- **Edytor na produkcji po zalogowaniu** — przeklikany jest harness.

## Świadomie poza zakresem

- Wybór pojedynczych różnic i ocena ich zgodności ze źródłami (makieta).
- Historia szkiców (wymagałaby nowej tabeli i reguły retencji).
- Wpis w historii zdarzeń o podglądzie importu — trasa niczego nie zapisuje;
  wstawienie widać jako zwykłą edycję (`branded_cv_edited`).
- PL→EN — czeka na decyzję Artura (raport PR 4).
