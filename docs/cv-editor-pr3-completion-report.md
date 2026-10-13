# Edytor CV 2 — PR 3: AI na zaznaczeniu (13.10.2026)

Trzeci z pięciu PR-ów zatwierdzonych przez Artura 12.10.2026. Rekruter zaznacza
fragment CV w edytorze i prosi o jego skrócenie, rozwinięcie z oryginału,
redakcję, korektę albo tłumaczenie — i dostaje propozycję „było / będzie” do
decyzji. Reguły: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja
„AI na zaznaczeniu (PR 3)”.

## Co się zmieniło

| Obszar | Zmiana |
|---|---|
| Dymek nad zaznaczeniem | B · Skróć · Rozwiń z oryginału · Przeredaguj · Popraw język · Na angielski. To samo w menu „AI” w pasku narzędzi (klawiatura, telefon) |
| Karta propozycji | „Było / będzie”, „Przyjmij”, „Doprecyzuj”, „Jeszcze raz”, „Odrzuć”. Przyjęcie to jedna cofalna zmiana na zaznaczonym zakresie |
| Bez nowych faktów | Kod odrzuca propozycję z liczbą, datą, nazwą albo technologią spoza zaznaczonego tekstu i mówi, o co poszło |
| Rozwiń z oryginału | Tylko z cytatem, który serwer znalazł w oryginalnym CV albo w notatkach; plakietka „Zgodne ze źródłem”, cytat na karcie, „Pokaż w oryginale” |
| Zatwierdzone CV | Zamówienie i odrzucenie propozycji niczego nie zmieniają; nowy szkic powstaje dopiero przy „Przyjmij” |
| Gdy AI nie działa | Karta mówi „chwilowo niedostępna”, edytor działa dalej |

Backend: trasa `POST /api/pipeline/stages/{id}/cv-ai/selection`, klucz AI
`cv_selection_edit` (F30), migracja `0432_cv_selection_edit_ai_key` z lustrem
w `entrypoint.sh` (sama wartość enumu i wiersz ustawień — bez zmian tabel).

## Decyzje przyjęte domyślnie (do wiadomości Artura)

| Sprawa | Przyjęte | Dlaczego |
|---|---|---|
| Model | Sonnet 5 (zapas Haiku) | Redaguje tekst, który pisał generator na Sonnecie; recenzent przy „Zapisz” to Luna i ma być innym modelem. Przejście na tańszą Lunę wymaga pomiaru na fragmentach z produkcji |
| Zakres zaznaczenia | Jeden akapit albo punkt | Stanowisko, firma i lista technologii mają zapis, z którego składa się Word; zaznaczenie przez kilka punktów — poza PR 3 |
| „Na angielski” w polskim CV | Działa, z uwagą na karcie | Etykiety szablonu i klauzula zostają po polsku; całe CV PL→EN to PR 4 |
| Menu „AI” w pasku | Dodane (nie było na makiecie) | Dymek nad tekstem jest niewygodny z klawiatury i na telefonie |
| Nieudana kontrola | Brak propozycji, powód na karcie | Propozycja z niesprawdzonym faktem nie powinna dać się przyjąć jednym kliknięciem |
| Dymek | Własny, bez `BubbleMenu` Tiptapa | Okno edytora jest modalne; element doczepiony do `body` byłby nieklikalny. Bez nowych zależności |
| Numer strony źródła, podświetlenie w notatkach | Odłożone | Odczyt oryginału nie ma granic stron; „Notatki” nie mają wyszukiwania |
| Edytor wyniku generatora | Bez AI na zaznaczeniu | Nie ma tam rekrutacji ani źródeł do sprawdzenia propozycji |
| Miara przyjęć | Jeden wpis na zamówienie propozycji (akcja, status, powód) | Bez osobnej trasy „przyjęto”; da się policzyć odmowy i ich powody |
| Wymaganie rekrutacji w tłumaczeniu | Zwykłym słowem — uwaga na karcie; jak nazwa, której nie było — odmowa | „mikroserwisów” → „microservices” to przekład, „…and Kafka” to dopisana technologia. Skutek uboczny: „metodyce zwinnej” → „Agile” też jest odmową |
| Kwoty w „Rozwiń z oryginału” | Nigdy nie są dopisywane | Stawka kandydata z notatki nie może trafić do CV dla klienta; budżet projektu rekruter wpisze ręcznie |
| Rola nieustalona | Propozycja bez plakietki, z uwagą | Na CV „blind” z powtórzoną nazwą stanowiska nie zgadujemy, z której roli jest cytat |

## Przeglądy przed PR-em (13.10.2026)

Trzy niezależne przeglądy (bezpieczeństwo, TypeScript, Python), tylko blokery.
Każda poprawka ma test, który przed nią padał.

| Przegląd | Znalezisko | Poprawka |
|---|---|---|
| Bezpieczeństwo | „Rozwiń” dostawało notatki ze stawką, red flags i motywacją z karty rekomendacji i mogło je zacytować do CV | Notatki bez pól handlowych karty (`CV_HIDDEN_FIELDS`); propozycja nie doda odnośnika ani adresu spoza źródeł |
| TypeScript | „Przyjmij” na zatwierdzonym CV zakładało szkic i gubiło propozycję | Kontroler nie zeruje się w trakcie przyjmowania; ponowne sprawdzenie zakresu po założeniu szkicu |
| TypeScript | Escape w karcie zamykał i zapisywał cały edytor | Okno poznaje kartę po `data-cv-ai-card` |
| Python | Stawka nadal przechodziła: cytat ucięty za słowem „Stawka”, kwota bez tego słowa | Cytat z kwotą nie jest źródłem, ocena całego zdania źródła, zakaz dopisania kwoty (`amount`) |
| Python | Tłumaczenie odrzucało „500 000” → „500,000”, „major”, „microservices” | Separator tysięcy, dokładne formy miesięcy, wymaganie zwykłym słowem jako uwaga |
| Python | Plakietka „Zgodne ze źródłem” bez ustalonej roli; pierwsza rola o tej samej nazwie brana za własną; cytat przez granicę ról | Rola tylko jednoznaczna (firma, nazwa, lata), bez niej brak plakietki i uwaga; cytat z nazwą innego pracodawcy odrzucony |
| Python | Znaki niewidoczne i litery innego alfabetu chowały wymaganie; NUL i połówka pary zastępczej psuły zapis i odpowiedź | `clean_markup` je wycina, `_odd_character` odrzuca |

Drobniejsze, naniesione przy okazji: limit `previous` równy limitowi propozycji,
akapit z dosłownymi `**` dostaje powód zamiast błędu, karta przewija się do
widoku, `pointercancel`, odpowiedź modelu z listą zamiast tekstu to
„niedostępne”, limit odpowiedzi 1500 tokenów (700 ucinało JSON długiej
propozycji), rozwinięcie bez zmian mówi „nie ma na czym oprzeć”.

Znane ograniczenia kontroli (nie blokują, rekruter widzi „było / będzie”):
fakty zapisane słownie („pięciu zespołów”), zamiana miejscami liczb, które są
we fragmencie, zaprzeczenie, słowa z wielkiej litery po dwukropku i w nawiasie,
tolerancja odmiany („Java” ~ „JavaScript”), w rozwinięciu — twierdzenie małymi
literami niezwiązane z cytatem.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Kontrola propozycji | zielone lokalnie | `tests/test_cv_selection_ai.py` (63): nowe fakty, odmiana, cytaty, inna rola, stawka i kwoty, tłumaczenie, znaki niewidoczne, koszt |
| Wywołanie modelu | zielone lokalnie | model poza transakcją, awaria = „niedostępne”, bez klucza i z wyłącznikiem bez wywołania, prompt nie daje się rozerwać danymi |
| Regresja „Ułóż w zdanie” | zielone lokalnie | `tests/test_recommendation_card_assist.py` — `phrase_guard` bez zmian zachowania |
| Klucz AI i migracja | zielone lokalnie | rejestr modeli, ustawienia, lustro enumu w `entrypoint.sh` (76 testów) |
| Trasa | schemat lokalnie, reszta w CI | granice żądania bez bazy; pełny przebieg (brak zapisu w szkicu, ślad bez treści, 404, 422) wymaga Postgresa |
| Uprawnienia | zielone lokalnie | `authz_golden/cv_editor_ai.json` — ten sam wzorzec co `qc/transform`; strażnicy tras |
| Logika edytora | zielone lokalnie | `lib/__tests__/cv-editor-ai.test.ts` (20) na prawdziwym edytorze: co wolno zaznaczyć, zakres czekający, przyjęcie, cofnięcie |
| Dymek, karta, menu | zielone lokalnie | `CvEditorSelectionAi.test.tsx`, `CvAiProposalCard.test.tsx` (6, w tym uwaga serwera przy propozycji) |
| Okno i źródła | zielone lokalnie | testy okna (25), `CandidatePreviewPane.test.tsx` (26, w tym wyszukanie zlecone z zewnątrz) |
| Harness | zielone lokalnie | `cv-editor-harness.test.tsx` (10): obieg bez sieci, stan `aidown`, wynik generatora bez AI |
| Przeglądarka | częściowo | obieg na poziomie DOM w harnessie (dymek w kolumnie kartki, karta, „Przyjmij”, cofnięcie, klauzula bez dymka) |

## Niepotwierdzone

- **Wygląd i położenie dymka oraz karty** przy 1280×720, 768 i 390 px — panel
  przeglądarki był ukryty, a Chrome niepodłączony, więc nie ma zrzutów.
  Położenie liczy `coordsAtPos`, czego jsdom nie sprawdzi.
- **Jakość propozycji prawdziwego modelu** i odsetek odmów kontroli — testy
  podmieniają model. Po wdrożeniu: wpisy `cv_selection_ai` w `activities`
  (`details->>'status'`, `details->>'reason'`).
- **„Pokaż w oryginale” na prawdziwym PDF-ie** — wyszukiwarka może nie trafić
  w cytat złamany między wierszami; karta pokazuje pełny cytat niezależnie.
- **Uwaga „nie udało się ustalić stanowiska”** — jak często wraca na
  prawdziwych CV (zwłaszcza „blind”); po wdrożeniu widać to tylko pośrednio,
  bo wpis użycia nie zapisuje tej uwagi.

## Świadomie poza zakresem

- Zaznaczenie przez kilka punktów, polecenie własnymi słowami dla całego CV
  i przeniesienie zmian PL→EN (PR 4); historia wersji i powrót pliku Word (PR 5).
- Prompty poprawek QC i przeglądu DZ nadal wklejają dane bez ogrodzenia —
  zgłoszone jako osobne zadanie.
- Propozycje poprawek w oknie QC (`qc/fixes`) nadal czytają notatki z polami
  handlowymi karty rekomendacji i oceniają stawkę po samym cytacie — ta sama
  przyczyna co wyżej, ale zmiana zmieniłaby wyniki QC; do decyzji Artura.
