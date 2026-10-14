# Edytor CV 3 — PR 5: „Napisz od nowa” (14.10.2026)

Propozycja i makiety: https://claude.ai/artifact/1g1FJJ2TtojTJSFjmZQj5Z
(„Ekran 4” i „Ekran 5”). Kierunek D1–D6 i „bardzo, bardzo prosto” — decyzje
Artura z 14.10.2026. Reguła: `docs/claude/generator-cv/edytor-cv-pelny-ekran.md`,
sekcja „„Napisz od nowa””. Bazą jest PR 4 (asystent w kolumnie).

## Co było nie tak

- „Wygeneruj ponownie” nie przyjmowało uwagi („krócej, więcej o Kafce”).
  Zostawało wklejenie CV do ChatGPT.
- Nowa generacja nadpisywała niezatwierdzony szkic bez śladu. Ręczne
  poprawki przepadały, a powrót był możliwy tylko do ostatniej
  zatwierdzonej wersji.

## Co weszło

- **Pole „Co poprawić?” + „Napisz od nowa” w karcie.** Uwaga trafia do
  notatek rekrutacji („Uwaga do CV: …”, fakty z tego zdania stają się
  źródłem) i do generacji. Panel rusza sam, gdy nic nie czeka na decyzję.
- **„napisz od nowa: …” w asystencie** (podpowiedź „Napisz od nowa…”).
  Edytor zapisuje szkic, zamyka się, a uwaga trafia do karty.
- **Uwaga dla modelu.** `GenerateRequest.instruction` (do 300 znaków, bez
  stawek) zamrożona w źródle zadania. W promptach legacy_v7 trafia jako
  ogrodzone `<recruiter_instruction>` z regułą „forma i akcenty, nigdy
  źródło faktów”, w treści użytkownika; prompt systemowy bez zmian (cache).
- **Ręczne poprawki zostają.** `services/cv_rewrite_merge.py` porównuje
  szkic z generacją, z której powstał. Porównuje nagłówek, sekcje
  i stanowiska (po firmie i datach), sam tekst. Część poprawiona zostaje,
  usunięta nie wraca, dopisana stoi na swoim miejscu. Gdy nie da się tego
  rozpoznać, wchodzi cała nowa wersja i karta mówi to wprost.
- **Nic nie ginie.** Migawka szkicu przed każdą podmianą
  (`cv_stage_draft_snapshots`, migracja 0444 + lustro w entrypoint)
  i `POST …/cv/branded/restore-previous`. W karcie pasek „Nowa wersja CV.
  „X” zostało w Twojej wersji.” z przyciskiem „Wróć do poprzedniej”.

## Świadomie inaczej niż makieta

- Nowa wersja pojawia się w karcie, nie na otwartej kartce edytora.
  Podmiana treści pod otwartym edytorem z autozapisem to wyścig o wersję
  szkicu. Edytor zapisuje i zamyka się sam, a nowa wersja przychodzi po
  ok. 40 s.
- „Wygeneruj ponownie” zostaje w „⋯”, bo daje pełny panel ustawień.
- „Usuń najstarsze role” wpisuje się słowami, gdy jest podpowiedź
  „Napisz od nowa…” (cztery podpowiedzi, jak na makiecie).
- „Weź nową Logistykę”, czyli prośba o nową wersję jednej części, nie
  weszła. Kto chce całą nową wersję, przywraca ją w historii albo pisze od
  nowa bez poprawek.

## Testy

- Backend lokalnie, bez bazy:
  - scalanie (`test_cv_rewrite_merge.py`, 9): bez zmian, rola i sekcja
    poprawione, samo pogrubienie, rola usunięta, część dopisana, klauzula
    RODO, szkic nie z generatora, „wszystko inne”;
  - generator (`test_cv_generator_legacy_v7.py`, +3): ogrodzona uwaga za
    źródłami, prompt systemowy bez zmian, brak tagu bez uwagi, stawki
    wycięte;
  - lustro migracji 0444.
- Backend z bazą (CI): podmiana z `keep_edits` (zostaje „Beta”), „Wróć do
  poprzedniej”, migawka `restore`, 409 i 404, wzorzec authz nowej trasy.
- Frontend lokalnie:
  - karta: 51, w tym 4 nowe — pole → notatka + generacja z uwagą →
    `keep_edits` → pasek → „Wróć do poprzedniej”; brak rozpoznania; wejście
    z edytora; tylko odczyt;
  - hook asystenta: +2;
  - harness edytora: podpowiedź i zdanie;
  - harness karty: pełny przebieg bez sieci;
  - inwentarz: 343.
  - `npm run type-check` czyste.
- Zrzuty 1280×720 (Playwright, harnessy): karta z polem, karta po nowej
  wersji z paskiem, podpowiedzi asystenta. Pierwszy zrzut pokazał ucięty
  placeholder w wąskiej karcie i dwulinijkową podpowiedź pod każdą kartą.
  Placeholder skrócony do „Co poprawić?”, przykład w jednej linii.

## Przeglądy przed PR-em (Python, TypeScript, bezpieczeństwo)

Każdy błąd z testem, który padał przed poprawką:

- **„Wróć do poprzedniej” bez „anonimowe” i języka** (bezpieczeństwo,
  Python): migawka nie trzymała szablonu ani języka, więc CV z nazwiskiem
  mogło wrócić jako anonimowe. Migawka trzyma je teraz (kolumny w 0444).
- **Uwaga zamykała swoje ogrodzenie** (bezpieczeństwo): `recruiter_instruction`
  nie było na liście `prompt_fencing`; teraz `recruiter_*`.
- **Klucz stanowiska** (Python): wzorzec dat łapał „now” w „Snowflake” —
  rola lądowała w wyniku dwa razy; dwie role w tej samej firmie z tymi
  samymi datami po zmianie kolejności gubiły jedną. Daty = linia bez nazwy
  roli; duplikaty albo inny zestaw ról = „nie rozpoznano”.
- **Start przed regułą klienta** (TypeScript): mógł pominąć zgodę RODO
  i wymagane pola. Reguła w drodze jest teraz brakiem.
- **Start z domyślnymi sprzed polityki** (TypeScript): język i numer
  projektu z polityki nie trafiały do generacji. Start rusza przebieg później.
- **Ponowienie dopisywało notatkę** (TypeScript) i **druga generacja
  z edytora w trakcie pierwszej** (TypeScript) — poprawione.
- **Numer migracji**: #2227 (inna sesja) też ma 0444. Kto wchodzi drugi,
  przenumerowuje — sprawdzane przed zdjęciem draftu.

