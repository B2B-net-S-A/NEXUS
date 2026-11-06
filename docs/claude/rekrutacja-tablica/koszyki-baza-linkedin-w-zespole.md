# Koszyki „Baza” / „LinkedIn” w zespole rekrutacji (0655, 06.11.2026)
<!-- indeks: kto szuka w bazie NEXUSA, a kto na LinkedInie; plan koszyków; „Pracują bez przypisania” jako ostrzeżenie, nie bramka -->

Decyzje Artura z 06.11.2026. Makiety (wariant B):
https://claude.ai/artifact/Whdf5UxmLqKiUpmbcUYTyk. Chodziło o to, żeby Head
of Recruitment ustawiał, kto przy danym requeście szuka w bazie, a kto na
LinkedInie, i żeby rekruter to widział.

## Dlaczego ręcznie

Danych o pracy na LinkedInie w NEXUSIE nie ma. Na kopii produkcji z 06.11
w 60 dniach było 13 080 pierwszych dodań osób, które już były w bazie, 638
nowych profili z linkiem LinkedIn i 972 nowe profile z innych źródeł.
Wiadomości z LinkedIna do NEXUSA nie trafiają, a pole `role` w
`job_work_assignments` ma wszędzie `recruiter`. Kto pracuje na LinkedInie,
wie więc tylko zespół: koszyk jest planem, nie pomiarem.

## Reguła

- **Dane:** tabela `job_recruiter_channels` (rekrutacja, osoba, `base` |
  `linkedin`, kto i kiedy ustawił) i kolumny `jobs.channel_plan_base` oraz
  `jobs.channel_plan_linkedin` (`NULL` = bez planu). SQL jest w
  `services/job_channels_schema.py`, a migracja 0655 i `entrypoint.sh` czytają
  go z tego jednego miejsca. Tabela stoi osobno od trzech źródeł „Rekrutera”
  (`job_team`), bo zmiana prowadzącego albo akceptacja propozycji nie może
  zgubić koszyka.
- **Koszyk w regule zespołu:** `job_team.recruiters_for_jobs` dokłada
  `channel` do każdej osoby (`TeamPerson.channel`, `JobRecruiterOut.channel`).
  Lista, okienko zespołu i pulpit dostają go bez osobnych zapytań. Wiersz
  osoby spoza zespołu nic nie znaczy.
- **Kto ustawia** (`PUT /api/jobs/{id}/channels/{user_id}`): rekruter swój
  koszyk; każdy koszyk rola z `user_can_staff_job` (Head of Recruitment, Delivery
  Lead w swoim zakresie, admin). Osoba musi pracować nad rekrutacją
  (propozycja automatu jeszcze nie), inaczej 409. Plan
  (`PUT /api/jobs/{id}/channel-plan`, 0–20 osób) ustawia tylko rola
  przydzielająca. Każda zmiana zostawia wpis w Historii
  (`recruiter_channel_changed`, `channel_plan_changed`).
- **Dołączenie od razu do koszyka:** `POST /api/jobs/{id}/collaborators`
  przyjmuje `channel`. Z tego korzystają „Dołącz do bazy” / „Dołącz do
  LinkedIna” i „Do bazy” / „Do LinkedIna” przy osobach bez przypisania.
- **Bez przypisania to ostrzeżenie, nie bramka** (Artur wybrał „tylko
  ostrzeżenie”; obowiązuje „Kanban bez bramek”). Rekruter z rolą rekrutera,
  który w ostatnich 30 dniach dodał albo przesunął kartę w rekrutacji
  (`candidate_stages.moved_by`), a nie jest w zespole, trafia do
  `GET /api/jobs/{id}/unassigned-workers` i do `unassigned_workers` wiersza
  pulpitu. Ruch karty działa dalej bez zmian. Nie dokładaj tu bramki bez
  nowej decyzji Artura.
- **Obłożenie:** `load[].base` / `load[].linkedin` liczą te same rekrutacje P1
  co `count`. Osoby bez koszyka to różnica, więc liczby się sumują.

## Ekrany

- Okienko „Zespół rekrutacji” (`JobChannelBuckets` w `JobOwnershipPanel`):
  dwa koszyki z planem („1 z 2”), pusty koszyk z planem jest bursztynowy
  („Brakuje: 1 osoba.”), „Bez koszyka” z „→ Baza” / „→ LinkedIn”, „Ustaw plan
  koszyków”, ramka „Pracują bez przypisania”. Propozycje automatu stoją pod
  koszykami w zwykłej liście.
- Daily (`RequestBoard`): przy nazwisku sama ikonka koszyka (przy 1280 px
  kolumna nie rośnie, dlatego bez drugiej kolumny z makiety B), osoby
  w kolejności Baza → LinkedIn → bez koszyka i bursztynowe dopiski
  (`boardChannelNotes`): „LinkedIn: brakuje 1 z 1”, „bez koszyka: N”,
  „bez przypisania: N”.
- Obłożenie (`LoadPanel`): pasek z odcinków Baza, LinkedIn i bez koszyka,
  a po rozwinięciu „Baza: N · LinkedIn: M”.
- Nagłówek Tablicy (`JobRecruiterFact`): zalogowany rekruter widzi znaczek
  swojego koszyka w fakcie „Rekruter”.
- Ikony: znak Dynaminds (`public/brand/dynaminds-mark.svg`, wpisany
  w `ChannelBadge`) dla bazy i `Linkedin` z lucide dla LinkedIna.
