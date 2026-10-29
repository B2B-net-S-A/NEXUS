# Rekruter sam dorzuca rekrutację: „+ Dodaj inną rekrutację” i „Dodaj też do rekrutacji…” (29.10.2026)
<!-- indeks: „Screening dla” ręczne dodanie, `also_manual`, `GET …/also-fits/search`, `joinable`, menu „⋯” panelu osoby → „Przypisz do rekrutacji” -->

Zgłoszenie z 29.10.2026: rekruter chciał porozmawiać z osobą o drugiej
rekrutacji („Fullstack też na backend”), a NEXUS jej nie podsunął.
„Pasuje też do” ocenia 8 najbliższych wektorowo rekrutacji i pokazuje
najwyżej 3 z wynikiem ≥ 70 (`services/also_fits.py`), więc rekrutacja,
o której rekruter myśli, potrafi wypaść (staging: osoba w Screeningu
Fullstacka Nordei 43001 dostawała trzy inne Java, bez 42742). Delivery
dostało to samo 27.10 (`dl-match-wyslij-tez-do.md`, „+ Dodaj inną
rekrutację”). Decyzja Artura: warianty A i B naraz, makiety
https://claude.ai/artifact/P8kozdrrMZLEpkGtkktmvR.

- **A — „+ Dodaj inną rekrutację” w „Screening dla”** (`JointAddJob` pod
  podpowiedziami w `JointScreeningPicker`). Sekcja stoi także wtedy, gdy
  osoba nie ma innych rekrutacji ani podpowiedzi — wcześniej znikała.
  Wyszukiwanie `GET /api/candidates/{id}/also-fits/search?from_job_id=&q=`
  (`also_fits.search_open_jobs`): ta sama pula co podpowiedź (opublikowane
  w pracy, bez żadnego wiersza tej osoby, także zamkniętej karty), po nazwie,
  tytule dla rekrutera, numerze u klienta, kliencie i id, od 2 znaków,
  najwyżej 8, **bez oceny** (rekruter wie, czemu dodaje). Bramka jak trasa
  „Pasuje też do” (wzorzec authz ten sam).
- **`joinable` = rekruter jest w zespole tamtej rekrutacji** — ta sama reguła
  (`ensure_job_membership`) co pary „Screening dla” z `joint-context`. Takie
  rekrutacje są na górze i mają „+ Dodaj i dołącz”: dodanie do „Nowych”
  z rezerwacją 12 h i wejście do tej rozmowy (limit 4 rekrutacji w rozmowie
  bez zmian). Rekrutacja innego zespołu, albo komplet w rozmowie, ma
  „+ Dodaj do Nowych”: samo dodanie i komunikat „Dodano do „Nowych”: …” —
  para spoza zespołu i tak nie wejdzie do wspólnego formularza.
- **Źródło `also_manual`** w `proposals/bulk` (i w telemetrii
  `PIPELINE_ADD_SOURCES`), żeby statystyka podpowiedzi nie liczyła ręcznych
  wyborów. Wpis w historii i dzwonek do rekruterów rekrutacji B jak przy
  `also_fits` (`record_also_fits_added(..., manual=True)`): akcja
  `also_fits_added` z `via: "manual"`, w dzwonku „dodane ręcznie przy
  rozmowie” zamiast „podpowiedź „Pasuje też do””.
- **B — „Dodaj też do rekrutacji…” w menu „⋯” panelu osoby**
  (`PipelineCandidateDock`, na każdym etapie): otwiera to samo okno co
  „Przypisz do rekrutacji” na profilu (`QuickAssignV2`, zakładki „AI
  sugestie” i „Wszystkie”, przywracanie zamkniętej karty). Bramka jak
  „Czarna lista…”: prawo zapisu kandydata i brak trybu podglądu. Nie łączy
  rozmowy — to droga dla osoby już po screeningu, zanim DL wyśle CV (od
  „CV wysłane” DL ma „Wyślij też do…”).
