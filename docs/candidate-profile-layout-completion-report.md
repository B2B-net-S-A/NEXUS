# Profil kandydata: porządki D1–D8 i nowy układ E1–E6 — raport

Gałąź `claude/candidate-profile-layout`, 13.10.2026, jeden PR (decyzja Artura). Reguły:
`docs/claude/kandydaci-wyszukiwanie/ekran-kandydaci-i-profil-kandydata-uproszczenie.md` (sekcja „Profil”)
i `docs/claude/kandydaci-wyszukiwanie/imie-bez-dopiskow.md`.
Makiety i decyzje: porządki https://claude.ai/artifact/K45m9WCNz9ypfKBE87B9dv (D1–D8),
układ https://claude.ai/artifact/LPzm9GQGPQCrnWjdtg2WG9 (E1–E6).

## Skąd ta zmiana

Zgłoszenie Artura 13.10.2026: na profilu wiszą martwe przyciski („Wrzuć na targ”), strona jest przeładowana
i nieczytelna, a dopiski z Traffita („[ACTIVE] …”, „(zatrudniony) …”) dalej siedzą w imionach. Odczyt produkcji
(tylko liczby) potwierdził: 9 dopisków w imionach (jeden wpisany ręcznie w NEXUSIE tego dnia), osoba
z „(czarna lista)” w imieniu miała status „aktywny”, 21 osób ma w nawiasie drugie nazwisko, które musi zostać.
Doprecyzowania z 13.10: Head of Recruitment dalej widzi stawkę do klienta (D8), dopisek czarnej listy ustawia
status `blacklisted` (D6).

## Co się zmieniło

- **Pasek osoby (E1)** na całą szerokość: imię, pigułki (dostępność, zatrudnienie, kategoria, czarna lista,
  konflikt z klientem), kontakt z kopiowaniem, akcje w jednym rzędzie, menu „⋯” w grupach Kontakt · Dane.
  Lewa kolumna to „Do propozycji”: fakty w jednej linii, źródło jako kropka z okienkiem, ramka zatrudnienia,
  linia „N rzeczy do sprawdzenia z rozmowy”.
- **Martwe funkcje zdjęte (D1–D3):** Obserwuj i pasek przypiętych, Wrzuć na targ, Korekta imienia (czyszczenie
  e-maila i telefonu przejęło „Edytuj dane”), Generuj CV z menu, CloudTalk, status kontaktu, pasek ryzyka,
  Zaangażowanie, LinkedIn, Telefony. Trasy backendu zostały.
- **Dostępność zamiast „Aktywny/Pasywny” (D4)** — pigułka na profilu i w wierszu listy.
- **Przegląd (E2):** W skrócie + Ostatnio, 8 umiejętności, „Do zrobienia” (ruch po naszej stronie), pasek
  „Z nami”, ostatnia rozmowa.
- **Rekrutacje (E3, D5):** tabela „W toku” z rozwijanym wierszem (karta, feedback, ocena dopasowania),
  „Zakończone” otwarte, „Pasujące rekrutacje” liczone dopiero po „Pokaż”.
- **Notatki (E4):** filtry w dwóch grupach, oś czasu za przełącznikiem, miesiące, „Pokaż starsze”.
- **CV i Dokumenty osobno (E5, D7):** pliki w trzech grupach (CV wysłane klientom rozpoznawane też po kodzie
  rekrutacji), umowy bez `delivery_view` z `/history` bez kwot i bez fałszywego błędu.
- **Licznik „Rekrutacje” = procesy w toku (E6).**
- **Imię bez dopisków (D6):** jedna reguła `candidate_name_rules`; ręczny wpis → 422 przy polu, ścieżki
  automatyczne zdejmują po cichu, mapper Traffita tą samą funkcją; korekta 0436 (migracja + faza startu):
  najpierw pole (czarna lista → status, „active” → dostępność), potem tekst; bez notatek.
- **D8:** opis reguły i komentarz `BoardReader` uzgodnione, uprawnienia bez zmian.
- Harness `/preview/candidate-profile` z nowymi danymi i `?role=recruiter`; e2e pod sześć zakładek;
  przewodnik Jarvisa „Profil kandydata” i pułapka listy; inwentarz funkcji z powodami zdjęć.

## Jak sprawdzone

- Front: testy komponentów i kontraktu źródła profilu, nawigacji (aliasy `calls`, `cv`), inwentarza (parytet),
  list, plików, notatek, rekrutacji, faktów, pigułki, inicjałów, harnessów; `npm run type-check` po scaleniu
  z mainem.
- Backend bez bazy: `test_candidate_name_rules.py`, testy mappera Traffita (w tym: dane Traffita każdego
  przypadku z produkcji dają to samo imię, status i prowieniencję co korekta 0436), indeks CLAUDE.md,
  przewodniki i stemple; ruff na zmienionych plikach. Testy z Postgresem (korekta 0436, odmowa 422 w POST,
  PATCH, `/bulk-import`, `/from-cv`) — w CI.
- Niepotwierdzone lokalnie: wygląd harnessu i próg zakładek w `responsive-preview.spec.ts` (za mało miejsca
  na dysku na `next dev`) — sprawdza e2e w CI, a po wdrożeniu przeklikanie produkcji.

## Poza zakresem

- Szybki podgląd dalej pokazuje „Aktywny/Pasywny”; inicjały na Tablicy liczone inną funkcją.
- Backend martwych funkcji (przypięcia, zaangażowanie, przywracanie z Traffita, targ, `/calls`) został;
  alerty mailowe targu dalej wychodzą.
- „CV dla klientów” czyta `job_title`, którego lista wygenerowanych CV nie wysyła.
- `phase9-matching-ux.spec.ts` był rozjechany z UI już przed tą zmianą.
- `?documents=files` nie przewija do plików; flagi ambasadora i „otwarty na…” nie mają już edytora (przyjęte
  przy D3).
