# Powiadomienia dla ról i jeden ekran „Powiadomienia” — raport (09.10.2026)

## Skąd to zgłoszenie

Admin poprosił o „możliwość wybrania, do jakiej roli mają iść powiadomienia”.
Odpowiedź „masz to w ustawieniach” okazała się nieprawdziwa:

| Ekran przed zmianą | Co robił | Wybór roli |
|---|---|---|
| Moje konto → Moje powiadomienia | każdy wycisza kategorie dzwonka tylko sobie | nie |
| System → Powiadomienia | włącza i wyłącza maile całej firmie, bez słowa o zasięgu | nie, odbiorcy to opis |
| Procesy rekrutacyjne → etap → Powiadomienia | reguły wejścia kandydata na etap | tak, ale tylko tu |

Reguł etapów na produkcji było 10, wszystkie z zasiewu z kwietnia, żadna nie
została zmieniona. Szukając ustawienia roli, zgłaszająca osoba 09.10 o 10:21
wyłączyła „Poranny skrót” — przełącznik działał na całą firmę (28 odbiorców)
i nie pytał o potwierdzenie.

Pomiar z produkcji, 30 dni do 09.10.2026:

- każdy z 7 adminów dostawał ok. 205 alertów końca zamówień i umów
  (1 237 łącznie), przeczytanych w 8%; Delivery Leadzi czytali te same alerty w 43%;
- konto zgłaszającej: 302 powiadomienia, 1 przeczytane; po własnym wyciszeniu
  czterech kategorii zostawało jej 263 (87%);
- wyciszenia osoby miało 1 konto z 34.

Makiety (stan „dziś” i propozycja): https://claude.ai/artifact/TRKAAZX3RcB8AA7LVohkT8

## Decyzje Artura (09.10.2026)

1. Przywrócić poranny skrót.
2. Zdjąć adminów z alertów końca zamówień i umów.
3. Zbudować ekran z makiety.
4. Konto zgłaszającej zmienić z Admina na Finanse (bez dodatkowych uprawnień).
5. Zmiany na produkcji wykonuje sesja przez API jako konto administratora 82.

## Zmiany na produkcji (09.10.2026, 11:20 czasu warszawskiego)

- `PUT /api/settings/notification-delivery` — `daily_digest` włączony; pozostałe
  rodzaje maili bez zmian. Dzisiejszy bieg miał już status `sent` (27/27) i nie
  powtórzył się. Następny skrót: poniedziałek 12.10, 8:00.
- `PUT /api/admin/users/39` — rola `finance`. Skutki uboczne samego handlera:
  wylogowanie konta, skasowanie 901 powiadomień z dzwonka, `recruiter_id = NULL`
  na 53 zamkniętych rekrutacjach. `can_delete_clients` zostało `true`.
- Rekrutacje, z których konto 39 zostało zdjęte jako prowadzące (jedyna droga
  odwrócenia): 3058, 9027, 9052, 9058, 9074, 9094, 9096, 9098, 9132, 9192, 9193,
  9196, 9214, 9222, 9238, 9284, 9285, 9286, 9305, 9329, 9330, 9336, 9337, 9349,
  9362, 9375, 9380, 9385, 9417, 9418, 9424, 9431, 9449, 9455, 9502, 9523, 9528,
  9553, 9583, 9593, 9607, 9625, 9630, 9650, 9666, 9728, 9773, 9777, 10027,
  383095, 383097, 383102, 383127.

## Co weszło w PR-ze

**Alerty umów.** Dzwonek końca zamówienia, umowy, umowy ramowej, zwrotu
sprzętu i szkicu kontraktu po zatrudnieniu idzie do Delivery Leadów klienta.
Admin dostaje go tylko wtedy, gdy żaden DL klienta nie może dostać tego typu:
klient bez DL-a, umowa bez klienta, DL z wyciszoną kategorią albo grupą
wyłączoną dla roli (`DeliveryAlertRecipientScope.bell_recipients`).

**Kto co dostaje.** Administrator wyłącza grupę powiadomień dla całej roli
(`app_settings['notification_role_mutes']`, `GET/PUT
/api/settings/notification-roles`). Konto z kilkoma rolami traci grupę dopiero,
gdy jest wyłączona we wszystkich jego rolach. Zapis ma wersję (409 przy
konflikcie) i wpis w Historii zdarzeń.

**Maile.** Każdy przełącznik ma plakietkę „cała firma”, wyłączenie pyta
o potwierdzenie i podsuwa drogę „tylko sobie”, a zmiana zostawia wpis
w Historii zdarzeń. Ekran pokazuje, kto i kiedy zmienił ostatnio.

**Własny wyłącznik porannego skrótu.** `users.daily_digest_email_enabled`
(migracja 0425 + lustro w `entrypoint.sh`), przełącznik w zakładce „Moje”.

**Jeden ekran.** `/settings?item=notifications` i `/settings?item=my-notifications`
otwierają ten sam ekran z zakładkami Moje · Kto co dostaje · Maile · Reguły etapów.

## Odstępstwo od planu

Wiersz z wyłączeniami ról jest czytany przy każdym liczeniu dostępu, bez
pamięci podręcznej (plan zakładał 30 s). To jedno zapytanie po kluczu głównym
na żądanie; w zamian zmiana działa od następnego żądania, tak jak reszta
polityki dostępu.

## Poza zakresem

- „Kandydat stoi na etapie 6 h”: 5 554 powiadomienia w 30 dni do dwóch kont
  z rolą Head of Recruitment. To zapas, gdy rekrutacja nie ma aktywnego
  Delivery Leada, powtarzany codziennie przez 14 dni. W tabeli ról da się tę
  grupę wyłączyć, ale konto z trzema rolami straci ją dopiero po wyłączeniu
  we wszystkich trzech. Zmiana samej reguły to osobna decyzja.
- Wyciszenia osoby zostają na poziomie kategorii; grupy są tylko w tabeli ról.
- Rola nie może zostać dopisana jako odbiorca dowolnego powiadomienia.
  Większość z nich jest imienna (rekruter kandydata, Delivery Lead rekrutacji).
- Nocny sync Traffita może wpisać konto 39 z powrotem jako prowadzące na
  części z 53 zamkniętych rekrutacji (dopełnia pustego prowadzącego po
  e-mailu). To archiwum; do sprawdzenia odczytem nazajutrz.

## Weryfikacja

- Produkcja: oba zapisy sprawdzone odczytem z bazy (rola i lista ról konta 39,
  wpis `role_changed`, `daily_digest.email_enabled = true`, brak drugiego biegu
  skrótu 09.10).
- Backend lokalnie (Python 3.12, bez bazy): reguła ról i grup, zapas przy
  dzwonku umów, lustro migracji 0425, strażnicy tras (`test_section_ceiling_contract`,
  `test_route_authz_contract`, `test_authz_guard_matrix` z nowym wzorcem),
  stemple instrukcji zamówień, `ruff check` i `ruff format --check`.
- Backend z bazą (zapis tabeli ról przez API, skaner wygasania, wyłącznik
  skrótu): tylko w CI — na tym komputerze nie stawiamy Postgresa.
- Frontend: testy ekranu, tabeli, rejestru ustawień, harnessów i strażników
  (500 testów), `tsc --noEmit`, `next lint` bez ostrzeżeń w zmienionych plikach.
- Przeglądarka, harness `/preview/notification-settings`: tabela ról przy
  1280 px (przełącznik → szkic → „339 na osobę, było 359” → okno potwierdzenia),
  zakładka „Maile” z oknem „Wyłączasz ten mail 21 osobom”, zakładka „Moje”
  jako rekruter (wiersz „Wyłączone dla Twojej roli”, własny wyłącznik skrótu),
  telefon 375 px — strona bez poziomego przewijania, tabela przewija się
  w swoim kontenerze.
- Przegląd kodu backendu: dwie uwagi blokujące w regule zapasu (alert bez
  odbiorcy przy wyciszonym DL-u, konto Admin + DL) — obie naprawione z testami.
- Niepotwierdzone do wdrożenia: zapis tabeli ról na produkcji i spadek liczby
  alertów umów u adminów (do sprawdzenia dobę po wdrożeniu).
