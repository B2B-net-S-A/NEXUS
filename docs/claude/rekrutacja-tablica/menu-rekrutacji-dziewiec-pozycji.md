# Menu „⋯” rekrutacji — dziewięć pozycji, puste kolumny zawsze widoczne
<!-- indeks: bez dubli nagłówka i okna „Zlecenie”, podmenu „Dodaj kandydatów”, Tablica bez przełącznika pustych kolumn -->

Decyzja Artura z 25.10.2026 (makiety ze stagingu:
https://claude.ai/artifact/Vd1qKUVRy1yGTAgXb7ofz6). Menu „⋯” w nagłówku
rekrutacji (`JobDetailCompactHeader`) miało 17 pozycji w dwóch grupach.
Artur: „za dużo elementów, ciężko się połapać”. Przy 1280 × 720 trzy ostatnie,
w tym „Zamknij rekrutację…”, były pod krawędzią ekranu.

## Co jest w menu

Kolejność, oddzielone kreskami, bez nagłówków grup:

1. **Dodaj kandydatów ›** — podmenu: Po nazwisku, Z pliku CV, Z moich ludzi,
   Przeszukaj całą bazę (AI). Brak prawa dodawania = brak pozycji.
2. Zlecenie — skrót · Edytuj Profil Championa · Edytuj dane rekrutacji · Pliki (N)
3. Kopiuj link do rekrutacji · Link do zgłoszeń kandydatów
4. Narzędzia AI (administrator)
5. Zamknij rekrutację… (na czerwono)

Przy zamkniętej rekrutacji i szkicu na górze stoją jak dotąd „Otwórz
ponownie…”, „Zmień powód zamknięcia…” albo „Dokończ i opublikuj…”.

## Czego w menu nie ma i gdzie to jest

- „Championi…” → plakietka statusu przy tytule (`JobChampionsStatus`).
- „Zespół” → fakt „Rekruter” w nagłówku (`JobRecruiterFact`), także zwinięty.
- „Ogłoszenie” → przycisk z megafonem i kropkami kanałów w nagłówku.
- „Baza pytań”, „Karta klienta” → okno „Zlecenie” (dwa kliknięcia, świadomie).
- „Pokaż / ukryj puste kolumny” → nie ma wcale (niżej).

**Pozycja, która ma już drugie widoczne wejście na tym ekranie, nie wraca do
menu.** Bo menu rosło z zasady „to, co zeszło z widoku, idzie do ⋯” (02.10)
i po trzech tygodniach połowa pozycji dublowała przyciski nagłówka. Nowa
akcja rekrutacji trafia do menu tylko wtedy, gdy nie ma innego wejścia;
wtedy ze zrzutem 1280 × 720, że menu dalej mieści się w oknie.

## Puste kolumny

Tablica zawsze pokazuje wszystkie kolumny szablonu, także puste; przełącznika
nie ma ani w menu, ani na Tablicy. Do 25.10.2026 domyślnie je chowano
(`hideEmptyKanbanColumns`, od 17.09.2026), a Tablica nie mówiła, że coś
ukryła. Pole zniknęło z `nexus-ui` (migracja v11 w `store/ui.ts`); nie
dodawaj go z powrotem przy pracy nad szerokością Tablicy.

Spis funkcji: `header.menu-empty-columns` ma `removed_reason`, pozostałe
wpisy wskazują nowe miejsca (`recruitment-feature-inventory.json`).
