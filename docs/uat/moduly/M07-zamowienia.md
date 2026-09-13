# M07 — Zamówienia (jednoosobowe, wielo-konsultantowe, kosztowe, z maila)

| Pole | Wartość |
|---|---|
| Tryb | **R** — odczyt PDF w oknie „Nowe zamówienie” JEST dozwolony (nic nie zapisuje do „Zapisz”); zapisy → P3 |
| Persony | delivery_lead (D1, D2), finance, head_of_recruitment, tac, talent_community_manager (podgląd); admin |
| Zależności | Fala 0 (D1, D2 w `MULTI_CONSULTANT_ORDER_CLIENT_IDS`, PDF-y z fixtures); najlepiej po P3 (dane w zakładkach) |
| Czas | ~3,5 h |
| Głębokość | pełna — pieniądze |
| Akcje AI | tak — odczyt PDF (`/order-groups/extract`, `extract`) = model + polityki; ~1 kwota na odczyt. Limit: 6 odczytów. |

## Zakres

- Zakładka „Zamówienia” w profilu klienta — **DWA RÓŻNE WIDOKI**:
  - `MultiConsultantOrdersTab` dla klientów z `MULTI_CONSULTANT_ORDER_CLIENT_IDS` (D2): grupy
    zamówień (MD per osoba / wspólna pula / kosztowe), linie, zamiana kontraktora, cykl życia
    (`active/completed/exhausted`), historia, sprawy offboardingowe.
  - `OrdersAndContractsTab` dla pozostałych (D1): zamówienia jednoosobowe, „kontraktor bez zamówienia”.
- Okno „Nowe zamówienie” (`OrderGroupFormModal`): typ (MD / kosztowe / okresowe), PDF →
  „Zczytaj i uzupełnij całe zamówienie” → karty osób (`OrderPlanLineCard`) → JEDNO `POST`.
- Okno „Uzupełnij zamówienie” (tryb edycji) + „Zczytaj dane z dokumentu”.
- `NewContractorOrderDialog` (okresowe) z „Zczytaj dane z dokumentu”.
- `/order-mail` — kolejka maili: zakładki **Do weryfikacji · Nierozpoznane · Zapisane automatycznie · Zapisane ręcznie**; pasek „Pobierz zamówienia z maila” (**STOP**).
- `/finance?view=md` — import zużycia MD i kosztowy (odczyt tu, import w P3).
- Eksport Excel zamówień (`POST /api/clients/{id}/orders/export`).
- Pomoc → „Zamówienia — instrukcja dla Delivery Leada”.

## Przed startem

ID D1, D2; PDF-y: `zamowienie-jednoosobowe.pdf`, `zamowienie-wieloosobowe.pdf`, `zamowienie-kosztowe.pdf`;
`GET /api/clients/{{D2}}` → `multi_consultant_orders_enabled: true`, `GET /api/clients/{{D1}}` → `false`.
Jeden PRAWDZIWY klient wielo-konsultantowy z aktywną grupą MD (tylko ID) — do S20–S24.

## NIE KLIKAJ

„Zapisz”/„Utwórz zamówienie” w oknach (P3), „Zakończ zamówienie”, „Zakończ współpracę”,
„Przywróć”, „Zamień kontraktora” → Zapisz, „Usuń linię”, decyzje offboardingowe, cały pasek
i przyciski w `/order-mail` („Pobierz…”, „Przelicz plan”, „Zastosuj”, „Odrzuć”, „Rozstrzygnij w oknie
zamówienia” → Zapisz), „Importuj” w `/finance?view=md`. Natywne `window.confirm` zamraża automatyzację.

## Scenariusze — widok wielo-konsultantowy (D2)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | delivery_lead (D2) | `/clients/{{D2}}?tab=zamowienia` | widok GRUP; sekcje wg typu (MD / kosztowe / okresowe); przycisk „Nowe zamówienie” (typ domyślny = najczęstszy u klienta; bez historii = legacy) | P1 |
| S02 | delivery_lead (D2) | „Nowe zamówienie” → typ MD → wgraj `zamowienie-wieloosobowe.pdf` → „Zczytaj i uzupełnij całe zamówienie” (odczyt 1) | 3 karty osób (Anna Testowa 40 MD × 1200, Jan Próbny 30 × 1100, Piotr Wzorcowy 20 × 1300); numer `QA/002/2026`; bezterminowo (pole „do” puste); każda wartość ma źródło („z PDF, pozycja N”) | P1 |
| S03 | delivery_lead (D2) | na kartach: dopasowanie osoby do kontraktu | po P2/P3: D5 = `auto` (identyczna nazwa); przed P2: `none` z komunikatem „brak osoby u klienta” + propozycja „szkic nowego kontraktora” (`unknown_consultant_reason`) | P1 |
| S04 | delivery_lead (D2) | zmień ręcznie MD na karcie 1 na 45 | źródło zmienia się na „wpisano ręcznie”; przelicz kwoty poprawnie; **ANULUJ** | P2 |
| S05 | delivery_lead (D2) | „Nowe zamówienie” → typ kosztowe → `zamowienie-kosztowe.pdf` (odczyt 2) | kwota 150 000 na GRUPIE; 2 osoby bez pól MD; ŻADNEGO ostrzeżenia „brak liczby MD” (o polach decyduje typ); **Anuluj** | P1 |
| S06 | delivery_lead (D2) | „Nowe zamówienie” → przełącz typ na „Okresowe” po wgraniu PDF | plik przenosi się do `NewContractorOrderDialog` (`initialFile`) i z powrotem | P2 |
| S07 | delivery_lead (D2) | „Nowe zamówienie” MD → status domyślny | „Aktywne” (nie Draft); walidacja: każda linia z `input_value > 0` (sprawdź komunikat przy 0 — **bez zapisu**) | P2 |
| S08 | finance | `/clients/{{D2}}?tab=zamowienia` | odczyt; liczby MD (operacyjne) widoczne; stawki linii MD **„—”** (zarządza admin + DL przypisany), pasek zużycia widoczny | P1 |
| S09 | head_of_recruitment | jw. | odczyt; akcje cyklu życia WIDOCZNE (HoR w `_ORDER_LIFECYCLE_ROLES`), stawki „—”; **nie klikaj** | P1 |
| S10 | tac / talent_community_manager | jw. | odczyt; brak akcji cyklu życia; stawki „—” | P1 |
| S11 | delivery_lead NIEprzypisany do D2 | jw. | 403 z powodem (klient poza portfelem) | P1 |

## Scenariusze — widok jednoosobowy (D1)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S12 | delivery_lead (D1) | `/clients/{{D1}}?tab=zamowienia` | widok jednoosobowy (karty kontraktorów); „kontraktor bez zamówienia” ma EDYTOWALNE numer/okres/stawki (pierwszy zapis zakłada szkic — **nie zapisuj**) | P1 |
| S13 | delivery_lead (D1) | „Nowy kontraktor / zamówienie” → wgraj `zamowienie-jednoosobowe.pdf` (odczyt 3, automatyczny po wgraniu) | pola PUSTE uzupełnione: `QA/001/2026`, 01.10.2026–31.12.2026, 1200 PLN/MD, 60 MD; stawka KOSZTOWA pusta (nie pochodzi z dokumentu); `client_policy` = null → komunikat „klient nie ma jeszcze własnych reguł, sprawdź pola” WIDOCZNY | P1 |
| S14 | delivery_lead (D1) | jw. → ręcznie zmień numer na `X` → „Zczytaj dane z dokumentu” (odczyt 4) | przycisk NADPISUJE (świadoma prośba) → numer wraca na `QA/001/2026`; **Anuluj** | P2 |
| S15 | delivery_lead (D1) | eksport Excel zamówień | plik z zamówieniami OBOWIĄZUJĄCYMI dziś, jedno na konsultanta; „kończące się” obecne; zakończone nieobecne; wiersz zbiorczy grupy (jeśli grupa) zostaje | P1 |

## Scenariusze — cykl życia i historia (prawdziwy klient wielo-konsultantowy, tylko odczyt)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S20 | admin | aktywna grupa MD: pasek MD per linia | `md_remaining` = `md_total − Σ konsumpcji + korekta` (sprawdź w API `GET …/order-groups`); poniżej zera = kolor ostrzegawczy, nie ucięcie | P1 |
| S21 | admin | historia grupy (dialog) | zdarzenia PL: dodanie konsultanta, zamiana, zakończenie; autor jako rola+ID; brak surowego JSON | P2 |
| S22 | admin | linia osoby z zakończoną współpracą | pod osobą zdanie „wykorzystał(a) X zł / Y MD … — ta kwota nie wraca do puli” (kwota tylko z dostępem do finansów) | P2 |
| S23 | admin | grupa `completed` z `closure_reason` „Wszyscy konsultanci wyczerpali limit MD” (jeśli istnieje) | status „Zakończone”, przycisk „Przywróć” daje 409 z instrukcją — **nie klikaj**, sprawdź tooltip/disabled | P3 |
| S24 | admin | grupa `exhausted` (wspólna pula; jeśli istnieje) | brak „Przywróć”; sugerowana korekta kwoty / nowe zamówienie | P3 |
| S25 | admin | sprawa offboardingowa `pending` (jeśli istnieje) | 3 decyzje: usuń / przenieś / przywróć; przy „przywróć” z zamówieniem z datą końca — pole daty WYMAGANE; **nie zapisuj** | P2 |

## Scenariusze — kolejka maili `/order-mail` (tylko odczyt)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S26 | delivery_lead | `/order-mail` → 4 zakładki | ładują się; liczby w pasku (nowe / zapisane automatycznie / do weryfikacji) dotyczą CAŁEJ skrzynki — kolejka DL zawężona do portfela, więc „1 do weryfikacji” + pusta lista to NIE sprzeczność | P1 |
| S27 | delivery_lead | wpis „Do weryfikacji” → szczegóły | plan z powodami PL; podgląd PDF (`/queue/{id}/file` z Bearer); `rule_versions` w meta; przyciski „Przelicz plan”/„Zastosuj” WIDOCZNE, **nie klikaj** | P1 |
| S28 | delivery_lead | wpis z `ACTION_DECIDE_PERSON` (jeśli jest) | „Zastosuj” WYŁĄCZONE; przycisk „Rozstrzygnij w oknie zamówienia” prowadzi do `/clients/{id}?tab=zamowienia&orderMailDoc={doc}` — **nie klikaj dalej** | P2 |
| S29 | admin | `GET /api/order-mail/sync/status` | `auth_mode: app`, `app_only_ready: true`, `last_status`, `finished_at`; `running` bez blokady = „przerwany” | P1 |
| S30 | talent_community_manager | `/order-mail` | odczyt bez treści błędów (cytują nazwy załączników); brak „Pobierz” | P1 |
| S31 | recruiter | `/order-mail` ręcznie | odmowa (sekcja delivery) | P1 |

## Scenariusze — import MD (odczyt)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S32 | finance | `/finance?view=md` | widok importu z historią; wiersze `Wymaga przypisania` (jeśli są) z przyciskiem przypisania; **nie importuj** | P1 |
| S33 | admin | historia importów — gałąź pustego stanu | pojawia się TYLKO po `isSuccess` (nie w przerwie ponowień) — sprawdź, przeładowując z throttlingiem sieci „Slow 3G” w DevTools | P2 |
| S34 | delivery_lead | `/finance?view=md` | odmowa (`/finance` = ADM, FIN) | P1 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const g = await fetch('https://api.nexus.dynaminds.pl/api/clients/{{D2}}/order-groups',{headers:h}).then(r=>r.json());
console.log('grupy D2:', g.items?.length ?? g.length, 'suggested:', g.suggested_order_type);
const c1 = await fetch('https://api.nexus.dynaminds.pl/api/clients/{{D1}}',{headers:h}).then(r=>r.json());
console.log('D1 multi:', c1.multi_consultant_orders_enabled, 'cost:', c1.cost_orders_enabled);
const st = await fetch('https://api.nexus.dynaminds.pl/api/order-mail/sync/status',{headers:h}).then(r=>r.json());
console.log(st.auth_mode, st.app_only_ready, st.last_status, st.finished_at);
```

## Znane pułapki

- **Dwa widoki zamówień** — pole dodane do złego widoku jest martwe. Zawsze zapisz, w którym widoku wystąpił błąd.
- Odczyt PDF u klienta BEZ polityki (`client_policy: null`) — model czyta ogólnie; brak reguł
  ma być WIDOCZNY komunikatem. Brak komunikatu = P2.
- Polityki per klient (Nordea, BP, CA, BNP, Erste, Orlen, PFRON, BIK, Polkomtel, CP, Alior)
  są bramkowane env-em — dla D1/D2 NIE działają i to poprawne. Test polityk realnych = tylko
  na prawdziwym PDF prawdziwego klienta, czego w UAT NIE robimy (dane).
- Zamówienie i kontrakt: linie grup MD/kosztowych są POZA kierunkiem kosztowym synchronizacji
  (stawka kosztowa linii ≠ stawka z kontraktu) — to zamierzone.
- Pusty stan list wisi na `isSuccess` — w przerwie ponowień react-query NIE może pokazywać „brak zamówień”.

## Do raportu

Zrzuty S02 (3 karty), S05, S13; JSON odpowiedzi `extract` dla S02 i S13 (bez danych osobowych — nazwy są fikcyjne);
tabela „rola → widoczność stawek linii / akcji cyklu życia”; zużycie AI przed/po.
