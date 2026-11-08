# Słownik rośnie z danych: nocne propozycje i podpowiedź w wymaganiach (06.11.2026)

Audyt słownika z 06.11.2026: słownik (`skills`, 256 haseł, 493 aliasy) znał 46%
must-have w rekrutacjach, a 89% rekrutacji miało choć jedno wymaganie spoza
słownika. Takie słowo dopasowanie i bramka must-have szukają dosłownie, więc
„mikroserwisy” nie znajduje osób z „Microservices”. Próba z 400 hasłami
podniosła pokrycie do 56%, a P@5 dopasowania z 0,103 do 0,117 (6 rekrutacji
lepiej, 0 gorzej). Decyzja Artura „Etap 1: A + B”.

## Zasada D7 bez wyjątków

- Jeden słownik dla wymagań, profili i mapy klienta. **Nic nie mapuje się
  samo**: model tylko proponuje, do słownika wchodzi to, co zatwierdzi Head of
  Recruitment albo admin. Delivery Lead zmienia podpowiedzią wyłącznie swój
  wiersz wymagań.

## A — zakładka „Propozycje” (Ustawienia → Słownik umiejętności)

- Pętla `tasks/skill_proposals.py` raz na dobę 1:00–5:00 (Warszawa,
  `local_now`), dzień biegu w `app_settings['skill_proposals_state']`, więc
  deploy nie liczy drugi raz tej samej nocy. Na stagingu zablokowana (woła AI).
  Ręcznie: `python -m scripts.skill_proposals_run [--no-model]`.
- Źródła nazw (`services/skill_proposals.collect_names`): `candidates.skills[*].name`
  (liczba profili), `cv_generated_documents.render_payload->skills[*].content`
  ze statusem `ready`, bez odrzuconych, rozcięte po przecinku i średniku poza
  nawiasem (liczba CV), `jobs.must_skills||nice_skills[*].name` z „A lub B”
  i „A / B” rozciętymi na dwa zapisy (liczba rekrutacji). Pomijane: krótsze niż
  2 znaki, dłuższe niż 100, więcej niż 6 słów.
- Znane = `care/skills.load_dictionary().resolve()`. Rodzina = `loose_key` po
  zdjęciu nawiasów i przedrostków ms/microsoft/apache. Waga = profile + CV +
  20 × rekrutacje. Co noc top 400 rodzin, z pominięciem zatwierdzonych
  i odrzuconych: ich nazwy nie wracają.
- Rodzina, której każdy zapis trafia `loose_key` w to samo hasło, to wariant
  z pewnością „high” bez modelu. Reszta idzie do modelu F45 (GPT-6.1 Sol,
  zapas Sonnet 5.5) w partiach po 50; raz sklasyfikowana rodzina nie wraca do
  modelu, nawet gdy dojdą do niej nowe zapisy.
- **Bezpieczniki** (`apply_guards`), bo wynik modelu to propozycja, nie fakt:
  wariant roli (`role_*`) → „low” i „Wskazuje rolę …, nie umiejętność: tylko
  ręcznie”; wariant nieistniejącego hasła → „low”; nowe hasło równe
  istniejącemu hasłu albo aliasowi → wariant; kategoria spoza listy
  (kategorie słownika bez `role_*` plus `practice`, `domain`) → brak i „low”;
  ogólnik dostaje zamienniki wyłącznie z haseł słownika. Po klasyfikacji
  rodziny z tym samym hasłem łączą się w jeden wiersz.
- Decyzje (`/api/skills-admin/proposals…`, HoR+ jak reszta słownika):
  „Dodaj” = `skill_curation.create_skill_rows` z zapisami jako aliasami,
  „Zmapuj” = `add_alias_rows`, „Zmień” = poprawka decyzji, nazwy, kategorii
  albo hasła, „Pomiń” = odrzucenie. Ogólnika, cechy i śmiecia nie da się
  zatwierdzić (422). Konflikt aliasu z innym hasłem = 409, jak w kuracji.
- „Zatwierdź pewne” (przez `useConfirmV2`): tylko „high”, nowe hasło albo
  wariant, bez uwagi, z kategorią. Każda propozycja we własnym savepoincie
  (konflikt jednej nie cofa reszty), mapa aliasów odświeżona raz.
- Nocą pętla zapisuje też liczbę profili per hasło słownika
  (`app_settings['skill_dictionary_usage']`) — liczby w podpowiedzi. To suma
  po zapisach, więc osoba z „Java” i „java 11” liczy się dwa razy.

## B — podpowiedź w edytorze wymagań

- `POST /api/job-intake/dictionary-hints` (OperationalUser, limiter jak
  `critical-suggestion`, do 60 słów, bez modelu). Hook `useDictionaryHints`
  w `lib/requirement-rows-api.ts`, wyłączony przy `countEnabled=false`;
  podpowiedź pojawia się tylko po udanym zapytaniu, „Zostaw” chowa ją na tym
  ekranie.
- Wariant → „Dodaj do wiersza „Microservices””, ogólnik → „Dodaj warianty:
  PostgreSQL, MySQL…”, nowe hasło → „Dodaj zapisy: microsoft excel, ms excel”,
  bez propozycji → `care/skills.suggester` („Może chodzi o …?”). Przycisk
  zmiany słownika („Dodaj do słownika”, „Zmapuj w słowniku”) widzi tylko HoR+
  (`can_curate`), a trasa ma własną bramkę.

## Etap 2 — porządek w słowniku (06.11.2026)

- **Kategoria jest obowiązkowa przy nowym haśle** (`POST /api/skills-admin/skills`,
  422 bez kategorii albo z kategorią spoza listy). Bez niej hasło nie działa
  w pogrubianiu CV, QC ani bramce must. Lista: `skill_curation.category_choices`
  — kategorie słownika bez ról plus `practice` i `domain`, ta sama co
  w propozycjach. „Nowa umiejętność” z nieznanego terminu też pyta o kategorię.
- **„Popraw” hasło** (`PATCH /api/skills-admin/skills/{id}`): nazwa i kategoria.
  Zmiana nazwy większa niż wielkość liter zostawia starą nazwę jako alias, więc
  zapisy w profilach i wymaganiach dalej trafiają w hasło. Tak poprawia się
  małe litery w nazwach („nosql” → „NoSQL”) bez migracji danych.
- **Role osobno.** Hasła `role_*` to stanowiska: lista Słownika ma przełącznik
  „Umiejętności / Role” (`kind`), wybór hasła do „Zmapuj” szuka bez ról, a rola
  nie przyjmuje nowych aliasów (`skill_curation._add_alias`, także „Zmapuj”
  w opiece i w propozycjach). Istniejące aliasy ról zostają.
- **Zapamiętane wyniki dopasowania po zmianie słownika.** Klucz pamięci wyników
  (`scoring_algorithm_version`) nie zależy od treści słownika, a pamięć nie ma
  TTL, więc wynik sprzed nowego aliasu żył dalej (test
  `test_cached_score_is_recomputed_after_new_alias`). Każda zmiana słownika
  (nowe hasło, alias, „Zmapuj”, „Popraw”, propozycje) kończy się
  `skill_curation.after_dictionary_change`: najpierw nowa mapa aliasów, potem
  unieważnienie wyników rekrutacji, których wymagania wymieniają hasło w którymś
  zapisie (`mark_stale_for_jobs`). Punktowo, nie całej tabeli, jak przy
  profilach wag.

## Wersja słownika i unieważnianie (audyt 2, 08.11.2026)

- Nocny bieg powiązań unieważnia tylko hasła zmienione tej nocy, a przy braku
  zmian nic. `invalidate_scores` bierze wyłącznie opublikowane rekrutacje.
  Dlatego powrót do publikacji (`publish_core`, jedyna droga: PATCH statusu
  daje 409 `reopen_required`) sam unieważnia wyniki tej rekrutacji; bez tego
  wracałaby ze starymi po zmianach słownika.
- `app_settings['skill_dictionary_version']` zmienia każda zmiana słownika.
  Pętla `tasks/skill_dictionary_sync.py` w każdym procesie co 60 s porównuje
  wersję i przeładowuje mapę. Stoi poza rejestrem pętli w `main.py`, bo rejestr
  startuje tylko u lidera, a mapa musi być świeża też w procesie bez blokady.
- Do 60 s po zmianie inny proces liczy jeszcze starą mapą, a taki wynik zostaje
  w pamięci wyników. To cena odpytywania co minutę.
- Wersja słownika jest tylko stemplem przeglądu automatycznego
  (`version_trace.skill_dictionary`), a nie częścią odcisku ani
  `_REVIEW_VERSION_KEYS`. Decyzja Artura z 08.11.2026. Słownik zmienia się
  prawie co noc, więc w odcisku dawałby co rano 409 w oknie propozycji na
  większości rekrutacji (limit 48 przeglądów na noc, 185 rekrutacji w pracy),
  a w kolejce zrównałby wszystkie z rekrutacjami, w których coś się stało.
