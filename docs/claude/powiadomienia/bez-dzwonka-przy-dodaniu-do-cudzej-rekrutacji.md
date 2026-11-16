# Dodanie osoby do cudzej rekrutacji nie dzwoni (16.11.2026)
<!-- indeks: also_fits_added bez dzwonka, wariant C, record_also_fits_added = tylko Activity, „Nowa osoba w Twojej rekrutacji” usunięte, rezerwacja 12 h -->

Decyzja Artura z 16.11.2026 po zgłoszeniu rekrutera („to powiadomienie też
useless troszkę”). Dodanie osoby do innej rekrutacji z „Pasuje też do” albo
„+ Dodaj inną rekrutację” (`proposals/bulk` ze źródłem `also_fits` /
`also_manual`) nie wysyła już dzwonka „Nowa osoba w Twojej rekrutacji” do
rekruterów tamtej rekrutacji. Zostaje wpis w historii kandydata
(`Activity(candidate, also_fits_added, {job_id, from_job_id, via?})`,
`also_fits.record_also_fits_added`). Zastępuje D2 z 14.10.2026.

Bo przez 12 h rezerwacji osobę prowadzi ten, kto ją dodał, więc odbiorca nie
miał z dzwonkiem nic do zrobienia. Pomiar na stagingu (kopia produkcji
z 16.11, dzwonki z 15.10–13.11): 49 dzwonków na 23 dodania (jedno dodanie do
8 osób naraz), treść średnio 274 znaki przy jednej linii w okienku
„Rekrutacje”, 12 z 23 osób dodający sam przesunął dalej w ciągu 12 h
(5 w ciągu 5 minut). Makiety wariantów A–C:
https://claude.ai/artifact/NpxRFnBVow4optXykCNi49

- Typ `NotificationType.also_fits_added` zostaje w enumie, kategorii, sekcji
  i tematach: stare wiersze w bazie muszą się dalej wyświetlać i liczyć.
  Nowych nie tworzy nic.
- Nie przywracaj dzwonka przy dodaniu „przy okazji” (np. przy zmianie
  „Pasuje też do”). Wariant B (jeden dzwonek „teraz Twój ruch”, gdy 12 h
  minie, a osoba dalej stoi w „Nowych”) przegrał z C 16.11.2026; 10 z 23
  osób stało wtedy w „Nowych” bez ruchu. Wraca się do niego tylko na nową
  decyzję Artura.
- Dzwonki przekazania DL-a („Wyślij też do”, `stage_changed`,
  `rekrutacja-tablica/dl-match-wyslij-tez-do.md`) to inna ścieżka i zostają.
