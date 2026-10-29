# Ogłoszenia na pulpicie — publikują HoR i admin, komunikatora nie budujemy (28.10.2026)
<!-- indeks: tabele announcements + announcement_reads (0618); panel nad kafelkami jak P0, znika bez aktywnych; odbiorcy wszyscy albo role; przeczytane per osoba schodzi niżej i szarzeje; „ważne” = dzwonek announcement_important + mail obowiązkowy „announcement” raz; odczyt bez bramki sekcji (wyjątek), zapisy sekcja Rekrutacje + HoR/admin; to nie care_announcements -->

Propozycja Olafa z 28.10.2026 („strefa OGŁOSZENIA na pulpicie każdego…
może przeniesiemy tam komunikator firmowy?”). Artur zatwierdził sam panel
ogłoszeń. **Komunikatora nie budujemy**: Teams niesie rozmowy z klientem,
prepy z transkryptem i kalendarz M365, a NEXUS ma już czaty rekrutacji
i kandydata oraz okienko „Wiadomości”. Przegląd z rysunkiem:
https://claude.ai/artifact/TY5MJmR9n8rbFtSBDGgYDT (sekcja 4).

To **nie są** „Komunikaty” z Ludzi (`care_announcements`, maile do
konsultantów bez konta) — osobne tabele, osobne trasy.

## Decyzje

- **Publikują Head of Recruitment i administrator** (`announcements.PUBLISH_ROLES`):
  tytuł (3–160 znaków), treść (zwykły tekst do 4000 znaków, znaczniki HTML
  odrzucone, front pokazuje ją jako tekst), „widoczne do” (data w kalendarzu
  firmy, włącznie, najdalej 90 dni), odbiorcy (wszyscy albo wybrane role),
  „Przypnij”, „Ważne”. Poprawka i „Zdejmij przed terminem” — każdy
  publikujący, tylko na aktywnym ogłoszeniu (inaczej 409).
- **Panel nad kafelkami** (`AnnouncementsPanel` w `CustomDashboard`, zaraz pod
  panelem P0), niezależny od własnego układu; znika, gdy nie ma aktywnych
  ogłoszeń. Przycisk „Ogłoszenie” w nagłówku pulpitu widzą tylko publikujący —
  panel może nie istnieć, więc wejście do publikacji stoi w nagłówku.
  Od razu 3 ogłoszenia, reszta pod „Pokaż wszystkie”.
- **Przeczytane per osoba** (`announcement_reads`). Kolejność z serwera:
  nieprzeczytane nad przeczytanymi, w grupie przypięte, potem najnowsze.
  Przeczytane szarzeje i zostaje do końca dnia „widoczne do”.
- **Publikujący widzą wszystkie aktywne** (także nie do siebie, z „do: …”)
  i „przeczytało N z M”; M = aktywne konta, do których ogłoszenie jest
  skierowane, liczone przy odczycie.
- **„Ważne”** = dzwonek `announcement_important` (kategoria „Konto i system”,
  obowiązkowa) i mail obowiązkowy rodzaju `announcement` (`REQUIRED_KINDS`,
  `BELL_MAIL_TYPES`) od razu do odbiorców, bez autora — ta sama ścieżka co P0.
  Wychodzi **raz** na ogłoszenie (`notified_at`): „Ważne” dodane w poprawce
  dzwoni, kolejna poprawka już nie. Typ jest w
  `ALWAYS_VISIBLE_NOTIFICATION_TYPES`, bo odbiorców wybiera rola z ogłoszenia,
  nie sekcja.

## Jak działa

- Ogłoszenie obowiązuje, gdy `withdrawn_at IS NULL` i `visible_until >=
  business_today()` (`announcements.live_clause`). Po terminie znika samo,
  bez pętli w tle. Zdjęcie zostawia wiersz (ślad).
- Trasy (`api/announcements.py`): `GET /api/announcements` i `POST
  /api/announcements/{id}/read` **bez bramki sekcji** — pulpit ma każde
  konto, także „Pracownik” i Rada; wyjątek opisany w `_BARE_BASELINE`
  (`tests/test_route_authz_contract.py`). Odbiorców filtruje serwer,
  „Przeczytane” na cudzym albo wygasłym ogłoszeniu = 404.
  `POST /api/announcements`, `PATCH|DELETE /api/announcements/{id}` — sekcja
  Rekrutacje + `HeadOfRecruitmentPlus` (wzorzec `authz_golden/announcements.json`).
- Historia zdarzeń: `announcement_published`, `announcement_edited`,
  `announcement_withdrawn` (`entity_type="announcement"`).
- Schemat: `services/announcements_schema.py` (jedno źródło dla migracji 0618,
  modelu i `entrypoint.sh`). Testy: `tests/test_announcements.py`,
  `AnnouncementsPanel.test.tsx`, `lib/__tests__/announcements.test.ts`.
