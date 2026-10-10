# Karta klienta (`client_playbooks`)

Jedno miejsce prawdy „jak pracujemy z tym klientem" (migracja `0272`, decyzje
Artura 03.09.2026). Tabela 1:1 z klientem + `client_playbook_events` (historia
z diffem pól). Pola: SLA w dniach roboczych, minimum kandydatów, limit CV na
proces, blokada kandydata (h), karencja między projektami (dni), polityka
stawek, „co powiedzieć kandydatowi o kliencie", reguły priorytetu, zasady
procesu (Markdown), onboarding po akceptacji (Markdown), dokumenty (nazwa +
link). API: `app/api/client_playbooks.py`.

- **Zapis = obowiązuje.** Bez `confirmed_at` jak w regułach CV: seed NIGDY nie
  nadpisuje istniejącego wiersza (`ON CONFLICT (client_id) DO NOTHING`), więc
  nie ma propozycji do odróżnienia od decyzji człowieka. `version` bumpuje się
  tylko przy realnym diffie; identyczny zapis nie zostawia wpisu w historii.
- **Tabela-siostra reguł CV, nie kolumny w `client_cv_rules`** — edycja
  obowiązującej reguły CV zdejmuje zatwierdzenie; adres biura na tym samym
  wierszu wyłączałby wymuszanie nazwy pliku do ponownego zatwierdzenia.
- **Bramki (lustro reguł CV po #1351):** zapis i historia = `DeliverySectionUser`
  (sekcja Delivery) + graf klienta `resolve_client_access` z `purpose="org"`
  (admin i Delivery Lead dla każdego klienta — ten sam formularz jest
  w edytorze reguł CV, a te są otwarte). **Odczyt karty i przeglądu = `OperationalUser`,
  org-wide, bez grafu klienta** — świadome odstępstwo: karta zastępuje 14 wzorów
  Word w Pomocy, które czytał każdy zalogowany, a rekruter czyta ją PRZED
  przypisaniem do rekrutacji. **Off-limits: funkcja usunięta 27.09.2026 decyzją
  Artura; kolumny zostają** (`client_contract_terms.off_limits_*` — karta,
  przegląd i `contract-terms` ich nie oddają, PUT je ignoruje, UI nie ma pól;
  runda 9, R9-N4-8). `client_playbooks.router`
  NIE trafia na listę routerów Delivery w `test_section_access.py` (bramki per
  handler, jak `client_cv_rules.router`).
- **Trzy powierzchnie odczytu, jeden formularz:** profil klienta → „Zasady
  współpracy" (edycja w miejscu dla DL/admina), rekrutacja → sekcja 6 Championa
  (wariant compact; link „Pełna karta klienta →" prowadzi do Pomocy, bo `/clients/*`
  jest w middleware bramkowane sekcją Delivery), Pomoc → Klienci (procedura per
  klient generowana z karty, `?tab=clients&client=<id>`). Edycja także jako
  zakładka „Karta klienta" w `/settings/cv-rules?client=<id>&tab=playbook`.
  Formularz jest JEDEN (`ClientPlaybookForm`); capability `client_playbook.manage`
  = admin + delivery_lead z wymogiem sekcji Delivery/write.
- **Seed jest KOMPLETNY** (decyzja: „żeby nic nie uciekło z aktualnych plików"):
  każda linia standardów, opisu klienta i dokumentów z 14 wzorów trafia do karty,
  w tym linie o nazwie pliku/języku CV (dublują regułę CV — DL usuwa je z karty,
  gdy reguła CV jest zatwierdzona) i linie o pochodzeniu kandydata (przeniesione
  jak są). Liczby (SLA, limity) zasiano tylko tam, gdzie wzór podawał je WPROST.
  Wzorce dopasowania klienta są z 0255; wieloznaczne (np. `%bnp%` przy kilku
  klientach BNP) nie zasieją nic — DL zakłada kartę ręcznie z treści `seed.json`.
- **Trzy miejsca rejestracji modelu** (`models/__init__`, lokalne importy sondy
  startowej i lista probe tuples w `main.py`) i **lustro w `entrypoint.sh`**
  (DDL w `_COLUMN_STATEMENTS`, `_seed_client_playbooks(conn)` po procedurach,
  odpublikowanie wzorów w `_DATA_STATEMENTS` z markerem
  `0272_champion_client_templates_unpublished` w `app_settings`, który nie cofa
  ponownej publikacji przez admina). Prod alembic jest osierocony — entrypoint
  JEST wdrożeniem.
- **Nie przenoś na kartę `selling_points`/`consultant_insight`/`historical_questions`
  bez A/B** — zasilają wektor oferty i prompt generatora CV (949 ofert).
- Poza zakresem MVP: `DELETE`/`copy-from` karty, alerty z pól strukturalnych (SLA).
