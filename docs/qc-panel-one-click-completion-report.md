# Panel „Do poprawy” jednym kliknięciem — raport (wariant A, D1–D7)

Zgłoszenie rekrutera (17.10.2026): panel „Do poprawy” w edytorze CV zajmuje mało
miejsca i jest nieczytelny; QC ma mówić, co jest nie tak, i poprawiać jednym
przyciskiem; potrzebny przycisk „przepuść dalej mimo uwag AI”. Makiety
i decyzje: https://claude.ai/artifact/Y9XgB3H1iMS2f5WQYsHJyG. Artur: „Tak — buduj
wariant A z rekomendowanymi D1–D7, PR-y po kolei”. Reguły:
`docs/claude/generator-cv/edytor-cv-pelny-ekran.md`, sekcja „Panel »Do
poprawy« jednym kliknięciem”.

## PR 1 · układ, wiersze, odpowiedzi jednym kliknięciem

Co weszło:

- Asystent zwinięty do jednej linii pod listą (D1); rozwinięty zwija listę do
  paska z liczbami i „Pokaż listę”. Lista przy 1280 × 720: 511 px zamiast 205.
- Grupy po wadze (D2): „Blokuje wysyłkę”, „Do poprawy”, „Poprawione”, „Do
  decyzji · nie blokuje”. Wiersz = problem, podgląd zmiany, jeden przycisk;
  tytuł rozwija szczegóły i pokazuje miejsce na kartce.
- Zdanie AI w wierszu swojej uwagi (każde z „Dopisz”, „Edytuj zdanie”,
  „Odrzuć propozycję”, „Pokaż w CV”); osobnej sekcji „Propozycje AI”
  w edytorze nie ma.
- „Poprawione” z „Cofnij” (ostatnia poprawka, dopóki CV się po niej nie
  zmieniło) i „Cofnij wszystkie” po „Popraw wszystkie”.
- Treść spoza oryginału (D5): „Usuń z CV”, „Kandydat to ma” (notatka
  „Potwierdzone z kandydatem”), „Jest w oryginale” (pominięcie z fragmentem).
- „OK” / „Zostaw” przy uwagach generatora i kontroli AI — nowy powód `kept`
  (backend: `cv_finding_dismissals.REASONS`, `REASON_CHECKS` jako zbiory,
  `cv_editor_issues.dismiss` sprawdza powód względem źródła).
- „Przekaż mimo uwag…” w nagłówku blokad — ta sama akcja i ten sam warunek
  czekania co w stopce.

Przegląd (typescript-reviewer) znalazł 4 rzeczy, poprawione z testami:
pominięcie per rola przy blokadzie w kilku rolach, edycja i odrzucenie każdego
z kilku zdań AI (odrzucone wypada z „Popraw wszystkie”), `appliedActions`
z zakresem pogrubienia i terminem, przycisk w panelu czeka na asystenta.

Testy lokalne: lib `cv-editor-issues` 42, panel 42, modal (3 pliki), harness
29, inwentarz i okno QC — razem 616 zielonych; backend bez bazy:
`test_cv_finding_dismissals.py` (nowe testy powodu `kept`). Testy z bazą — CI.

## PR 2 · lata, tytuł, stawka i kontakt, zdanie z kontroli AI

Co weszło:

- Akcje `qc/transform` `years`, `title`, `strip_client_rules`, `remove_line`
  (`cv_qc.fix_years_html`, `set_title_html`, `strip_client_rules_html`,
  `remove_line_html`); `years` i `title` w „Popraw wszystkie” (D4).
- Przyciski w wierszach: „Zmień” (podgląd „Ponad 10 lat → Ponad 7 lat”),
  „Wpisz” (tytuł z rekrutacji), „Usuń stawkę” / „Usuń dane kontaktowe” przy
  blokadzie reguł klienta, „Usuń zdanie” przy kontroli AI.
- Wynik QC bez nowych pól — panel rozpoznaje uwagę po kluczu sprawdzenia, żeby
  nie zmienić skrótu przebiegów i czasu oczekiwania w kolejce DL.

Testy: backend bez bazy — 11 nowych w `test_cv_qc.py` (w tym liniowość
czterech operacji na wejściu kilkuset KB: < 0,4 s); front — lib 44, panel,
harness 30 („Usuń zdanie” na prawdziwym edytorze).

Przegląd (python-reviewer) znalazł 7 rzeczy, poprawione z testami na jego
przykładach: kwadratowe wzorce na surowych odstępach, liczba lat podmieniana
poza cytatem, sprzątanie bloków nietkniętych przez operację, luźna kwota
usuwająca treść („Moduł wynagrodzeń dla 250…”), kontakt zostający w linkach,
tytuł nadpisujący imię („Imię – Rola”), inna historia niż w uwadze QC. Przy
okazji: `_block_nodes` dla każdego bloku było kwadratowe (54 s) — węzły liczone
raz. Runda 2 przeglądu: kwadratowo przy wielu twierdzeniach o stażu
(323 s → 0,34 s; limit 10 na kliknięcie) i tytuł nadpisujący dopisek po
imieniu — teraz tylko układ generatora „Rola – Imię”. Znalezione poza zakresem: `rate_mentions` w QC używa luźnego `_AMOUNT`,
więc „Moduł wynagrodzeń dla 250 zleceniobiorców” bywa zgłaszany jako stawka
(blokada `client_rules`, której nie da się pominąć) — przycisk wtedy mówi
„W CV nie ma stawki…”; poprawka reguły QC to osobna decyzja (zmienia wynik QC).

## PR 3 · przepuszczenie idzie za CV (D6) i termin w zdaniu przez asystenta

- `cv_qc.follow_advisory_override` w `run_qc`: obejście doradcze dostaje
  odcisk bieżącego CV, gdy bieżące blokady są podzbiorem blokad z chwili
  obejścia (`blocking_keys`). `_override_applies` bez zmian — bramka ruchu,
  plakietka i przegląd DL czytają to samo co dotąd.
- „Usuń z CV” przy terminie w zdaniu: panel przekazuje prośbę asystentowi
  (`onAskAssistant`), zamiast kończyć komunikatem „usuń je w edytorze”.

Testy: bez bazy — 4 nowe w `test_fix48_ws11_qc_override_rule.py`; z bazą
(CI) — `test_advisory_override_follows_the_cv_until_a_new_blocker_appears`;
front — panel (przekazanie asystentowi), modal.

Przegląd (security-reviewer) znalazł blokadę: sesje mają `autoflush=False`,
więc bramka ruchu zaraz po przeliczeniu czytałaby stary odcisk — `flush()` po
podmianie. Do tego obejście idzie za CV tylko przy QC najnowszego wiersza etapu
pary. Ponowny przegląd: nic nie blokuje (skutek uboczny: plakietka może do
zapisu przebiegu przy zamknięciu edytora pokazywać obejście jako utracone —
błąd w stronę blokady).

## PR 4 · zgoda RODO w panelu, rola bez dat

- „Wgraj zrzut maila” w wierszu blokady `upload_consent` — do dokumentu
  generatora albo CV etapu (`consentTarget`, jak karta „CV do klienta”),
  potem QC od nowa.
- Wiersz „<rola>: brak dat” zamiast „Rola bez dat.”.
- Zmiana planu z makiet (D3 „daty przez asystenta”): asystent nie widzi
  oryginału, więc wpisywałby daty zgadnięte albo pytał. Bez przycisku;
  wpisanie dat kodem z odczytu oryginału czeka na decyzję.

Testy: lib (`consentTarget`), panel (zgoda: generator / kopia etapu, QC po
wgraniu; tytuł roli bez dat), inwentarz (`cv.editor-consent-upload-in-panel`).

## Poprawka po wdrożeniu PR 2 · lata kilku firm naraz (#2292)

Na produkcji (17.10.2026, f2d04f103) panel pokazał „Zmień” przy „3 lata w <A>
i <B>”, gdzie z dat roli w A wychodzi 0. Zera serwer nie wpisywał (przycisk
kończył się „nic do zrobienia”), ale „12 lat w A i B” przy 8 latach w A
dostałoby „8 lat w A i B”. Teraz `fix_years_html` pomija staż kilku firm naraz,
a panel daje „Zmień” tylko z podglądem i bez kilku firm (`yearsFixable`). Wynik
QC bez zmian — uwaga zostaje do decyzji. Czy QC w ogóle ma zgłaszać staż kilku
firm, gdy historia zna jedną, to osobna decyzja (zmiana reguły QC).

PR 3 w CI: `test_advisory_override_is_for_the_cv_it_was_made_on` kodował regułę
sprzed D6 — przepisany na „obejście kończy nowa blokada”
(`test_advisory_override_ends_when_the_cv_gets_a_new_blocker`).
