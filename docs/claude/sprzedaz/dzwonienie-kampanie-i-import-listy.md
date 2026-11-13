# Dzwonienie: kolejka, kampanie i import listy — decyzje Artura 10.11.2026
<!-- indeks: Nie zainteresowany z powrotem za pół roku albo nigdy, Zły numer, klawisze 1–7, licznik Dziś bez celu, widok Tabela, LinkedIn z importu, zakładka Dzwonienie, sales_call_campaigns, sales_call_records, wynik rozmowy nie jest szansą, oferta ogólna wysłana = wpis kolejki, szansa z umówionego spotkania, sześć wyników i CALL_OUTCOMES, oddzwonienie po 3 dniach roboczych, spotkania bez terminu, szanse z etapu Lead w kolejce, import CSV/xlsx z bramkami, Skąd kontakt, klient NEXUSA do Delivery Leada, bez celu dziennego i przełącznika osoby -->

Rekomendacje A1 i A2 z przeglądu Sprzedaży (prywatny artefakt z makietami:
https://claude.ai/artifact/PEfTGijHaxrPDZS2mkxKty). Powód: dwie osoby dzwoniące założyły
94 szanse w 3 dni robocze, bo wynik telefonu dało się zapisać tylko jako szansę. Kolumna
„Lead” w 80% składała się z „Oferta ogólna wysłana”, a dziennik rozmów miał 0 wpisów.

Kod: `backend/app/services/sales/calling.py` (kolejka, wynik), `calling_file.py` (odczyt
pliku), `calling_import.py` (bramki), `backend/app/api/sales_calling.py`, front
`frontend/src/components/sales/calling/`, trasa `/sales/calling`. Migracja 0681, DDL w
`sales_schema.CALLING_DDL` (lustro w `entrypoint.sh`).

## Co jest szansą, a co wpisem kolejki

- **Wynik telefonu nie jest szansą.** „Oferta ogólna wysłana” to stan rekordu z datą
  oddzwonienia. **Szansa powstaje dopiero z umówionego spotkania.** Nie dodawaj ścieżki,
  która z wyniku rozmowy zakłada szansę na etapie „Lead”.
- **Kampania** (`sales_call_campaigns`) to usługa, lista i skrypt rozmowy. **Rekord**
  (`sales_call_records`) to firma, osoba, telefon, „skąd kontakt”, stan, data
  oddzwonienia i kto dzwoni. Rekord zawsze ma kartę firmy; osoba z nazwiskiem dostaje
  też kontakt w kartotece, bo sprzeciw („Nie kontaktować”) leży przy kontakcie.
- **Jeden słownik wyników:** `sales_schema.CALL_OUTCOMES` i `calls.OUTCOME_LABELS`
  (front: `CALL_OUTCOME_LABELS`). Kolejka używa `no_answer`, `call_back`, `not_now`,
  `do_not_contact` i dokłada `offer_sent` oraz `meeting_booked`. Stan rekordu to `new`
  albo ostatni wynik. Każdy wynik zapisuje też telefon w `sales_activities`, więc
  rozmowy z kolejki liczą się tak samo jak te z karty szansy.

## Kolejka

> 13.11.2026: kolejka ma wybór osoby, wynik zapisuje każdy z „Sprzedaż: edycja”,
> „Nie zainteresowany” i „Nie teraz” zdjęte, „Nie odebrane” to osobna sekcja, a oferta
> zakłada lead w Leadach: `dzwonienie-lista-zmian-od-dzwoniacych-13-11.md`.

- **Zawsze zalogowanej osoby, w stałej kolejności:** oddzwonienia na dziś, spotkania bez
  terminu, nowe rekordy kampanii. Bez celu dziennego, paska postępu, rankingu i
  przełącznika „pokaż osobę”: to narzędzie pracy, nie kontroli (jak „Mój dzień”).
- **Listy widzi cała Sprzedaż** (decyzja Artura 12.11.2026): Tabela ma zakres „Moje /
  Wszyscy” (`GET /records?scope=all&caller_id=`) z kolumną „Kto dzwoni” i filtrem osoby,
  dla każdego z „Sprzedaż: podgląd”, żeby handlowiec wiedział, do jakich firm i kto dzwoni.
  Karta firmy pokazuje „Na liście dzwonienia” (`GET /companies/{id}/records`: osoba,
  kampania, wynik, powrót, bez numeru). Sprzeciw nie wychodzi także w „Wszyscy”.
  Od 13.11.2026 wynik w cudzym rekordzie i cudzej kolejce zapisuje każdy z „Sprzedaż:
  edycja” (wcześniej tylko przypisana osoba albo admin), a kolejka ma wybór osoby.
- **Nic nie dzwoni i nie wysyła się samo.** Dzwonimy z telefonu, nie z NEXUSA (decyzja
  Artura 12.11.2026): karta pokazuje numer i „Kopiuj numer” zamiast linku `tel:`, a wiersz
  kolejki nie ma etykiety „Zadzwoń”. Lead ani rekord nie dają prawa do zimnego kontaktu
  (art. 398 PKE).
- **Daty powrotu** liczy serwer w kalendarzu firmy: „Nie odebrał” następny dzień roboczy,
  „Oferta ogólna wysłana” za 3 dni robocze, „Oddzwonić” i „Nie teraz” w wybranym dniu
  (bez daty: następny dzień roboczy i 30 dni). Brak daty nie blokuje zapisu, data
  w przeszłości to 422. Rekord wraca sam w swoim dniu.
- **Szanse dzwoniącego z etapu „Lead”** (lejek Sprzedaż) też są w kolejce, żeby dało się
  je obdzwonić przed jednorazowym przeniesieniem (A7, osobna decyzja). Bez wyniku z
  kolejki wracają 3 dni robocze po założeniu i stoją za oddzwonieniami z ustaloną datą,
  od najnowszej (świeża oferta jest więcej warta niż wpis z importu sprzed miesięcy). Pierwszy wynik zakłada rekord bez kampanii
  (jeden na szansę, `ux_sales_call_records_opportunity`), a telefon ląduje w dzienniku
  tej szansy. O tym, czyja to pozycja, decyduje opiekun szansy, nie pole rekordu.
- **„Spotkania bez terminu”** to otwarte szanse tej osoby na etapie „Spotkanie
  kwalifikujące”, których firma nie ma w NEXUSIE spotkania od dnia założenia szansy.
  Pomija te same wyniki co szanse z etapu „Lead”: sprzeciw, „Zły numer” i „Nie
  zainteresowany” bez daty powrotu; z datą wraca w swoim dniu. Bez tego pozycja wracała
  po „Nigdy”, a każde kolejne naciśnięcie liczyło się w „Dziś” i Skuteczności (audyt 12.11.2026).
  Karta daje pole terminu: zapis to zwykła aktywność `meeting`, która jest też krokiem
  szansy (`next_step.py`).
- **„Umówione spotkanie”:** rekord kampanii otwiera `OpportunityFormDialog` z etapem
  „Spotkanie kwalifikujące”, kontaktem, źródłem „Dzwonienie” i nazwą kampanii, a wynik
  zapisuje się z `opportunity_id` (bez niego 422, bo rekord zniknąłby bez śladu).
  Szansa z etapu „Lead” przechodzi na etap spotkania z wpisem w historii. Formularz
  „Umów spotkanie” z pakietu „Przekazanie i werdykt” podmienia tu tylko okno.
- **Sprzeciw zdejmuje pozycję z kolejki, skądkolwiek przyszedł** (`_without_objection`):
  osoba z `do_not_contact_at` i firma ze statusem „Nie kontaktować” nie są listowane,
  więc numer nie trafia do odpowiedzi API. Nie zastępuj tego ukryciem numeru na froncie.
- **Odmowy:** cudzy rekord 403 (zapisuje osoba przypisana albo admin), rekord zamknięty
  409, osoba albo firma ze sprzeciwem 409 (poza samym „Nie kontaktować”), firma, która
  jest klientem NEXUSA, przy „Umówionym spotkaniu” 409 z nazwą Delivery Leada, szansa
  zamknięta albo innej firmy przy „Umówionym spotkaniu” 422.

## Import listy

- **To nie jest silnik leadów.** Listę przygotowuje człowiek i musi podać „Skąd kontakt”
  (zapis przy każdym rekordzie). Bez tego pola import to 422; sam podgląd go nie wymaga.
- **Najpierw los każdego wiersza, potem zapis.** Podgląd niczego nie zapisuje, a zapis
  liczy plan jeszcze raz pod jedną blokadą importu (`pg_advisory_xact_lock`), więc drugi
  klik ani import tej samej listy do innej kampanii niczego nie dubluje.
  Pliku nie trzymamy na serwerze między krokami: przeglądarka wysyła go drugi raz.
- **Bramki, pierwsza pasująca decyduje:** sprzeciw (firma, osoba, ten sam numer albo
  adres także przy innej firmie), klient NEXUSA albo nasza spółka (`client_gate`, sprawa
  dla Delivery Leada), już w kampanii (także powtórka w pliku i własna otwarta szansa),
  dzwoni ktoś inny (cudzy otwarty rekord albo cudza otwarta szansa), brak telefonu.
  Reszta to „Połączono z kartą” (domena, potem NIP, potem nazwa z dołączonymi nazwami
  z CV) albo „Nowa firma”. Do kolejki trafiają tylko dwie ostatnie grupy.
- **Karta firmy z importu** dostaje domenę ze strony albo z adresu osoby (nie z poczty
  publicznej). Pustą domenę istniejącej karty import uzupełnia, nigdy nie nadpisuje.
- **Plik walidowany na granicy:** tylko `.csv` i `.xlsx`, 2 MB, 2000 wierszy, 60 kolumn,
  10 MB po rozpakowaniu xlsx, znaki sterujące i długości komórek. Trasy mają limit
  zapytań, dlatego moduł API nie ma `from __future__ import annotations`.
- **Logi są publiczne:** import loguje same liczby.

## Po Excelu dzwoniących — decyzje Artura 11.11.2026

Powód: osoby dzwoniące prowadziły arkusz na osobę (kolor wiersza = wynik, komentarz ręcznie,
wiersz „Podsumowanie” dnia wpisywany ręcznie). Makiety: https://claude.ai/artifact/5yiSa8H1BW5v2iewpKFFHX.

- **Dwa nowe wyniki** (migracja 0683, DDL `sales_schema.CALL_OUTCOMES_V2_DDL`):
  „Nie zainteresowany” (`not_interested`) wraca do kolejki domyślnie za pół roku, do wyboru
  3 / 6 / 12 miesięcy albo **nigdy** (`never: true`, rekord bez daty nie wraca). To nie jest
  sprzeciw: firma i osoba zostają do kontaktu inną drogą. „Zły numer / brak danych”
  (`bad_contact`) zamyka rekord. „Nie zainteresowany” z datą nie wlicza się do „wróci w swoim
  dniu”, bo pół roku czekania setek osób zasłoniłoby ten licznik.
- **Klawisze 1–7** zapisują wynik w kolejności przycisków (`calling.KEYED_OUTCOMES`), potem
  karta przechodzi do następnej osoby. W polu tekstowym i przy otwartym oknie klawisz jest
  zwykłym znakiem. „Umówione spotkanie” z klawisza otwiera to samo okno szansy.
- **Licznik „Dziś”** (telefony · rozmowy · oferty · spotkania, obok poprzedni dzień roboczy)
  to świadomy wyjątek od „bez paska postępu”: sam licznik, **bez celu i bez porównania
  z innymi**. Liczy jak „Skuteczność”: rozmowa = wynik inny niż „Nie odebrał” i „Zły numer”, spotkanie raz
  na szansę. Ranking osób jest tylko na ekranie „Skuteczność”.
- **Widok „Tabela”** (przełącznik obok filtra kampanii): wszystkie rekordy osoby
  (`GET /api/sales/calling/records`) z filtrem po wyniku i licznikami, kolory jak w legendzie
  Excela, klik w wiersz otwiera tę samą kartę. Sprzeciwu nie ma w tabeli ani w licznikach,
  bo numer nie może wyjść z API. Szanse z etapu „Lead” bez żadnego wyniku z kolejki nie
  mają jeszcze rekordu, więc w tabeli ich nie ma (są w kolejce).
- **LinkedIn**: import czyta kolumnę „LinkedIn” (tylko adres `linkedin.com` po http/https),
  zapisuje go przy kontakcie (pusty uzupełnia, istniejącego nie nadpisuje), karta pokazuje
  przycisk „LinkedIn”.
- **Przeniesienie samego Excela** (arkusz = osoba, kolor = wynik) to osobny, jednorazowy krok
  z biegiem na sucho; zapis na produkcji tylko po zgodzie Artura.

## Nowość do przeklikania

Wpis `sprzedaz-dzwonienie-kolejka` (poziom `tour`, odbiorcy „Sprzedaż: edycja”) chodzi po
kotwicach `sales.calling.queue`, `sales.calling.outcomes` i `sales.calling.import`. Krok
z wynikami ma `ack`, bo klik w wynik zapisałby prawdziwą rozmowę. Użycie w pracy zalicza
klik w wynik (`used_anchor`).

## Poza zakresem (osobne decyzje)

Wysyłka oferty ogólnej z NEXUSA (A5), karta rozmowy per usługa (A6), jednorazowe
przeniesienie istniejących „ofert ogólnych” do kolejki (A7: zapis na produkcji po biegu
na sucho i zgodzie Artura), integracja z centralką, „Nie kontaktować” na poziomie firmy
z ekranu (D4; import i kolejka czytają już `sales_companies.status`).

Testy: `backend/tests/test_sales_calling_queue.py`, `test_sales_calling_import.py`,
`test_sales_calling_file.py`, `frontend/src/components/sales/__tests__/sales-calling.test.tsx`.
