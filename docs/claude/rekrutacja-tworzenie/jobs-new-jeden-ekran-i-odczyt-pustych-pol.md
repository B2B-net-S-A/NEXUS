# `/jobs/new`: jeden ekran, „Wypełnij z…” i odczyt tylko pustych pól (D1–D4, 10.10.2026)

Decyzje Artura 10.10.2026 (makiety https://claude.ai/artifact/DehYwkrVBK498hCbyRUdie). Do tej daty były dwa kroki:
trzy źródła dawały trzy różne ekrany (ręczny — pusty prostokąt na 40% szerokości, braki podświetlone dopiero po
odczycie AI), a zmiana źródła kasowała wpisane pola bez pytania (`onRead` podmieniał cały formularz).

- **D2: formularz stoi na stronie od wejścia.** Kroków nie ma (`step`, `StepPills`, „Zmień źródło”, `NewJobSourceStep`
  usunięte). Nad sześcioma sekcjami `NewJobSourceBar`: klient i „Wypełnij z: Wklej treść | Wgraj plik | Inna
  rekrutacja” (jeden panel pod paskiem), do użycia w dowolnej chwili i wiele razy. Pasek zostaje jednym rzędem
  przy 1280 × 720. Ręczne wpisywanie nie jest źródłem do wybrania.
- **Treść requestu stoi obok formularza tylko, gdy jest** (`requestText`: treść odczytana albo opis szablonu, idzie
  też jako opis rekrutacji). Bez niej formularz ma całą szerokość, a karta „Pliki” stoi po sekcji 6. `pasteDraft`
  to treść w panelu, jeszcze nieodczytana — nie może udawać requestu, z którego powstały pola.
- **D3: odczyt wypełnia tylko PUSTE pola** (`lib/job-intake-fill.ts`, `applyIntakeRead`). Nietknięty formularz
  (`isPristineIntake`) bierze odczyt w całości. Inaczej: puste → wypełnij, takie samo → nic, inne → propozycja pod
  etykietą pola (`IntakeOfferChip`: „W mailu / W pliku / W szablonie: … [Użyj] [Zostaw]”). Razem idą: budżet „od–do”
  z uwagą, tryb pracy z dniami, termin i hiring manager z decyzją „Klient nie podał”; miasta to zbiór. Wymagania
  i pytania: gdy są już wpisane, JEDNA propozycja „jeszcze N … [Dodaj]” (limity 10/20, nigdy „krytyczne”). Odczyt
  nie rusza „Brak krytycznych”, kategorii, tytułu dla zespołu, numeru wpisanego ręcznie ani poziomów wierszy.
  Nie wracaj do `setForm(formFromIntake(...))` ani do zerowania formularza przy zmianie źródła.
- **Szablon („Inna rekrutacja”, `?from=`, baner) idzie tą samą drogą**: `applyTemplate(pusty, …)` →
  `applyIntakeRead(…, { source: "template" })`. `TemplateJobPicker` woła `jobsApi.list` z JEDNĄ wartością
  `client_id` — tablica poszłaby jako `client_id[]`, którego serwer nie zna, i lista pokazałaby wszystkich klientów.
- **„Cofnij wypełnienie” to łatka, nie migawka** (`IntakeFillUndo`): wraca tylko to, co wpisał odczyt i czego nikt
  potem nie zmienił. Propozycje jadą w autozapisie (`IntakeFormState.offers`), cofnięcie nie. Drugi odczyt dopisuje
  treść pod kreską, a plik requestu zapisuje się raz na odczyt (efekt na liczniku odczytów).
- **Braki są podświetlane w każdym trybie tak samo**: po odczycie, przy szablonie i po „Utwórz i opublikuj”.
  Przycisk przy brakach albo bez klienta jest AKTYWNY — kliknięcie podświetla pola, przewija do pierwszej sekcji
  z brakiem i nic nie wysyła (`MISSING_NOTE_TEXT`: „Brak w requeście / w szablonie — uzupełnij”, „Uzupełnij przed
  publikacją”). Nieaktywny tylko przy komplecie pól bez rekrutera, blokadzie portalu i sprawdzaniu krytycznych.
- **Pusta strona nie wysyła żadnego POST-a** — także po samym wyborze klienta: bez treści w formularzu nie ma
  zapytania o kategorie ani autozapisu. Lista niedokończonych formularzy stoi tylko na pustej stronie.
- **Zgodność zapisu:** formularz zapisuje zawsze `step: "review"`, a `requestRead` mówi, czy `request_text` to
  treść odczytana; stary zapis z `step: "request"` wraca do panelu „Wklej treść”.
- **D1** (przecinek i Enter w pustym wierszu to osobne wymagania, wariant przez „+ lub”) — reguła
  w `umiejetnosci-krytyczne-i-bramka-v9.md`.
- **D4: wypełniony wzór Profilu Championa (.docx) czyta KOD, bez modelu** (`services/job_intake_champion_file.py`:
  `champion_document.table_profile` + `champion_intake.prepare_profile`). `POST /api/job-intake/read-file` próbuje
  go najpierw; odpowiedź ma wtedy `reader: "champion_form"`, źródło pól „z dokumentu” (`FieldBasis` `document`)
  i `champion_extras` — sekcje wzoru bez pola w formularzu (frazy i plan searchu, insight konsultanta, pytania
  klienta z poprzednich rozmów, branże, „Wiedza z rozmów”). Formularz niesie je w `IntakeForm.championExtras`
  (także w autozapisie), a `buildChampionPayload` dokłada do `search` / `client` / `insights`; pola formularza
  wygrywają. Pusty wzór = 422 po polsku; plik, którego nie da się odczytać jako wzoru (inny dokument, błąd
  tabeli, profil nie przechodzi walidacji), idzie starą ścieżką z modelem (`reader: "request"`), a PDF wzoru
  dostaje uwagę „wgraj .docx”. Nowa sekcja wzoru bez pola w formularzu = wpis w `champion_extras`, inaczej
  wgranie pliku ją gubi. Pomiar na plikach z produkcji (tylko odczyt, same liczby):
  `python -m scripts.eval_champion_file_read --limit 200` w kontenerze backendu — 10.10.2026 produkcja nie miała
  jeszcze żadnego pliku requestu, więc czytnik jest sprawdzony tylko na wzorach z obrazu.
- **Fokus nie może spaść na początek strony**, gdy kliknięty przycisk znika: po zamknięciu panelu źródła wraca na
  jego przycisk (`NewJobSourceBar`), po „Użyj” / „Zostaw” przechodzi do pola propozycji (`focusFieldAfter` —
  najpierw pole do wpisywania, nigdy „Usuń frazę”), po „Cofnij wypełnienie” zostaje na pasku źródeł.
- **W trakcie odczytu (do 2 minut) zablokowane są: wybór klienta, „Utwórz i opublikuj” i „Dokończę później”** —
  odczyt klienta A nie może trafić do formularza klienta B, a utworzenie w trakcie zgubiłoby odczyt.
- Propozycje z zapisanego formularza przechodzą `restoreIntakeOffers` razem z wnętrzem (wiersze, pytania, łatka);
  zepsuty wpis jest pomijany. Sekcje pliku Championa bierzemy z PIERWSZEGO pliku — pasek mówi wprost, gdy drugi
  ich nie wniósł (`championSections`: `taken` / `kept` / `none`).
- Harness `/preview/new-job?state=manual|attempted|offers|champion`.
