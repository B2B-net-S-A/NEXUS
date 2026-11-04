# Najlepsze 40 zamiast progu 70% i „Ukryci przez »musi mieć«” w „Propozycjach z bazy” (28.10.2026)

Zgłoszenie rekrutera z 28.10.2026 (rekrutacja IAM z krytyczną „SailPoint
IIQ”): „Propozycje z bazy” nie pokazały 7 osób, które znalazł ręcznie
i uznał za bardzo dobre, więc pobierał CV hurtem i oceniał je w prywatnym
czacie. Odczyt produkcji: na 38 rekrutacjach z przeglądem ludzie dodali
ręcznie 373 osoby — 22% było w propozycjach, 61% miało 50–70%, 17% ukryła
bramka „musi mieć”. Z przedziału 60–70% wyszło 20 wysłanych CV, z ≥ 70% 13.
Decyzja Artura: warianty A i B z makiety
https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS (słownik „IdentityIQ = IIQ”
to osobny PR, „Oceń z AI” — kolejny).

## B. Najlepsze 40

- **Nocny przegląd publikuje wszystkich od progu plus najlepszych spod
  progu do łącznie `AUTO_FULL_REVIEW_MIN_COUNT` (40)**
  (`auto_full_review.publish_run_proposals`). Od progu nikogo nie obcinamy
  (limit 60 zdjęty 07.10.2026 zostaje zdjęty). Dopełnienie bierze tylko
  dopuszczonych i zmierzonych, z tą samą regułą „musi mieć”
  (`is_good_match`) i bez innej roli; osoba pominięta albo dodana w tej
  rekrutacji nie zajmuje miejsca. `0` = sam próg.
- **„Spod progu” nie ma w zapisie** — liczy się przy odczycie z wyniku:
  `job_proposals.meets_threshold` (para z innym źródłem niż `full_base`
  zawsze „od progu”). Próg = `proposal_threshold` (panel „Ranking
  kandydatów”, bez zapisu env) — ten sam, którym publikuje przegląd.
- **Liczby zostają przy osobach od progu:** poranny dzwonek „Do przejrzenia”
  (`fresh_open_pairs`), licznik listy rekrutacji i skrót DL-a
  (`open_counts_for_jobs`), kafel i zakładka (`open_split_counts.base`,
  w oknie `isBelowThreshold`), „najlepsze 3” (`top_open_by_job`) i pasek
  etapów (`visibleCount`). Nowy czytelnik skrzynki, który coś LICZY, bierze
  `meets_threshold` — inaczej każda rekrutacja miałaby co rano 40 osób.
- **Lista ich pokazuje:** `GET …/proposal-inbox` niesie `below_threshold`
  przy osobie i `threshold`; serwer stawia ich za wszystkimi od progu,
  a okno pod separatorem „Poniżej 70% · N osób”
  (`proposals-below-threshold`). Osoba z adoptowanego przeglądu (`run`) jest
  „spod progu” po wyniku; podobne projekty i rekomendacje — nigdy.
- **Wygaszanie bez zmian w regule:** `expire_full_base` gasi osobę, której
  najnowszy przegląd nie zaproponował; dopełnieni dostają `run_id` przeglądu,
  więc wygasają dopiero, gdy wypadną z najlepszych 40.

## A. Ukryci przez „musi mieć”, choć w CV jest coś bliskiego

- **Źródło:** najnowszy przegląd automatyczny z wynikami, wiersze
  `eligible = false` z `missing_must` (`services/hidden_by_critical.py`,
  `GET …/proposal-inbox/hidden-by-critical`). Brakujące krytyczne liczy ta
  sama bramka na wymaganiach ZAMROŻONYCH w przeglądzie — wariant dopisany
  dziś nie zdejmuje nikogo z sekcji do następnej nocy.
- **Bliskie słowo** (`close_words`): człon nazwy krytycznej albo słowa
  wiersza, sam niebędący pełną nazwą, ≥ 4 znaki, bez ogólnych słów
  („Server”, „Cloud”) i parasoli producentów („Microsoft”, „Oracle”).
  Krytyczna z jednego słowa nie ma bliskich słów. **Osoba bez śladu
  (całe słowo w profilu, CV albo notatce-dowodzie) nie wchodzi** — ani ukryta
  innym powodem, pominięta, z żywą propozycją, w rekrutacji czy na czarnej
  liście.
- **Cytat to podgląd, nie zapis:** `must_text_evidence.word_snippet`
  (do 40 znaków) przy każdym odczycie; do `job_proposals.evidence` nie trafia.
- **Wiersz jak propozycja:** wynik „?”, „+ Dodaj” (`proposals/bulk` ze
  źródłem `proposal_inbox` przez `useJobProposals.addToJob(…,
  { unlistedSource })` — droga z `sciezka-kandydata-przekazania-zweryfikowany-jeden.md`),
  „Pomiń” (powód, trwałe jak w skrzynce), podgląd. Przy więcej niż 3 osobach
  sekcja startuje zwinięta („Pokaż wszystkich N”). Awaria = komunikat
  z „Ponów”, pusta odpowiedź = brak sekcji.
- **„„SailPoint” = SailPoint IIQ”** (`HiddenByCriticalSection`,
  `lib/critical-variant.ts`): dopisuje słowo do wiersza krytycznej TYM SAMYM
  zapisem co „+ lub” — `PUT …/champion-profile` z całym `stack`
  i `expected_profile_hash`, po potwierdzeniu `useConfirmV2`. Bez nowej trasy.
  Przycisk widzi ten, komu wolno ten zapis (`can_add_variant` =
  `job_edit_level`: rekruter, DL, każda rola wewnętrzna; „Automatyzacje” —
  nie). Słowo idzie w najczęstszej pisowni z CV; dopisane = „· od następnej
  nocy” (`in_row`).
- Harness/testy: `tests/test_hidden_by_critical.py`,
  `tests/test_auto_full_review.py` (najlepsze N),
  `AddCandidatesPanel.test.tsx` (separator, sekcja, wariant).
