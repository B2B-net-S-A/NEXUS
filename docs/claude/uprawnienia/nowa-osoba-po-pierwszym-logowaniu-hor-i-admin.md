# Nowa osoba po pierwszym logowaniu: decyzja HoR albo admina (0612, 28.10.2026)
<!-- indeks: setup_pending_since, new_person_signed_in, /api/people-setup, „Nowe osoby do ustawienia”, HoR nadaje tylko Rekrutera -->

Prośba Artura z 28.10.2026: kiedy ktoś loguje się pierwszy raz przez
Microsoft, konto powstaje jako „Konsultant/Kontraktor” (`employee`, decyzja
z 19.10.2026) i do tej pory nikt się o tym nie dowiadywał. Na kopii produkcji
z 22.10 konto czekało od 19.10 bez decyzji. Rekruter dostał kategorie dzień
później, ale nie miał przełożonego. Dwóch aktywnych rekruterów nie miało
żadnej kategorii, więc automat nie dawał im requestów. Makiety:
https://claude.ai/artifact/1JHbBUC392K7peJotFXNgs.

## Jak działa

- **Znacznik:** `users.setup_pending_since` (0612, DDL w
  `services/new_person_setup_schema.py`, lustro w `entrypoint.sh`). Ustawia go
  `new_person_setup.mark_and_notify` po pierwszym logowaniu SSO, ale tylko
  wtedy, gdy konto zostało samym `employee`. Konto, któremu mapowanie grup AAD
  dało inną rolę, nie czeka. Uzupełnienie wsteczne obejmuje tylko konta SSO
  od 19.10 bez wpisu `role_changed` / `roles_changed` /
  `new_person_setup_decided` i jest idempotentne.
- **Dzwonek i mail od razu** (`new_person_signed_in`, rodzaj maila
  `new_person`, kategoria „Konto i system”) do aktywnych adminów i Head of
  Recruitment. Mail nie jest obowiązkowy, każdy może go wyłączyć w „Moje
  maile”. Przyciski „Zdecyduj” i „Zostaw jako Konsultanta” tylko otwierają
  okno na pulpicie (`/dashboard?nowa-osoba=<id>[&zostaw=1]`). Decyzja zapada
  w oknie. Awaria powiadomienia nie blokuje logowania.
- **„Czeka na Ciebie” → „Nowe osoby do ustawienia”** (`new_people`
  w `/api/board-tasks`, tylko `PROPOSAL_DECISION_ROLES`):
  - nowe konta do decyzji;
  - rekruterzy bez kategorii, z wyjątkiem kont „Poza przydziałem” oraz osób
    z rolą admina albo HoR;
  - rekruterzy z kartoteką bez przełożonego (tylko przy włączonym programie
    „Ludzie”).

  Lista liczy się do tego, czy coś „czeka”. Gdy liczenie padnie, przychodzi
  `null` i panel mówi to wprost.
- **Okno „Ustaw”** zapisuje wszystko jednym `POST /api/people-setup/{id}`
  (`HeadOfRecruitmentPlus`, sekcja Pipeline):
  - Rola: Head of Recruitment zmienia tylko „Konsultanta/Kontraktora” na
    Rekrutera. Zmiana idzie przez `admin.update_user`, więc jest ten sam
    onboarding, ta sama nowa wersja uprawnień (wylogowanie) i te same wpisy
    w historii. Delivery Lead i inne role zostają w „Osoby i role” (422 dla
    HoR, link dla admina).
  - Kategorie przez `competence_team.assign_category`, tę samą regułę
    1. priorytetu co panel kategorii.
  - Przełożony przez `hr.structure.reassign`. HoR wskazuje siebie albo innego
    HoR (403 dla kogoś innego), admin dowolną osobę. Bez programu „Ludzie”
    kroku nie ma.
  - „Zostaw jako Konsultanta” zdejmuje sam znacznik.
  - Granice HoR (przegląd kodu 28.10.2026), których pilnuje serwer, nie
    sam ekran:
    - HoR decyduje tylko o koncie ze znacznikiem. Konsultanta bez znacznika
      nie promuje.
    - Kont z rolą admina albo HoR nie rusza.
    - Przełożonego ustawia tylko osobie nowej albo takiej, która go nie ma.
      Przepięcie cudzego zespołu dawałoby wgląd w godziny i premie.

  Każda decyzja zostawia wpis `new_person_setup_decided`.
- **„Osoby i role”**: przycisk „Do decyzji · N” i plakietka „Nowa · zdecyduj”
  otwierają to samo okno. Zmiana roli albo wyłączenie konta w panelu admina
  też zdejmuje znacznik.

## Czego nie robić

- Nie dokładaj automatycznego nadawania roli rekrutera po domenie albo po
  nazwie grupy. Decyzja należy do człowieka, bo 12.10.2026 automat dał
  kursantom dostęp do bazy kandydatów (`powiadomienia-dla-rol-…`, alarm 0508).
- Nie rozszerzaj uprawnienia HoR na inne role bez decyzji Artura. Wąskie
  przejście Konsultant → Rekruter to celowa granica.
