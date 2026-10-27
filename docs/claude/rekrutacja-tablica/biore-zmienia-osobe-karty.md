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
