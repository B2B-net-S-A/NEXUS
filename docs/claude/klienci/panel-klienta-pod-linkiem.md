# Panel klienta pod linkiem z CV (0639, 02.11.2026)
<!-- indeks: `/k/{token}`, sam link bez kodu, token HMAC + SHA-256 w bazie, dowód tylko z CV, stawka do klienta, oczekiwania i kontakt nigdy, wspólny serwis terminów, ramka w pobranym Wordzie, doprecyzowanie D2 -->

Decyzje Artura z 02.11.2026. Makiety: https://claude.ai/artifact/JV234LbwTz1UFBH4r1STfb.
Kod: `api/public_client_panel.py`, `api/client_panel.py`,
`services/client_panel*.py`, `services/interview_slot_requests.py`,
SQL `services/client_panel_schema.py` (lustro w `entrypoint.sh`, sondy w `/api/health/deep`).

- **Doprecyzowanie D2 („z NEXUSA nic nie idzie do klienta”, 07.10.2026).** Zasada
  zostaje. Jedyna droga wyjścia to ten panel, włączany na rekrutację przez osobę
  z prawem i z tego, co DL i tak wysłał klientowi w CV. Inne publiczne linki
  (karta Championa, interaktywne CV) nie wracają przy okazji.
- **CV dalej idzie plikiem.** Pobrany Word ma pod tytułem ramkę: QR, klikalny link,
  krótki adres i ważność (`client_panel_stamp`). Ramka powstaje przy pobraniu
  (`intent=download`: plik generatora, szkic i zatwierdzona wersja etapu, też PDF),
  zapisane bajty i `docx_sha256` się nie zmieniają. Podgląd w NEXUSIE, edytor
  generatora i API v1 ramki nie mają. Awaria = plik bez ramki i wpis w logu.
- **Wejście: sam link, bez kodu z maila.** Dlatego token z sekretu aplikacji
  (`base32(HMAC(SECRET_KEY, "client-panel:{id}:{nonce}"))`, 16 znaków, 80 bitów),
  w bazie tylko SHA-256, nieznany lub wyłączony = 404, wygasły albo rekrutacja
  zamknięta = 410, `noindex`, `no-referrer`, `no-store`, limity tras. „Odwołaj link”
  zmienia `nonce`. Zmiana `SECRET_KEY` unieważnia wszystkie linki: nowy link daje
  dopiero „Odwołaj link”. Ważność przy włączeniu: koniec dnia za 60 dni.
- **Domyślnie wyłączony na każdej rekrutacji.** Włącza osoba z uprawnieniem
  „Rekrutacje” i członkostwem w rekrutacji (`RecruitmentManageUser`
  + `ensure_job_membership` + `_ensure_panel_manager`: zespół rekrutacji albo DL z portfelem
  klienta, poza tym admin i Head of Recruitment; DL cudzej rekrutacji dostaje 403, bo panel
  wypuszcza stawki na zewnątrz). Rola Head of Recruitment bez tego uprawnienia nie
  ma dostępu, jak we wzorcu `tests/data/authz_golden/client_panel.json`.
- **Zamknięta rekrutacja nie ma działającego panelu** (decyzja Artura 04.11.2026, po
  teście, w którym panel włączony na zamkniętej rekrutacji pokazał „minął termin”).
  Włączenie = 409, włącznik w oknie nieaktywny, a Word nie dostaje ramki. Panel włączony
  przed zamknięciem można wyłączyć; okno ostrzega, a klient widzi „rekrutacja zakończona”.
  Ekran klienta rozpoznaje ten przypadek po tekście `MSG_JOB_CLOSED`, bo 410 ma też wygasły link.
- **Kto na liście:** para z wierszem `cv_sent`, której bieżący etap nie jest
  w kolumnach „Zamknięte” ani „Zatrudnieni” (`board_column_for`, także etapy końcowe
  z nazwy), bez `hidden`. `?c=<public_id>` nie jest sekretem, zastępuje tylko
  `candidate_id` w adresie. `show_other_candidates=false`: lista tylko z tą osobą.
- **Dowód wyłącznie z CV** (`client_panel_evidence`, czyste funkcje, bez AI):
  `project` = opis doświadczenia z firmą i datami, `list` = umiejętności, certyfikaty,
  języki, `none` = brak albo odrzucone przez DL-a. Wejściem jest HTML CV etapu,
  ten sam, z którego renderuje się plik, także dla pliku wgranego. Ramka „Dlaczego
  nasz kandydat”, edukacja i klauzula zgody nie są dowodem; screening i notatki nie
  mają tu w ogóle drogi. Nigdy „kandydat powiedział w rozmowie”.
- **Dopasowanie:** pętle pogrubiania z `docx_renderer`, a wymaganie bez technologii
  po rdzeniach słów z granicą wyrazu. „Webhook” nie jest aplikacją webową, BigQuery
  do analiz nie jest chmurą, Linux z samego certyfikatu to `list`, GitLab nie jest
  Gitem. Synonim pojęcia = wpis w `_CONCEPTS` z testem, nie luźniejszy wzorzec.
  Słaby dowód dla DL-a (`weak`): sama lista albo sam wiersz „Technologie:”.
- **Stawka to stawka do klienta** (`latest_client_rates`) za wyłącznikiem `show_rate`.
  Oczekiwania kandydata, telefon i e-mail nie mają w odpowiedzi publicznej żadnego
  pola. Odpowiedzi publiczne powstają z jawnych list pól; pilnuje tego
  `test_public_panel_shape_has_no_private_fields`.
- **CV blind:** imię i nazwisko jak w `public_view` („Kandydat”), nazwa pliku `CV.pdf`,
  certyfikaty tylko po wskazaniu przez DL-a, bo noszą nazwisko.
- **CV w panelu to plik z „Pobierz”** (zatwierdzona wersja albo szkic), jako PDF
  bez ramki. Blokada zgody RODO działa jak przy pobraniu: bez zgody `cv.available =
  false`, a osoba zostaje na liście. Pliki: tylko wskazane przez DL-a
  (`shared_document_ids`, „Pliki dla klienta” w oknie), także certyfikaty, bo rodzaj
  dokumentu ustawia ręcznie rekruter; wszystko inne 404.
- **Terminy idą drogą DL-a.** `services/interview_slot_requests.py` jest wspólny dla
  `POST /interview-cycle/slots` i panelu: `normalize_slots`, limit 6, karta sama na
  „Rozmowę u klienta”, dzwonek rekrutera, „Klient milczy” wraca. Aktorem jest DL
  rekrutacji; bez DL-a wniosek powstaje bez ruchu karty. Otwarty wniosek = 409,
  klientowi bez `open_request_id`. Klient widzi wybrany termin dopiero po potwierdzeniu.
  „Nie pasuje” niczego nie przesuwa, decyzja zostaje u DL-a.
- **Siatka terminów zaczyna się od dziś** (04.11.2026, zgłoszenie z testu panelu;
  wcześniej od jutra). Dziś do wyboru są tylko godziny, które się jeszcze nie zaczęły, bo
  `normalize_slots` odrzuca termin przeszły (`slotWeeks` w `panel-logic.ts`). Bez minimalnego
  wyprzedzenia: o 15:51 można wskazać 16:00.
- **Autor jest niezweryfikowany.** Na wpisany adres nic nie wychodzi samo. Mail
  z odpowiedzią wychodzi tylko po kliknięciu DL-a, bez linku do panelu i bez nazwiska;
  adres spoza domen kontaktów klienta ma `email_domain_known=false`. Dzwonek i mail
  do DL-a (`client_panel_request`, rodzaj `client_interview`) nie niosą treści od
  autora. Dzienny limit zapisów panelu: 30 (429), `allow_actions=false` = 403.
- **Dziennik wejść** bez surowego IP (SHA-256 z IP i soli dnia), retencja 180 dni
  w `tasks/queue_retention.py`.
- **Bez AI w żądaniu publicznym.** Testów umiejętności nie budujemy (odłożone).

Przegląd bezpieczeństwa (02.11.2026): `/k/` jest w `capabilityPath` w `lib/sentry-privacy.ts`, bo nagrania sesji niosłyby żywy token. Nowa publiczna trasa z sekretem w ścieżce = wpis tam też.
