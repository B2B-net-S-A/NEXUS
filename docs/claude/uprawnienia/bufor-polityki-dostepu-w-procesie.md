# Bufor polityki dostępu w procesie (decyzja Artura 04.11.2026)

Pomiar z 04.11.2026: trasy są wolne przez kolejkę w jednym wątku Pythona, nie
przez bazę, a 48% instrukcji SQL to autoryzacja i ustawienia. Dlatego polityka
dostępu (`rbac_*` i `app_settings['notification_role_mutes']`) żyje w jednej
migawce procesu: `services/policy_cache.py`. Odczyt idzie przez
`effective_access.resolve_effective_access`, jak dotąd.

- **Odebranie działa od następnego żądania.** Zdarzenia sesji SQLAlchemy widzą
  każdy zapis polityki (ORM, DML, `text()` przez sesję) i kasują migawkę po
  commicie. Nowa trasa zapisująca politykę przez sesję nie musi o tym pamiętać.
- **Limit 30 s to siatka, nie mechanizm.** Obejmuje to, czego zdarzenia tego
  procesu nie widzą: drugi kontener przy rolling update, skrypt w osobnym
  procesie, `conn.execute` z pominięciem sesji (siatka DDL przy starcie). Zapis
  polityki w działającym procesie z pominięciem sesji wymaga
  `invalidate_policy_cache()` po commicie.
- **Odczyt zaczęty przed commitem nie trafia do bufora** (`_generation`), a limit
  liczy się od początku odczytu.
- **Sesja z niezatwierdzonym zapisem polityki czyta przez siebie** (znacznik
  w `session.info`). Nikt inny nie widzi jej wierszy przed commitem, a ona sama
  widzi je po `flush()`.
- **Do bufora trafiają wartości, nigdy obiekty ORM.** Odczyt idzie po kolumnach,
  bo encja załadowana wcześniej w tej samej sesji zachowałaby stare wartości
  i rozniosła je na wszystkie żądania.
- **Role konta nie są w buforze.** Liczą się z wiersza `users`, czytanego przy
  każdym żądaniu, więc zmiana ról osoby działa od razu.
- **Oczekujący na odczyt nie oddaje połączenia** (`cache_single_flight` bez
  `db=`), bo commit zwolniłby blokady `FOR UPDATE`, które wołający mógł wziąć.
- **Testy:** `tests/conftest.py` wyłącza bufor (`_policy_cache_off`), bo testy na
  wspólnej bazie dosiewają politykę z pominięciem sesji. Zachowanie sprawdza
  `tests/test_policy_cache.py`, także odmowę 403 po odebraniu przez panel.
- **Ekrany „Osoby i role” czytają tabele wprost**, nie z bufora: panel ma pokazać
  stan bazy i zapisuje pod blokadą `rbac_policy_state`.
