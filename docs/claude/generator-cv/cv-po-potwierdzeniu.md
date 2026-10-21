# CV po potwierdzeniu — bez auto-CV po „Zweryfikowany” (21.10.2026)
<!-- indeks: trzy potwierdzenia w karcie, plik z kopii „Oryginał CV”, `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION` -->

Zgłoszenie zespołu z 21.10.2026: „jak usunąć CV, które wygenerowało się z błędnego
pliku, i wygenerować poprawne?” oraz „CV generuje się samo po kliknięciu
»Zweryfikowany«, zanim dodam notatkę, a system sam wybiera plik i nie da się
tego cofnąć”. Makiety: https://claude.ai/artifact/3Q8bnMiqoAxbp6PmvZE8E7.
Decyzje Artura 21.10: CV powstaje dopiero po potwierdzeniu pliku, odpowiedzi
i dodatkowych notatek; domyślny plik = kopia „Oryginał CV” rekrutacji.

## Co było źle (stan do 21.10)

- Karta „CV do klienta” pokazywała „Plik CV: …” z kopii etapu, a generator
  brał główne CV profilu, bez niego najnowszy PDF/DOC/DOCX — także
  „nieaktualny” i z kwarantanny tożsamości. Rekruter nie widział, z czego
  powstało CV, a „Wygeneruj ponownie” brało ten sam plik.
- Pole „Notatki ze screeningu” (dopisek do CV, gdy pytania czegoś nie
  obejmują) było tylko w oknie generatora na profilu, a auto-CV ruszało zaraz
  po ruchu karty.

## Reguła

- **Ruch na „Zweryfikowany” nie generuje CV.** `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION`
  (domyślnie `False`) w `cv_auto_generate._enqueue`: po ruchu zostaje tylko QC
  istniejącego CV pary (`qc_after_attach`), bez wpisów w „Pracy w tle” i bez
  dzwonka „Automat nie zrobił CV”. `True` = tryb 21.09–21.10 (testy automatu
  włączają go jawnie fixturą). `CV_AUTO_GENERATE_ON_VERIFIED` dalej wyłącza
  całość, także QC po ruchu.
- **Trzy potwierdzenia w karcie** (`recruitment/CvGenerateConfirm.tsx`, reguły
  `lib/cv-generate-confirm.ts`): plik CV, odpowiedzi ze screeningu (podgląd
  treści z formularza, „Popraw w formularzu”), dodatkowe notatki do CV
  (zapis jako notatka rekrutacji przed generacją, jak w oknie generatora;
  „Nie mam nic do dodania”). Kolejność dowolna; „Generuj” po trzech. Zmiana
  pliku albo treści notatki po potwierdzeniu zdejmuje potwierdzenie.
  „Napisz od nowa” potwierdzeń nie ma — poprawia CV, które już powstało.
- **Plik domyślny = kopia „Oryginał CV”** (`GET …/cv/ai-sources`, `_cv_files`
  w `api/cv_ai_sources.py`): plik profilu o tym samym SHA co kopia etapu (także
  z wiersza sprzed ruchu karty). Bez kopii — główne albo najnowsze CV
  z pominięciem „nieaktualnych” i z kwarantanny. Odpowiedź niesie `cv_files`
  (wszystkie pliki CV osoby z `is_primary`, `outdated`, `stage_original`)
  i rekruter może wybrać każdy, także nieaktualny.
- **Po „Zapisz i przekaż dalej”** blok postępu mówi „CV czeka na Ciebie —
  potwierdź niżej, z czego je zrobić”, panel potwierdzeń otwiera się sam (raz
  na przekazanie), karta nie odpytuje serwera o auto-CV.
- Awaria `…/ai-sources` nie blokuje: lista plików z `cv-sources` generatora,
  krok odpowiedzi mówi „nie udało się sprawdzić”, potwierdzenia działają.

## Czego nie zmienia

- Inne wejścia do generatora (okno z profilu, dok, okno QC) — mają własny wybór
  pliku i pole notatek.
- Automat przy ruchu z włączoną flagą dalej bierze pierwszy plik z listy
  generatora (`sources[0]`).

Testy: `backend/tests/test_cv_confirm_before_generate.py`,
`frontend/src/lib/__tests__/cv-generate-confirm.test.ts`,
`CvToClientCard.test.tsx` (sekcje „brak CV” i „po przekazaniu”), harness
`/preview/cv-to-client` (osoba „Po przekazaniu — potwierdź, z czego zrobić CV”).
