# Przygotowanie rekrutera — trzeci prep przed Prepem 1 (F3, 0772, 24.11.2026)
<!-- indeks: `prep_no` 0, krok `prep0`, opcjonalne na start (bez zadań, plakietek i dzwonków o braku), zaproszenia „(spotkanie 1–3)”, nagrywane bez oceny do F4, rekruter domyślnie na Prepie 1, `prep_labels` / `lib/prep-label.ts`, pułapki „0 to fałsz” -->

Decyzje Artura z 24.11.2026 (F3 planu „Fundamenty prepa i specyfika klientów”;
fundamenty: `fundamenty-prepa-przygotowanie-rekrutera.md`, specyfika:
`klienci/specyfika-na-prep-w-karcie-klienta.md`). Makiety ze stagingu:
https://claude.ai/artifact/WXRdAMzdJjZEGFnpkHRjRB (prywatny).

Przed rozmową u klienta są trzy rozmowy z kandydatem (wiadomość Artura do DL-i
z 11.11.2026): **Przygotowanie** prowadzi rekruter (fundamenty i specyfika
klienta), **Prep 1** prowadzi Delivery Lead razem z rekruterem (wymagania
rekrutacji, braki po przygotowaniu), **Prep 2** to follow-up rekrutera jak
dotąd. Przygotowanie dochodzi obok Prepu 2, nie zastępuje go.

- **Numer 0, nie przenumerowanie.** `prep_meetings.prep_no` przyjmuje 0, 1, 2
  (migracja 0772; lustro w `entrypoint.sh` to blok DROP+ADD w
  `_CONSTRAINT_STATEMENTS`, bo `CREATE TABLE` zostaje lustrem 0370 —
  `test_prep_preparation_schema.py`). Prep 1 i 2 zachowały numery, więc stare
  prepy, oceny, notatki „Prep N” i ustawienia ocen (`prep1`/`prep2`) się nie
  zmieniły. Krok cyklu to `prep0` przed `prep` (`STEP_KEYS`), wpis agendy
  `prep0`.
- **Zero to nie „brak”.** Prep spoza NEXUSA ma `prep_no = None`, a
  Przygotowanie `0`. Każde sprawdzenie numeru prepu albo `ordinal` pisz
  `is not None` / `!= null` — `if p.prep_no:` traktowało 0 jak prep
  z Outlooka i Przygotowanie zajmowało miejsce Prepu 1 (zadanie „brak Prepu 1”
  znikało). To samo z trójnikami `=== "prep2" ? 2 : 1` — numer z klucza kroku
  bierze `prepNoOfStep` (`lib/prep-label.ts`).
- **Nazwy:** w NEXUSIE „Przygotowanie → Prep 1 → Prep 2”; grupa kolumn
  Kalendarza to „Prepy · rekruter i DL”, bo „Przygotowanie” jest nazwą
  kolumny. „Przygotowanie” jest rodzaju nijakiego, więc zdania z prepem
  składają `services/prep_labels.py` i `lib/prep-label.ts` („Przygotowanie
  zaplanowane”, „Zaplanuj przygotowanie”, „brak przygotowania”), nie szablon
  `f"Prep {n}"`. Pasek kroków w doku ma 8 kresek („Przyg.”).
- **Zaproszenie kandydata** numeruje spotkania po kolei: „Przygotowanie do
  spotkania z Klientem X - Imię (spotkanie 1)”, treść „pierwsze / drugie /
  trzecie spotkanie przygotowujące” (`prep_invitation.meeting_number`). Numer
  liczy się przy zakładaniu: Prep 1 ma „(spotkanie 2)”, a Prep 2 „(spotkanie
  3)”, gdy w rundzie jest Przygotowanie; bez niego tytuły jak dotąd (Prep 1 bez
  numeru, Prep 2 „(spotkanie 2)”). Przygotowanie dodane do już zaplanowanego
  Prepu 1 zostawia jego tytuł bez numeru — odrzucone: „Nazwy z 11.11 wszędzie”
  (Prep właściwy / Follow-up) i „Wstępne przygotowanie”.
- **Opcjonalne na start.** Krok, planowanie i zaproszenie są, ale nie ma zadań
  („Przygotowanie bez terminu”, także `prep_late`, `prep_unrecorded`),
  plakietek Tablicy, kolejki `prep_attention` ani przypomnień o braku.
  Niezaplanowane Przygotowanie nie jest krokiem „bieżącym”, więc karta stoi
  dalej na Prepie 1 (`_optional_todo` w `interview_cycle.py`). Po starcie
  Prepu 1 bez niego krok jest szary „pominięte”. Dzwonki o zmianach
  ZAPLANOWANEGO przygotowania (zaplanowane, przełożone, odpowiedź kandydata,
  brak odpowiedzi dobę przed) działają jak przy prepach. O obowiązku Artur
  zdecyduje po pomiarze w F5 — odrzucone: „wymagane do Prepu 1” i „jak Prep 2
  z wyjątkiem”.
- **Okno „Umów rozmowę i prepy”** ma trzy wiersze, a polecana godzina
  przygotowania jest zaznaczona od razu („zaproś na prepy (3)”, decyzja
  Artura); rekruter może dać „Zaplanuję później”. Wcześniejszy prep wybiera
  godzinę pierwszy, późniejszy omija jego godzinę; przygotowanie po Prepie 1
  daje ostrzeżenie, nie blokadę. Serwer podpowiada przygotowanie jak
  najwcześniej (dwa dni robocze przed rozmową) i przed zaplanowanym Prepem 1
  (`prep_availability.suggest`, `end_by`), a Prep 1 po nim (`not_before`).
- **Prowadzi rekruter kandydata** (podpowiedź jak przy Prepie 2,
  `suggestion_summary[0]`). Na Prep 1 rekruter kandydata jest zaproszony od
  razu (`defaultInviteeIds`, można go usunąć), bo Prep 1 prowadzi DL razem
  z rekruterem.
- **Nagrywamy jak prepy:** ta sama informacja o nagrywaniu w zaproszeniu,
  transkrypt pobiera pętla `teams_prep_transcripts`. Oceny przygotowania nie
  ma do F4: `review_prep` dla prepu 0 zapisuje tylko notatkę z faktami
  („NEXUS jeszcze nie ocenia przygotowania”), bez modelu i bez
  `prep_reviews`, a krok mówi „nagrane · oceny przygotowania jeszcze nie ma”.
  Ocena według listy Prepu 1 byłaby fałszywa (inne tematy, inny prowadzący).
- **Liczenie prepów:** „dwa prepy” w raporcie „Jakość prepów” i „bez słowa”
  w pominięciach Prepu 2 liczą tylko Prep 1 i 2 (`prep2_skips.not_preparation`),
  a wiersze organizatorów raportu pomijają Przygotowanie — doliczy je F5.
- **Dostęp** jak przy prepach (`CalendarWriteAccess` + `ensure_job_membership`);
  F3 go nie zmienia. Przejście ścieżki 24.11 na kopii (rekruter → kandydat →
  DL, role bez sekcji pipeline → 403): opis w PR-ze.
- **Dalej:** F4 ocena przygotowania (fundamenty, specyfika klienta, „kandydat
  umie”, warunek stop → dzwonek do DL-a), F5 raport „Jakość prepów”,
  przewodniki ekranów i stemple, decyzja o obowiązku.
