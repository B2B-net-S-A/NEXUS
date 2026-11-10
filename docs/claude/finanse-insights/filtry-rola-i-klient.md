# Filtry wyników zespołu: Rola i Klient
<!-- indeks: pulpit „Aktywność rekrutacyjna”, „Kto się liczy”, tabela Ludzie, kafel „Wyniki zespołu”, raport „Aktywność zespołu”; Rekruterzy = rola rekrutera bez HoR i admina; start „Cały zespół · Rekruterzy”; wiersz „Poza filtrem”; `role` i `client_id` w trasach -->

Decyzje Artura z 10.11.2026 po prośbach Olafa (HoR) z 09.11.2026: filtr klienta
przy „Rozmowach u klienta” i statystyki bez Delivery Leadów, domyślnie
„Cały zespół · Rekruterzy”. Makiety: https://claude.ai/artifact/Y4enbWHVXkesAJLYUDWUEM.

## Jedna reguła, w jednym miejscu

`backend/app/services/team_filters.py`, na froncie `lib/team-filters.ts`
i kontrolki `components/v2/kpi/TeamFilterControls.tsx`. Nie pisz drugiej
definicji grupy na ekranie.

- **Rekruterzy** = konta z rolą rekrutera (także Delivery Lead i TCM, którzy ją
  mają), bez Head of Recruitment i admina. Ta sama grupa co lista „Kto”
  (`has_any_role(recruiter)`). Decyzja Artura: DL z rolą rekrutera, który
  naprawdę weryfikuje, zostaje w „Rekruterach” (na stagingu listopad: dwie
  takie osoby, 53 z 348 weryfikacji). Główna rola konta (`users.role`) tego nie
  rozstrzyga.
- **Delivery Leadzi** = konta z rolą DL. Grupy mogą się nakładać.
- **Klient** = klient rekrutacji, w której para osiągnęła etap (`jobs.client_id`).
  Wpisy DynaReportera nie mają rekrutacji, więc przy wybranym kliencie nie
  wchodzą do liczby.
- Konto liczy się do grupy bez względu na `is_active`, jak w sumie firmy.

## Gdzie działa

- **Pulpit → „Aktywność rekrutacyjna”**: Rola, Klient, Kto nad paskiem okresu.
  Role z wglądem w zespół (admin, HoR, DL, Finanse, TCM) startują od „Cały
  zespół · Rekruterzy”, rekruter od siebie. Filtr działa na kafle, „w tym dziś”,
  tabelę osób i listę pod liczbą. Wybór pamięta przeglądarka
  (`nexus:recruitment-activity:team-filters`).
- **Lista „Kto się liczy” w Insights**: kontrolki na liście całego zespołu.
  Start od „Wszyscy”, bo lista otwiera się z liczby lejka całej firmy i ma się
  z nią zgadzać.
- **Insights → Zespół → tabela „Ludzie”, zakładka „Rekruterzy”**: zawsze grupa
  Rekruterzy (wcześniej stały tam DL-e z aktywnością), do wyboru klient.
  Zakładka „Delivery Leadzi” to dalej portfele DL-i.
- **Kafel „Wyniki zespołu”**: Rola i Klient, domyślnie Rekruterzy, pamiętane per kafel.
- **Raporty → „Aktywność zespołu”**: tylko Rola. Klienta nie ma, bo ranking
  liczy też notatki i telefony, które nie należą do rekrutacji.
- **Bez filtra:** Rywalizacja (wyścigi mają własne zasady ról i wypłacają
  nagrody), Aktywność (rytm dnia już liczy samych rekruterów), Firma i raporty
  klientów (klient jest tematem ekranu), Mój miesiąc.

## Nic nie znika bez śladu

- Osoby spoza grupy roli stoją jednym wierszem „Poza filtrem”
  (`filtered_out` w `/team/people` i `/recruitment/team-activity`).
  Kafle plus „Poza filtrem” dają cały zespół; test tego pilnuje.
- W tabeli pulpitu przy filtrze roli konta administracyjne są w „Poza filtrem”,
  bo nie należą do grupy i nie ma ich w liczbie nad tabelą.
- Liczba przy kliencie na liście to wiersze po filtrze roli, przed filtrem
  klienta. Na pulpicie liczby przy kliencie nie ma, bo sumowałaby etapy.

## API

`role` (`all` | `recruiter` | `delivery_lead`) i `client_id` w
`/api/dashboard/v2/recruitment-activity`, `/details`, `/team-totals` oraz
`/api/insights/team/people`; sama `role` w `/api/insights/recruitment/team-activity`.
Odpowiedzi niosą `clients` (`id`, `name`, `count`). W widoku jednej osoby filtr
nic nie zmienia. Precyzja (30 dni) i „W drodze” w tabeli Ludzie liczą całą
pracę osoby, bez filtra klienta.
