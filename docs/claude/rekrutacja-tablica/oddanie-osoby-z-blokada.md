# Oddanie osoby z blokadą „Biorę”: Oddaj, Zwolnij, Poproś o oddanie
<!-- indeks: blokada 12 h, `/api/pipeline/claim/handover|release|request|request/answer`, `claim_request_*` (0777), trzy typy dzwonków, `ClaimHandover.tsx`, plakietka „Prośba · X” -->

Prośba rekruterki z 25.11.2026: przy „maszynowym” dodawaniu ma 15 osób
w „Nowych”, koleżanka zna jedną z nich i prosi, żeby się nią podzielić.
Rekruterka się zgadza, ale blokada trzyma osobę jeszcze 10 h, a zdjąć ją
mógł tylko admin, Delivery Lead albo Head of Recruitment. Decyzja Artura
z 25.11.2026: wszystkie trzy warianty z makiet
(https://claude.ai/artifact/RYsL53ApEcA3CMEcsCLrrd).

- **Oddaj…** (`POST /api/pipeline/claim/handover`): tylko osoba z aktywną
  blokadą wybiera aktywną osobę z rolą rekrutera (`pair_owner.can_own`).
  Ta dostaje pełne 12 h od teraz (`set_claim`), kartę, filtr „Kto dodał”
  i umówiony telefon (`screening_calls.follow_claim`), a także dzwonek
  `candidate_claim_handover`. Rekrutacje widzi każdy rekruter
  (`recruitment_access`), więc osobnego sprawdzania zespołu nie ma.
- **Zwolnij** (`POST /api/pipeline/claim/release`): `claimed_until` = teraz,
  `claimed_by_user_id` zostaje. Karta wygląda jak po upływie 12 h: imię
  zostaje, „Biorę” może kliknąć każdy, a „Biorę” nie liczy się jako
  przejęcie. Gdy ktoś prosił, dostaje dzwonek „zwolnił(a) osobę”.
- **Poproś o oddanie** (`POST /api/pipeline/claim/request`, powód 3–300
  znaków): kolumny `claim_request_user_id/_reason/_at` na procesie (0777).
  Jedna prośba naraz (druga osoba dostaje 409 z imieniem proszącej).
  Prośba obowiązuje tylko przy aktywnej blokadzie kogoś innego
  (`candidate_claim.pending_request`), a każda nowa blokada i zwolnienie ją
  kasują. Osoba z blokadą odpowiada `POST …/request/answer` (`accept`):
  „Oddaj” idzie drogą „Oddaj…”, „Zostaw” zostawia blokadę i dzwoni do
  proszącej.
- **Dzwonki:** trzy typy (`candidate_claim_handover`, `candidate_claim_request`,
  `candidate_claim_request_answer`), bo `ix_notif_dedup_daily` puszcza jeden
  dzwonek dziennie na typ i proces. Przy jednym typie „zostawia u siebie”
  zjadało późniejsze „oddał(a) Ci osobę” tego samego dnia.
- **Front:** `ClaimHandover.tsx` w wierszu „Prowadzi” (`PairOwnerLine`) i pasek
  prośby pod nim. Osoba z blokadą ma na karcie „Prośba · imię” zamiast
  „Twój · N h” (ton `wait`), bo przy 15 kartach sam dzwonek łatwo przeoczyć.
- **Bez zmian:** „Przejmij” admina, DL i HoR, Liga, cele i premie (liczą się
  jak przy „Biorę”, `biore-zmienia-osobe-karty.md`) oraz przypisanie
  „Prowadzi” na stałe u admina i HoR.
