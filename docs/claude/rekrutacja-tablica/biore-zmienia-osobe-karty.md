# „Biorę” zmienia osobę karty i filtr „Kto dodał”
<!-- indeks: `taken_by_*` na Tablicy, ostatnia osoba z „Biorę” do pierwszej weryfikacji, karta, filtr, „kto ma ruch”; Liga i premia bez zmian -->

Prośba rekruterki z 27.10.2026: wzięła „Biorę” ludzi, których dodał kolega,
żeby do nich zadzwonić, a potem nie mogła ich znaleźć na Tablicy z 38 osobami
w toku. Karta dalej pokazywała dodającego, a filtr „Kto dodał → Ty” miał 0.
Decyzja Artura z 27.10.2026 (wariant A z makiet
https://claude.ai/artifact/E2oxhWSM3fJ8SF3SycicNB, karta zostaje u biorącej
osoby także po 12 h).

- **Serwer:** Tablica (`GET /api/pipeline/kanban/{job_id}`) zwraca
  `taken_by_user_id` i `taken_by_name`, czyli ostatnią osobę z
  `recruitment_processes.claimed_by_user_id`, także po wygaśnięciu blokady.
  Pola znikają po pierwszej weryfikacji pary, a przy koncie nieaktywnym nie ma
  ich wcale (`candidate_claim.claim_state`). Blokada 12 h działa jak dotąd:
  `claim_user_*` i `can_take` są tylko przy aktywnej.
- **Kto jest w `claimed_by_user_id`:** osoba z „Biorę”/„Przejmij”/„Dzwonię”,
  pierwszy zapis formularza screeningu, ręczne dodanie (to ta sama osoba, co
  dodająca) i właściciel linku przy zgłoszeniu z linku. Ruch poza „Nowych”
  i „Screening” czyści pole (`recruitment_process_commands`).
- **Front:** w „Nowych” i „Screeningu” karta pokazuje osobę, która wzięła
  (`cardOwner`, rola `taken`). Dodającą widać w dymku karty. Filtr „Kto dodał”
  i kolejka panelu liczą ją zamiast dodającej (`board-added-by.adderId`), więc
  „Ty” pokazuje osoby wzięte i dodane przez patrzącego. Dół karty („kto ma
  ruch”) też należy do niej (`recruiterSideWho`).
- **Kolejność:** „Prowadzi” (admin/HoR) > osoba z „Biorę” > dodająca. Od
  „Zweryfikowanego” w prawo jak dotąd: osoba, która zweryfikowała.
- **Bez zmian:** Liga, cele, premie, „Moi ludzie”, Hall of Fame i Insights.
  „Biorę” ich nie przenosi, bo to jedno kliknięcie przy telefonie, a
  przypisanie prowadzącego zostaje u admina i HoR
  (`prowadzi-przypisanie-osoby.md`). Wariant „Biorę = Prowadzi na stałe” był
  na makietach i został odrzucony.

## Ruch karty „System” do „Screeningu” = „Biorę” (28.10.2026)

Zgłoszenie rekruterki z 28.10.2026: przeciągnęła osobę od „Nowi na 20”
z „Nowych” do „Screeningu”, a karta dalej pokazywała „System” i nie było jej
pod „Kto dodał → Ty”. Decyzja Artura z 28.10.2026 (wariant A z makiet
https://claude.ai/artifact/7cvyoGQuvbJKv7f76bYtq2):

- Ruch człowieka (nie integracji) z „Nowych” do „Screeningu” karty **bez
  osoby** — od systemu albo bez osoby dodającej, bez „Prowadzi” i bez nikogo
  w `claimed_by_user_id` — działa jak „Biorę”: przesuwający trafia do
  `claimed_by_user_id`, rusza blokada 12 h, a karta, filtr i „kto ma ruch”
  pokazują jego (`candidate_claim.take_unowned_on_screening`, wołane
  z `/move` i `/bulk-move`).
- Karta dodana przez człowieka zostaje u niego także po 12 h. Kto chce ją
  wziąć, klika „Biorę”. Odrzucone: „każdy ruch przepisuje kartę” (DL/HoR
  porządkujący Tablicę zabierałby ludzi rekruterom) i sam dopisek
  „przeniosła” (filtr „Ty” dalej by jej nie pokazał).
- Karty przeniesione przed zmianą: jednorazowo
  `scripts/system_card_screening_backfill.py` (podgląd, `--apply`) daje im
  autora ruchu do „Screeningu” z blokadą liczoną od tamtego ruchu, więc nikt
  nie dostaje świeżej blokady.

## Od „Zweryfikowanego” filtr liczy osobę, która zweryfikowała (29.10.2026)

Zgłoszenie rekruterki z 29.10.2026: w rekrutacji Nordei w „Wysłane do Cpro”
cztery karty miały jej imię (to ona je zweryfikowała), a „Kto dodał → Ty”
zostawiał jedną. Dwie osoby dodał kolega, jedną silnik „Nowi na 20”. Karta
od 20.10.2026 pokazuje od „Zweryfikowanego” w prawo osobę, która
zweryfikowała (`cardOwner`), a filtr dalej liczył dodającą.

- Filtr, menu i kolejka panelu (`board-added-by.cardPerson`) idą za kartą:
  „Prowadzi” > „Biorę” (tylko w „Nowych” i „Screeningu”) > osoba, która
  zweryfikowała (od „Zweryfikowanego”, `verified_by_id`) > dodająca. Osoba
  od systemu po weryfikacji człowieka nie jest już „System”.
- Kolumnę karty filtr dostaje z Tablicy (`withAddedByFilter`, klucz kolumny
  z `foldBoardColumns`) albo z `peopleInProgress` (`board_column`). Karta
  „Poza szablonem” nie ma kolumny i liczy się jak przed weryfikacją.
- Bez zmian: Liga, premie i „Moi ludzie” liczą jak dotąd (pierwszy
  weryfikujący i tak jest tam osobą pary, `prowadzi-przypisanie-osoby.md`).
