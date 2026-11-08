# Czeka na odpowiedź klienta: pas nad Tablicą i trzy akcje na karcie (08.11.2026)
<!-- indeks: `services/client_wait.py`, `GET /api/client-wait/jobs/{id}`, „Przypomnij klientowi” bez wysyłki, `ended_by='client_silent'`, wyłącznik `app_settings['client_wait']`, 6. dzień roboczy -->

Decyzje Artura z 08.11.2026 po audycie 2 (S-C2). 85% czasu do zatrudnienia to
czekanie na klienta, tylko 27% CV ma jakąkolwiek odpowiedź, a 278 z 789 par stoi
u klienta ponad 30 dni. Makiety: https://claude.ai/artifact/VXHZFJQZQbNRXAVGzNfdCu
i C2 w https://claude.ai/artifact/AotE3yHZ1zq62oy2L4b4Sf.

- **Kto czeka:** bieżąca karta w „CV wysłane” albo „Rozmowie u klienta”, bez rozmowy
  przed nami i bez otwartego wniosku o terminy. Ta sama myśl co w follow-upie z
  kandydatem, ale bez daty granicznej: pas zbiera też stare pary.
- **Od kiedy:** ponad 5 dni roboczych (`waiting_workdays`), czyli od 6. dnia. Zegar
  to późniejsze z: wejścia na etap, ostatniej rozmowy, ostatniego wniosku o terminy
  i „Klient odpowiedział”.
- **Kto widzi i klika:** te same osoby co przy zamknięciu rekrutacji
  (`RecruitmentManageUser` + zakres DL-a).
- **Z NEXUSA nic nie idzie do klienta (D2).** `POST …/reminder` zwraca treść, DL ją
  kopiuje albo otwiera w poczcie. Zapisuje tylko ślad „przypomniano”.
- **Link do panelu tylko, gdy DL sam go włączył.** Panel klienta nie włącza się
  automatycznie (`klienci/panel-klienta-pod-linkiem.md`).
- **Stan panelu przy osobie:** „Panel: otwarty 3× · ostatnio 05.11 · bez decyzji”,
  „Panel: klient chce rozmowy 06.11”, „Panel: nie pasuje: …”.
- **„Klient odpowiedział”** (bez decyzji) liczy zegar od nowa, wpis
  `client_responded` w historii rekrutacji.
- **„Zamknij — brak odpowiedzi”** to zwykły ruch przez `usePipelineMoveCore`,
  `ended_by='client_silent'`, powód „Klient nie odpowiedział” (`client_no_response`).
  Bez maila do kandydata. `client_silent` nie jest odrzuceniem osoby: ranking go
  nie liczy (`known_people_signal`, `known_queue_points`).
- **Automat:** tylko „CV wysłane”, 30 dni kalendarzowych ciszy, `ended_by='client_silent'`,
  pętla `client_wait` co godzinę w dzień roboczy 8–17. **Domyślnie wyłączony**,
  włącza HoR albo admin w Ustawienia → Zespół rekrutacji → „Automat przydziału”
  (`app_settings['client_wait']`), bez wdrożenia. Po włączeniu pary starsze niż
  próg dostają jeszcze 7 dni (`BACKLOG_GRACE_DAYS`), inaczej pierwszy przebieg
  zamknąłby setki kart naraz. „Rozmowa u klienta” nie zamyka się sama.
- **Karta:** serwer daje `client_silent_workdays` (ta sama reguła co pas, `None` do 5.
  dnia roboczego), więc plakietka „Klient milczy” i menu gasną po „Klient odpowiedział”.
  Plakietka stoi w „CV wysłane” i „Rozmowie u klienta”. Menu „Co z klientem?” jest
  w wierszu ruchu tylko w „CV wysłane”, dla osób z `recruitment_manage`; liczba dni pod
  nim, bo karta ma 160 px. Awaria liczenia = brak plakietki i log, nigdy 500 Tablicy.
- **„Zamknięci”:** `client_silent` liczy się do „przez klienta” (`closedRejectBy`).
