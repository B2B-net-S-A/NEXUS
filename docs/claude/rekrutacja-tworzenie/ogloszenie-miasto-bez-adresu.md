# Miasto w ogłoszeniu bez adresu biura klienta (28.10.2026)

<!-- indeks: public_city, „Miasto w ogłoszeniu”, content.city, kontrola „address” -->

Zgłoszenie rekruterki: dokładny adres w ogłoszeniu pozwala po wygooglowaniu
rozpoznać klienta. Lokalizacja rekrutacji bywa adresem biura
(„Warszawa, ul. Kwiatowa 12”, „Siedziba klienta, al. Przykładowa 7,
00-950 Warszawa”) i szła w całości do ogłoszenia, maila do opiekuna
Pracuj.pl, JustJoin.IT i strony kariery. Na stagingu 22.10: 24 z 204
otwartych rekrutacji. Decyzje Artura 28.10.2026 (makiety
https://claude.ai/artifact/5pGFGYC8vinSANdsF52ugB).

- **Samo miasto** — `services/public_city.py`, użyte w
  `job_public_profile.public_params`. Lokalizacja bez adresu zostaje bez
  zmian (także opisowa). Z adresem zostają miasta rozpoznane w słowniku
  `pl_places` („Warszawa lub Lublin”); bez rozpoznanego miasta — pusto, nigdy
  adres. „Miasto, Nazwa 12” liczy się jako adres tylko, gdy przed przecinkiem
  stoi miasto — inaczej „ASP.NET Core 8, Angular 17” byłoby ulicą.
- **Odcisk materiału się nie zmienia.** `AdMaterial.location` niesie
  lokalizację sprzed wycięcia i `material_hash` liczy z niej pole `city`.
  Bez tego każde ogłoszenie z adresem dostałoby „Rekrutacja zmieniła się…
  Przygotuj ponownie”, a to nadpisuje ręczne poprawki. Strona kariery
  zatwierdzona z adresem dalej pokazuje migawkę z zatwierdzenia
  (`_SNAPSHOT_PARAMS`), a `approved_content_stale` mówi, że rekrutacja się
  różni — adres znika ze strony po ponownym zatwierdzeniu.
- **„Miasto w ogłoszeniu”** w „Warunkach w ogłoszeniu” (`content.city`):
  wpisane zastępuje miasto z rekrutacji w ogłoszeniu i mailu, puste = miasto
  z rekrutacji. Klucz zapisuje się tylko wpisany — `publications.content_hash`
  liczy się z całej treści.
- **Kontrola: uwaga `address`, nie blokada** (decyzja Artura). Ulica z numerem,
  „ul./al./pl./os.”, kod pocztowy — w polach treści, w polu miasta i w
  warunkach z rekrutacji. Nazwa ulicy w opisie projektu bywa niewinna.
