# Przegląd PR-ów #1225–#1229 (codex) — po mergu

> Wykonany 21.08.2026, po zmergowaniu wszystkich pięciu na `main`. Sześciu agentów: pięciu
> po jednym PR-ze, szósty liczący kolizje z równoległą gałęzią napraw długu.
> Kontekst: [`docs/tech-debt-audit-2026-08-21.md`](./tech-debt-audit-2026-08-21.md).

**31 uwag:** 7× P1 · 16× P2 · 8× P3.
**19 z nich to nawroty klas opisanych w audycie** — czyli defekty, które backlog już nazywa,
odtworzone w kodzie napisanym bez jego kontekstu. To najmocniejszy argument za tym, żeby
naprawy systemowe (strażniki, testy kontraktowe) szły przed naprawami pojedynczych wystąpień:
bez nich każda kolejna fala pracy odtwarza te same klasy.

---

## PR #1225 — `wymaga-poprawki`

PR robi trzy rzeczy naraz: (1) wprowadza status `scheduled` dla grup zamówień wielo-konsultanckich wraz z datowym materializerem (`order_group_lifecycle.py`), master-PDF grupy synchronizowanym do `contract_documents`, i usuwaniem plików; (2) auto-promuje kompletne drafty `ClientOrder` do `active`; (3) ODWRACA świadome utwardzenie z `contract_lifecycle.py` — `status` wraca jako pole zapisywalne w `ContractCreate`/`ContractUpdate`. Warstwa zamówień jest zrobiona bardzo solidnie (lustro entrypointu z DROP przed ADD, test kontraktowy migracji, `isSuccess`/`isError`/`onError` wszędzie na froncie, jawne `contract=contract` przeciw MissingGreenlet). Problem jest w warstwie kontraktów: PATCH `{"status": ...}` omija `assert_transition`, `validate_ready_for_activation`, wymóg podpisu ORAZ cały sync terminacji z `/terminate` (zamówienia klienta zostają otwarte). Do tego dialog rejestru wysyła `status` przy KAŻDYM zapisie, więc kontrakt w `ready_for_signature` przestaje dawać się edytować (422) — przed PR-em pole było po prostu ignorowane. Warstwa zamówień: kilka mniejszych rzeczy (martwy klucz cache `["clients"]`, dopasowanie klienta Nordea po PODCIĄGU nazwy, `_activate_complete_draft` nadpisujące jawny `status: draft`).

**Co zrobione dobrze.** Część zamówieniowa jest zrobiona wzorowo i widać, że autor czytał CLAUDE.md, a nie tylko ticket.

1. **Lustro entrypointu jest kompletne i zrobione DOBRZE.** Wszystkie siedem nowych kolumn ma `ADD COLUMN IF NOT EXISTS`, oba nowe FK sprawdzają istnienie SEMANTYCZNIE (`pg_constraint` JOIN `pg_attribute` po `conrelid`/`confrelid`/`attname`), a nie po nazwie więzu — to lepiej niż wzorzec w sąsiednich blokach. Poszerzenie `ck_client_order_groups_status` o `scheduled` ma przed sobą `ALTER TABLE client_order_groups DROP CONSTRAINT IF EXISTS ck_client_order_groups_status` (entrypoint.sh:4547), czyli dokładnie ten DROP, którego brak w 0226 zrobił z poszerzenia katalogu no-op. Oba indeksy (w tym częściowy UNIQUE) też są zmirrorowane.

2. **Test wydania migracji (`test_contract_order_workflows_migration.py`) pilnuje tego lustra maszynowo** — parsuje graf alembica AST-em bez bootowania aplikacji, asertuje pojedynczą głowę po 0237, sprawdza `ADD COLUMN IF NOT EXISTS` dla każdej kolumny i wymusza wzorzec DROP-then-ADD w OBU ścieżkach. To jest strażnik, który nie zgnije.

3. **Jednorazowa korekta BIK jest idempotentna w obu ścieżkach naraz.** Marker w `app_settings` (PK na `key`, więc `ON CONFLICT (key)` jest legalny) i UPDATE są JEDNYM statementem z `AND EXISTS (SELECT 1 FROM marker)` — cokolwiek pobiegnie pierwsze (alembic czy entrypoint), drugie jest no-opem, a entrypoint leci przy każdym starcie i bez tego wskrzeszałby kontrakt świadomie zakończony później przez admina. `downgrade` jawnie nie cofa korekty i pisze dlaczego.

4. **Front trzyma dyscyplinę stanów.** Dziewięć mutacji w `MultiConsultantOrdersTab` — dziewięć `onError`. Pusty stan wisi na `!query.isSuccess`, nie na `!isLoading`, i ma nad sobą komentarz tłumaczący przerwę między ponowieniami. Licznik w nagłówku też renderuje się dopiero przy `isSuccess`. `withExistingFileBusy` w `OrderGroupFormModal` łapie błąd usuwania pliku i pokazuje go w `fileError` zamiast zostawiać odrzuconą obietnicę.

5. **MissingGreenlet pomyślany z wyprzedzeniem.** `create_order_extension` i `create_contract_with_order` przekazują `contract=contract` do konstruktora `ClientOrder`, żeby `_activate_complete_draft` nie musiał lazy-loadować relacji; `update_order` ma `selectinload(ClientOrder.contract)` z komentarzem nazywającym problem po imieniu.

6. **Nowy status nie rozszczelnił liczenia pieniędzy.** Linie grup `scheduled` powstają jako `ClientOrderStatus.draft`, a `active_md_lines` filtruje `ClientOrder.status == active`, `active_cost_lines` dodatkowo `ClientOrderGroup.status == GROUP_STATUS_ACTIVE` — więc ani import MD nie zaczyna widzieć dwóch kandydatów na jedno nazwisko, ani `active_consultants` (`is_active = order.status == active`) nie liczy tej samej osoby dwa razy. Sprawdziłem wszystkie predykaty po `ClientOrderGroup.status` w backendzie: żaden nie jest napisany jako negacja, więc `scheduled` nigdzie nie wchodzi tylnymi drzwiami.

7. **Kolejność commit → kasowanie bloba** jest wszędzie właściwa (`replace_order_group_file`, `delete_order_group_file`, `delete_order_po`), z komentarzem tłumaczącym, że awaria dysku nie może cofnąć poprawnego usunięcia z formularza. `ContractDocument` po skasowaniu grupy zostaje jako historia (FK `SET NULL`), a częściowy UNIQUE `(contract_id, source_order_group_id) WHERE source_order_group_id IS NOT NULL` sprawia, że podmiana PDF-a aktualizuje wiersz, a nie dopisuje duplikat obok — i nie tyka dokumentów ręcznych.

8. **Testy idą przez HTTP, nie mockują zepsutej warstwy** — `test_multi_consultant_orders.py` sprawdza zagnieżdżanie i sortowanie przyszłych zamówień, status `draft` ich linii, promocję w dacie startu, przeżycie kopii PDF po odpięciu konsultanta i po usunięciu grupy.

### `P1` PATCH/POST kontraktu znów zapisuje `status` bezpośrednio — omija cały strzeżony lifecycle (przejścia, podpis, sync zamówień)

`backend/app/api/contracts.py:1536`

> **Nawrót znanej klasy:** P1-CONTRACT-01 — swobodny zapis `status` z pominięciem `contract_lifecycle` (usunięty wcześniej defekt; docstring `contract_lifecycle.py` opisuje go jako naprawiony)

```
    if "status" not in updates:
        coerced_status = _status_after_end_date_change(
            contract.status, contract.end_date, date.today()
        )
```

**Dlaczego to boli.** `ContractUpdate.status` (schemas/contract.py:188) i `ContractCreate.status` (:140) były USUNIĘTE świadomie — docstring `app/services/contract_lifecycle.py` mówi wprost: „The finding (P1-CONTRACT-01): ... ``status`` was writable from the create/update schemas ... no route sets ``status = active`` directly". Ten PR je przywraca, a `update_contract` nie woła ŻADNEJ funkcji z `contract_lifecycle`. Cztery konkretne skutki. (a) `ALLOWED_TRANSITIONS[ContractStatus.void] = frozenset()` — void jest terminalny, a PATCH {"status":"active"} go wskrzesza (soft-skasowany kontrakt wraca do MRR, `active_consultants`, alertów DL). (b) `signature_required(contract, has_signatures=True)` zwraca True nawet przy `SIGNING_ENABLED=false` — kontrakt, dla którego proces podpisu RUSZYŁ, ale się nie zakończył, da się teraz oznaczyć jako `active` bez `completed` DocumentSignature; `activate_contract` odmawiał tego z 409 `signature_required`. (c) `validate_ready_for_activation` pomijane — `active` z brakującymi wymaganymi polami, na których stoi liczenie pieniędzy. (d) Najgorsze operacyjnie: wybranie „Zakończony" w dropdownie NIE robi tego, co `/terminate` (contracts.py:2904-2957) — brak `terminated_at`, brak koherencji `end_date`, brak `ContractAmendment`, i przede wszystkim brak syncu `ClientOrder`, którego własny komentarz mówi „bez jawnego syncu zakończony kontrakt zostawiał otwarte zamówienia dryfujące bezterminowo". Zamówienia klienta zostają `active`, `dl_portal_expiry_scanner` dalej wysyła alerty, a zamknięty kontrakt dalej ciągnie linie w zamówieniach. Bramka to `TacPlus` (admin + delivery_lead + tac), nie sam admin.

**Naprawa.** Nie zdejmować pola (ticket jest słuszny — dropdown musi zapisywać), tylko przepuścić je przez maszynę stanów: w `update_contract`, gdy `"status" in updates`, wołaj `contract_lifecycle.assert_transition(contract.status, target)` przed setattr, a dla `target == active` deleguj do `activate_contract(db, contract, actor_id=...)`, dla `target == ended` — do tej samej ścieżki, którą robi `/terminate` (co najmniej sync `ClientOrder` + koherencja `end_date`). `void` i tak odrzuca już walidator schematu, ale przejście Z `void` trzeba zablokować jawnie.

### `P1` Dialog rejestru wysyła `status` przy KAŻDYM zapisie, więc kontraktu w `ready_for_signature` nie da się już edytować — 422 z komunikatem o czymś, czego użytkownik nie dotykał

`frontend/src/components/contracts/ContractRegisterDialog.tsx:206`

```
        prolongation_status: prolongation,
        status: statusVal,
      };
```

**Dlaczego to boli.** `statusVal` jest inicjalizowany z `setStatusVal(contract.status ?? "active")` (:164), a `RegisterContractRow.status` to `string | null` (lib/contract-register.ts:25) — czyli przyjmuje też `ready_for_signature`. `STATUS_OPTIONS` (:74-79) ma tylko cztery wartości, więc Select nie ma dopasowanej opcji, ale stan i tak trzyma `"ready_for_signature"` i leci w payloadzie. Nowy `AfterValidator` (`_validate_contract_register_status`, schemas/contract.py) odrzuca go z 422 „Status jest dostępny wyłącznie przez lifecycle kontraktu". `_apply_contract_list_filters` (contracts.py:294+) wyklucza domyślnie TYLKO `void` (`query.where(Contract.status != ContractStatus.void)`), więc kontrakty czekające na podpis SĄ na liście rejestru. Przed tym PR-em pole było ciche (Pydantic `extra=ignore`) i edycja przechodziła. Regresja: użytkownik poprawia numer projektu, dostaje 422 o statusie. Drugi skutek tej samej linii: skoro `status` jest w payloadzie ZAWSZE, warunek `if "status" not in updates` (contracts.py:1536) nigdy nie zadziała z rejestru — udokumentowany self-heal („editing only the end date to bezterminowo heals a contract wrongly marked ended") jest z tego UI martwy. Testy tego nie łapią, bo parametryzują wyłącznie cztery dozwolone statusy.

**Naprawa.** Wysyłaj `status` tylko gdy operator go zmienił (`statusVal !== contract?.status`), albo — lepiej — zainicjalizuj `statusVal` bezpiecznie i nie pozwól odesłać wartości spoza `STATUS_OPTIONS`: gdy `contract.status` jest spoza listy, ukryj Select i pomiń klucz w payloadzie. Test regresyjny: PATCH z rejestru na kontrakcie w `ready_for_signature` ma zwrócić 200 i zostawić status bez zmian.

### `P2` `_activate_complete_draft` nadpisuje jawnie przesłany `status: draft` — udokumentowana ścieżka twardego usuwania zamówienia przestaje działać

`backend/app/api/client_orders.py:1010`

```
    for field, value in data.items():
        setattr(order, field, value)

    auto_activated = _activate_complete_draft(order)
    if auto_activated:
        data["status"] = ClientOrderStatus.active
```

**Dlaczego to boli.** Promocja leci PO pętli setattr i nie odróżnia „draft, bo nikt jeszcze nie uzupełnił" od „draft, bo operator właśnie o to poprosił". `ClientOrderUpdate.status` jest polem publicznym (schemas/client_order.py:40), a CLAUDE.md opisuje dokładnie ten ciąg jako sposób sprzątania na produkcji: „Pełne usunięcie idzie istniejącym API: `PATCH {"status":"draft"}` → `DELETE` (`ClientOrderUpdate` przyjmuje `status`, a twarde kasowanie obejmuje szkice)" — użyty realnie 18.08 przy czyszczeniu zamówienia testowego Polkomtela. Po tej zmianie kompletne zamówienie wraca z PATCH-a jako `active`, a `DELETE` (client_orders.py, gałąź `if order.status == ClientOrderStatus.draft`) tylko je anuluje zamiast skasować. Osierocone wiersze `client_orders` po skasowanej grupie stają się nieusuwalne z aplikacji.

**Naprawa.** Nie promuj, gdy `"status" in payload.model_fields_set` — jawna intencja operatora wygrywa z heurystyką kompletności.

### `P2` Nowa inwalidacja `["clients"]` nie ma w całym froncie ANI JEDNEJ kwerendy pod tym kluczem — liczniki katalogu nie odświeżą się mimo komentarza, który to obiecuje

`frontend/src/components/contracts/ContractRegisterDialog.tsx:231`

> **Nawrót znanej klasy:** Temat 10 backlogu — „mutacje unieważniają klucze cache, których nikt nie produkuje"

```
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      queryClient.invalidateQueries({ queryKey: ["clients"] });
```

**Dlaczego to boli.** `grep -rn 'queryKey' frontend/src | grep '"clients"'` zwraca wyłącznie trzy inwalidacje (AppShell.tsx:2241, QuickActionsV2.tsx:87 i ta nowa) i ZERO producentów. React Query dopasowuje prefiksowo po RÓWNOŚCI elementów, więc `["clients"]` nie trafia w `["clients-directory"]` — a to właśnie ten klucz stoi pod katalogiem klientów (potwierdza to strażnik `lib/__tests__/query-key-producers.test.ts`, który wymaga producenta dla `clients-directory`). Komentarz dodany w tym samym hunku mówi „Status napędza ... liczniki katalogu. Bez invalidacji poprawny zapis wyglądał jak nieskuteczny aż do ręcznego odświeżenia strony" — czyli intencja jest jasna, a klucz jest martwy i objaw zostaje. `["client-profile", clientId]` obok jest poprawny (producent: app/clients/[id]/ProfileTab.tsx:30).

**Naprawa.** Zamień na `["clients-directory"]` (i dopisz ten literał do listy w `query-key-producers.test.ts`, żeby kolejna zmiana nazwy klucza wywaliła test zamiast cicho przestać odświeżać).

### `P2` Reguła numeru zamówienia Nordea dopasowuje klienta po PODCIĄGU wolnotekstowej nazwy, którą nadpisuje import z Traffita — w module, który wszędzie indziej używa list ID z ENV

`backend/app/api/client_orders.py:911`

> **Nawrót znanej klasy:** Temat 13 backlogu — „dopasowanie po ID klienta, nie po podciągu nazwy. To samo pole nazwy jest nadpisywane przez import z Traffita"

```
    if client.name.casefold() == "nordea" or "nordea bank abp" in client_names:
        extraction = enforce_nordea_order_number(extraction, text)
```

**Dlaczego to boli.** Sąsiednie funkcje tego samego obszaru celowo NIE robią dopasowania po nazwie: `MULTI_CONSULTANT_ORDER_CLIENT_IDS` i `COST_ORDER_CLIENT_IDS` to listy ID w Coolify, a CLAUDE.md uzasadnia to wprost — „Nazwa odpada z tego samego powodu co przy e-Zdrowiu: Traffit nadpisuje `Client.name`". Tu wystarczy, że import z Traffita przestawi `name` na „Nordea Bank Abp SA Oddział w Polsce" albo że powstanie duplikat rekordu klienta (historycznie: e-Zdrowie miało dwa wiersze, BNP to RODZINA rekordów), żeby twarda polityka numeru przestała działać. Skutek jest cichy w najgorszą stronę: `enforce_nordea_order_number` nie odpali, a parser zwróci numer oferty/projektu jako numer zamówienia — czyli dokładnie to, przed czym ta funkcja miała chronić, tylko bez żadnego sygnału. Odwrotnie też: dowolny nowy klient z „nordea bank abp" w `legal_name` dostanie tę politykę bez decyzji.

**Naprawa.** Przenieś na listę ID w ENV (`NORDEA_ORDER_NUMBER_CLIENT_IDS`, wzorzec `is_multi_consultant_client` / `is_cost_order_client`), zgodnie z resztą modułu zamówień.

### `P2` Bramka auto-aktywacji czyta cache'owaną kolumnę `contracts.rate_candidate`, więc kontrakt ze stawką progresywną zaczynającą się w przyszłości nigdy nie wypchnie zamówienia z Draftu

`backend/app/api/client_orders.py:167`

> **Nawrót znanej klasy:** Temat 0 backlogu — czytanie cache'owanych kolumn `contracts.rate_*` zamiast stawek efektywnych z harmonogramów

```
        and order.rate_client is not None
        and order.contract is not None
        and order.contract.rate_candidate is not None
    )
```

**Dlaczego to boli.** `Contract.rate_candidate` jest kolumną cache'owaną, odświeżaną wyłącznie przy zapisie kontraktu: `create_contract` robi `contract.rate_candidate = contract.effective_candidate_rate(date.today())` tylko gdy przesłano harmonogram, a `effective_candidate_rate(today)` zwraca None, gdy pierwszy krok harmonogramu ma `effective_from` w przyszłości. Dialog rejestru buduje harmonogram z `effectiveFrom` = data rozpoczęcia kontraktu, więc kontrakt zakładany „od przyszłego miesiąca" ma `rate_candidate` NULL. Efekt: dwa identycznie wypełnione formularze dają różny wynik — kontrakt ze stawką płaską auto-aktywuje zamówienie, kontrakt ze stawką progresywną zostawia je w Draft, bez żadnego komunikatu. Draftowe zamówienie nie wchodzi do `active_md_lines` (`ClientOrder.status == ClientOrderStatus.active`) ani do liczników konsultantów. Kanoniczny resolver stawek efektywnych (`contracts._effective_rate_fields`, używany już przez `clients.py`) daje na to poprawną odpowiedź.

**Naprawa.** Zamiast `order.contract.rate_candidate` sprawdź `order.contract.effective_candidate_rate(date.today()) is not None` lub przejdź przez `_effective_rate_fields`. Uwaga na eager-load: `update_order` robi `selectinload(ClientOrder.contract)`, ale harmonogramy NIE są ładowane, więc trzeba dołożyć `selectinload(Contract.candidate_rate_schedule)`, inaczej wyjdzie MissingGreenlet (500 bez CORS).

### `P2` Zapis grupy to dwa wywołania API pod jedną mutacją — gdy padnie upload PDF-a, komunikat mówi „nie udało się zapisać zamówienia", a zamówienie już istnieje; ponowienie tworzy duplikat

`frontend/src/components/client-profile/orders/MultiConsultantOrdersTab.tsx:146`

```
        saved = (await orderGroupsApi.create(clientId, values)).data;
      }
      if (file) {
        saved = (await orderGroupsApi.replaceFile(clientId, saved.id, file)).data;
      }
```

**Dlaczego to boli.** `replaceFile` ma cztery własne ścieżki odmowy (415 nie-PDF, 415 zły magic `%PDF-`, 413 >25 MB, 410 brak pliku na dysku) plus 30-sekundowy timeout instancji axios przy pliku do 25 MB. Każda z nich odpala `onError` mutacji, która ustawia jeden komunikat „Nie udało się zapisać zamówienia." i zostawia modal otwarty — mimo że `POST /order-groups` już przeszedł i grupa (razem z liniami konsultantów) jest w bazie. `ClientOrderGroup.order_number` jest „świadomie BEZ unikalności w bazie" (models/client_order_group.py:99), więc kliknięcie „Zapisz" jeszcze raz zakłada DRUGIE zamówienie o tym samym numerze — i dopiero wtedy import MD trafia na niejednoznaczność.

**Naprawa.** Rozdziel komunikat: w `mutationFn` złap błąd samego `replaceFile` i zgłoś go osobno („Zamówienie zapisane, ale nie udało się wgrać PDF-a — spróbuj ponownie z karty zamówienia"), zamykając modal i inwalidując listę. Alternatywnie po udanym `create` zapamiętaj `saved.id` w stanie i przy ponowieniu użyj `update` zamiast `create`.

### `P3` Automatyczne domknięcie poprzednika nie zapisuje zdarzenia w historii zamówienia i nie dociąga `end_date` grupy — inaczej niż ręczne zakończenie

`backend/app/services/order_group_lifecycle.py:114`

```
            previous.status = GROUP_STATUS_COMPLETED
            previous.closure_date = history_boundary
            previous.closure_reason = (
                f"Automatycznie zastąpione zamówieniem {current.order_number}"
            )
```

**Dlaczego to boli.** Ręczna ścieżka (`close_order_group`, client_order_groups.py:1468-1489) robi trzy rzeczy, których materializer nie robi: zapisuje `record_event(..., event_type=EVENT_ORDER_CLOSED, ...)`, dociąga `group.end_date` do daty zamknięcia i stempluje `closed_by_user_id`. CLAUDE.md mówi o tym module „Historia żyje w ... zdarzeniach" i „log JEST raportem" — po automatycznym przejściu dialog „Historia statusów" nie pokaże NIC między `przedluzenie` a stanem obecnym, więc nie da się odpowiedzieć, kiedy i czym zamówienie zostało zastąpione (a `closure_reason` przepadnie przy pierwszym `przywroceniu`, które je czyści). Osobno: `previous.end_date` zostaje na starej, przyszłej dacie, więc karta zakończonego zamówienia dalej pokazuje „do 31.12", podczas gdy jego linie są już przycięte do `history_boundary`.

**Naprawa.** Dopisz `record_event(db, group_id=previous.id, event_type=EVENT_ORDER_CLOSED, ...)` (typ jest już w CHECK-u `ck_client_order_group_events_type`) i dociągnij `previous.end_date`, jak robi to `close_order_group`. `user_id=None` jest tu poprawne — to przejście systemowe.

### `P3` `reopen_order_group` nie zna statusu `scheduled` — przywrócenie zamówienia przyszłego robi z niego drugie „aktywne" w rodzinie, z liniami zostawionymi w Draft

`backend/app/api/client_order_groups.py:1528`

```
    if group.status == GROUP_STATUS_ACTIVE:
        raise HTTPException(409, detail="To zamówienie jest już aktywne")
    if group.status == GROUP_STATUS_EXHAUSTED:
```

**Dlaczego to boli.** Handler był pisany w świecie trzech statusów: „nie active i nie exhausted" znaczyło „completed". Po dołożeniu `scheduled` grupa przyszła przechodzi obie bramki i dostaje `group.status = GROUP_STATUS_ACTIVE` przed datą startu, a linie zostają `draft` (reopen ich nie rusza) — czyli „bieżące" zamówienie z zerem aktywnych konsultantów, niewidoczne dla `active_md_lines`. Materializer już go nie naprawi: `due` bierze wyłącznie wiersze `GROUP_STATUS_SCHEDULED`, więc ani ta grupa nie wróci do kolejki, ani jej poprzednik (też `active`) nie zostanie domknięty — w rodzinie zostają dwa aktywne zamówienia. Z UI nieosiągalne (przycisk „Przywróć" renderuje się tylko dla `status === "completed"`, OrderGroupCard.tsx:537), więc to bramka API, nie objaw produkcyjny.

**Naprawa.** Dodaj jawną odmowę: `if group.status == GROUP_STATUS_SCHEDULED: raise HTTPException(409, ...)` — zamówienie, które jeszcze nie ruszyło, nie jest „przywracane", tylko edytowane albo usuwane.

### `P3` Cały cykl życia przyszłych zamówień chodzi na `date.today()`, czyli na zegarze kontenera w UTC, a nie na dobie warszawskiej

`backend/app/services/order_group_lifecycle.py:50`

> **Nawrót znanej klasy:** Temat 5 backlogu — 113 wywołań `date.today()` na zegarze kontenera zamiast doby warszawskiej

```
    boundary_day = today or date.today()
```

**Dlaczego to boli.** To samo w `_initial_group_status` (client_order_groups.py:294: `return GROUP_STATUS_SCHEDULED if start_date > date.today() else GROUP_STATUS_ACTIVE`) i w `_promote_statuses` skanera. `BUSINESS_TZ: str = "Europe/Warsaw"` jest w `core/config.py:380` i honorowany w kilku miejscach. Latem UTC jest o 2 h za Warszawą, więc między 00:00 a 02:00 czasu polskiego: zamówienie zakładane z datą startu „dziś" dostaje status „Przyszłe", a zamówienie, które właśnie wchodzi w życie, nie jest jeszcze materializowane — jego linie zostają `draft`, czyli poza `active_md_lines` i poza licznikiem konsultantów. Okno jest wąskie i nocne, ale moduł jest w CAŁOŚCI sterowany datą, więc to jedyne miejsce, gdzie ta klasa błędu ma bezpośrednie przełożenie na stan biznesowy, a nie tylko na kubełkowanie raportu.

**Naprawa.** Jedna funkcja `business_today()` (`datetime.now(ZoneInfo(settings.BUSINESS_TZ)).date()`) użyta w `materialize_scheduled_order_groups`, `_initial_group_status` i w skanerze. Repo dostaje właśnie taki helper na gałęzi długu („granice okresu w strefie biznesowej") — warto podpiąć się pod niego zamiast dokładać kolejne `date.today()`.

---

## PR #1226 — `ok-z-uwagami`

Jednorazowa, precyzyjnie wskazana korekta danych po 0238: aktywuje kontrakt #571 (nazwisko w NFD nie trafiło w porównanie całego napisu w 0238) i przenosi przyszłą grupę zamówienia BIK 4500030684 z `active` na `scheduled`, przygotowując jej linie do materializacji 11.09. Rzemieślniczo jest to dobry PR — lustro w entrypoint jest semantycznie identyczne z migracją (porównałem oba bloki po normalizacji), docelowy stan dokładnie odpowiada temu, czego oczekuje `materialize_scheduled_order_groups`, prefiks `'Łuszcz%'` poprawnie omija znaki rozkładane przez NFD, wszystkie filtry statusu są pozytywne, a poprawka testu kontraktorów NAPRAWIA klasę „active jako równość zamiast koszyka dat" zamiast ją maskować. PR nie liczy żadnych pieniędzy, nie dotyka uprawnień ani frontendu, więc większość klas z audytu jest tu nieaktywna. Cztery uwagi dotyczą utwardzenia: obejście jedynej dozwolonej ścieżki do statusu `active`, marker jednorazowy zapisywany także przy zerowym dopasowaniu, kolejność `_DATA_STATEMENTS` przed `_CONSTRAINT_STATEMENTS` w safety-necie oraz hardkodowana głowa alembica w cudzym pliku testowym.

**Co zrobione dobrze.** Lustro w `entrypoint.sh` jest SEMANTYCZNIE IDENTYCZNE z migracją — porównałem oba bloki po normalizacji białych znaków, jedyna różnica to etykieta `'source'` ('alembic' vs 'entrypoint_safety_net'). To nie jest lustro „na oko", tylko realny drugi kanał dostarczenia, co przy udokumentowanym osieroconym alembicu na prodzie jest kluczowe. Docelowy stan korekty (grupa `scheduled`, linie `draft`, `filled_at NULL`) dokładnie odpowiada temu, czego oczekuje `materialize_scheduled_order_groups` — promuje wyłącznie `GROUP_STATUS_SCHEDULED`, a linie `draft` przestawia na `active` i stempluje `filled_at` tylko gdy jest NULL; migracja nie wymyśla własnej semantyki obok istniejącej maszyny stanów. Diagnoza Unicode jest poprawna i widać, że autor rozumie, co robi: prefiks `LIKE 'Łuszcz%'` omija `ń` i `ś`, czyli dokładnie te znaki, które NFD rozkłada, a `Ł` jest w Unicode atomiczne, więc prefiks działa w obu normalizacjach. Wszystkie predykaty statusu są POZYTYWNE (`contract.status = 'draft'::contractstatus`, `order_group.status = 'active'`, `status = 'active'::clientorderstatus`) — zero negacji typu `!= draft`, która wpuszczałaby `ready_for_signature`/`void`. Cały blok jest jedną transakcją `DO`, więc częściowe zastosowanie nie może się utrwalić, a `RAISE EXCEPTION` przy niejednoznaczności wycofuje też UPDATE kontraktu. Migracja jest doczepiona do `0238_contract_order_workflows`, czyli łańcuch pozostaje jednogłowy. Poprawka `test_contractors_api.py` nie jest rozluźnieniem testu pod zieleń, tylko NAPRAWĄ klasy defektu z audytu: asercja `end_date < today or end_date > cutoff` to dokładne dopełnienie `ending_soon_clause()` i wierne odwzorowanie `live_not_ending_clause()`, więc test przestał twierdzić coś węższego niż kontrakt API. CI faktycznie wykonuje ten SQL (`alembic -c alembic/alembic.ini upgrade heads` w `.github/workflows/ci.yml:81`), więc to nie jest kod weryfikowany wyłącznie grepem po pliku.

### `P2` Migracja ustawia kontrakt na `active` bezpośrednim UPDATE-em, omijając jedyną dozwoloną ścieżkę aktywacji i wiersz audytu

`backend/alembic/versions/0239_bik_contract_order_backfill.py:45`

```
       SET status = 'active'::contractstatus,
```

**Dlaczego to boli.** `app/services/contract_lifecycle.py` deklaruje wprost: „:func:`activate_contract` — the ONLY path to ``active``" i „no route sets ``status = active`` directly". Ta funkcja robi dwie rzeczy, których migracja nie robi: (1) woła `validate_ready_for_activation(contract)` i odrzuca aktywację, gdy brakuje któregoś z `ACTIVATION_REQUIRED_FIELDS` = (`start_date`, `end_date`, `rate_candidate`, `rate_client`, `contract_type`, `work_mode`) — docstring tej stałej mówi wprost „without these, downstream reporting (margin, finance, end-date alerts) would show garbage"; (2) dopisuje wiersz `Activity` z akcją `contract_activated`. Migracja bramkuje wyłącznie `contract.id = 571`, `client_id = 18`, `status = 'draft'` i tożsamość osoby/klienta — kompletności danych nie sprawdza wcale. Scenariusz: jeśli kontrakt #571 nie ma wypełnionego `rate_client` albo `rate_candidate` (a to najczęstszy brak w szkicu), po migracji wchodzi do rejestru kontraktorów i do profilu klienta jako aktywny konsultant, którego marża renderuje się jako „—", a do kafla MRR wnosi zero — `active_mrr` liczy `to_whole_pln(active_rates[c.id]["monthly_margin"] or 0)` (backend/app/api/clients.py:625), więc nie ma awarii, jest cicho zaniżona liczba. Równolegle historia kontraktu (`select(Activity)...where(Activity.entity_type == "contract", Activity.entity_id == contract_id)`, backend/app/api/contracts.py:1359) nie ma wpisu o aktywacji, więc oś czasu przeskakuje ze szkicu na aktywny bez zdarzenia. Ta sama klasa pominięcia weszła już w 0238 dla dziewięciu kontraktów, więc utrwala się jako wzorzec.

**Naprawa.** Dopisać do WHERE komplet warunków odpowiadający `ACTIVATION_REQUIRED_FIELDS` (`AND contract.start_date IS NOT NULL AND contract.end_date IS NOT NULL AND contract.rate_candidate IS NOT NULL AND contract.rate_client IS NOT NULL AND contract.contract_type IS NOT NULL AND contract.work_mode IS NOT NULL`), żeby niekompletny szkic nie dawał się aktywować SQL-em skoro nie daje się aktywować przez API, oraz dołożyć w tej samej transakcji `INSERT INTO activities (entity_type, entity_id, action, details)` z `action = 'contract_activated'` i `details` zawierającym `from_status`/`to_status`, żeby historia kontraktu nie miała dziury. Jeśli kontrakt #571 na prodzie jest niekompletny, warunek zamieni cichą aktywację w brak zmiany — wtedy właściwą ścieżką jest uzupełnienie pól i aktywacja przez UI.

### `P2` Marker jednorazowy zapisywany także przy zerowym dopasowaniu grupy — fail-closed działa tylko dla >1, nie dla 0

`backend/alembic/versions/0239_bik_contract_order_backfill.py:73`

```
    IF target_group_count > 1 THEN
        RAISE EXCEPTION
            '0239 expected at most one BIK order group 4500030684, found %',
            target_group_count;
    END IF;
```

**Dlaczego to boli.** Opis PR obiecuje „zachowuje fail-closed przy niejednoznacznym dopasowaniu", ale bramka łapie wyłącznie nadmiar. Przy `target_group_count = 0` blok `IF target_group_count = 1` jest pomijany, a `INSERT INTO app_settings` (linia 94) wykonuje się BEZWARUNKOWO — więc jednorazowa korekta zostaje skonsumowana mimo że nic nie zrobiła. Zapytanie o grupę ma sześć koniunkcji, w tym `order_group.predecessor_group_id IS NOT NULL` i `order_group.order_number = '4500030684'`; grupa powstała — jak mówi sam docstring — „przed wprowadzeniem statusu ``scheduled``", czyli starą ścieżką, w której powiązanie z poprzednikiem wcale nie musiało zostać zapisane. Scenariusz: UPDATE kontraktu trafia (1 wiersz), zapytanie o grupę zwraca 0 z powodu pustego `predecessor_group_id` albo numeru z sufiksem → marker zapisany → grupa 4500030684 zostaje na zawsze w statusie `active`. To nie jest stan neutralny: `materialize_scheduled_order_groups` buduje listę `due` wyłącznie z `group.status == GROUP_STATUS_SCHEDULED`, więc 11.09.2026 nie promuje tej grupy i NIE domyka poprzednika (`previous.status = GROUP_STATUS_COMPLETED`, `closure_date`, domknięcie linii). U BIK zostają dwie równorzędne aktywne karty tego samego zamówienia bez daty domknięcia poprzednika — dokładnie ten defekt, który 0238/0239 miały zlikwidować — i nie ma ani retry (marker), ani alarmu (health nic o tym nie wie). Jedynym śladem jest `'order_group_rows', target_group_count` w JSON-ie markera, którego nikt nie odczyta bez pytania o niego wprost.

**Naprawa.** Rozdzielić „nie ma czego poprawiać" od „nie rozpoznaję stanu": osobno policzyć grupy po samej parze `(client_id = 18, order_number = '4500030684')` i gdy taka grupa ISTNIEJE, a nie spełnia oczekiwanego kształtu (`status = 'active'`, `predecessor_group_id IS NOT NULL`, `start_date = DATE '2026-09-11'`), zrobić `RAISE EXCEPTION` zamiast cicho zapisać marker. Wtedy zerowe dopasowanie po poprawnym zastosowaniu (grupa już `scheduled`) nadal kończy się markerem, a rozjazd danych jest głośny i powtarza się przy kolejnym starcie zamiast przepaść.

### `P2` Safety-net zapisuje `status = 'scheduled'` w `_DATA_STATEMENTS`, a CHECK dopuszczający tę wartość jest poszerzany dopiero w `_CONSTRAINT_STATEMENTS`, które biegną PÓŹNIEJ

`backend/entrypoint.sh:5084`

> **Nawrót znanej klasy:** ADD CONSTRAINT bez poprzedzającego DROP w entrypoint.sh / migracja bez działającego lustra w entrypoint.sh

```
        for stmt in _DATA_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill data skip: {stmt!r} -> {e!r}")
        for stmt in _CONSTRAINT_STATEMENTS:
```

**Dlaczego to boli.** Nowy blok 0239 trafił do `_DATA_STATEMENTS` (linia ~3679) i wykonuje `UPDATE client_order_groups SET status = 'scheduled'`. Wartość `'scheduled'` staje się legalna dopiero po instrukcji z `_CONSTRAINT_STATEMENTS`: `ALTER TABLE client_order_groups DROP CONSTRAINT IF EXISTS ck_client_order_groups_status` + `ADD CONSTRAINT ck_client_order_groups_status CHECK (status IN ('active', 'scheduled', 'completed', 'exhausted')) NOT VALID` (entrypoint.sh:4632-4636). `NOT VALID` nie sprawdza istniejących wierszy, ale NOWE zapisy — owszem. Pętla wykonuje DATA przed CONSTRAINT, więc na każdym starcie, na którym poszerzony CHECK jeszcze nie wszedł, UPDATE łamie stary, wąski CHECK, wyjątek wywraca CAŁY blok `DO` (razem z aktywacją kontraktu), marker nie powstaje, a jedynym śladem jest `print(f"backfill data skip: ...")` w logu kontenera — `/api/health` pozostaje zielony. Osiągalne scenariusze: świeża baza (tabele powstają dopiero w `Base.metadata.create_all` PO backfillu), oraz skoalescowany deploy 0238+0239 przy osieroconym alembicu — a to jest dokładnie ten tryb awarii, na który safety-net został napisany. Na prodzie nie ugryzło, bo #1225 zmergowano 13:21Z, a #1226 o 14:21Z, czyli jako dwa osobne deploye — to zbieg okoliczności, nie zabezpieczenie. Stan naprawia się sam przy kolejnym restarcie, ale przez co najmniej jeden cykl deployu safety-net jest bezczynny i milczy.

**Naprawa.** Nie polegać na kolejności list: poprzedzić blok 0239 w `_DATA_STATEMENTS` idempotentnym `ALTER TABLE client_order_groups DROP CONSTRAINT IF EXISTS ck_client_order_groups_status` + `ADD CONSTRAINT ... CHECK (status IN ('active','scheduled','completed','exhausted')) NOT VALID` (ten sam DROP-przed-ADD co wyżej), albo wprost sprawdzić w `DO` obecność `'scheduled'` w definicji więzu i pominąć korektę grupy z jawnym `RAISE NOTICE`, zamiast wywracać transakcję razem z aktywacją kontraktu.

### `P2` Hardkodowana nazwa głowy alembica w teście CUDZEJ migracji — każda kolejna migracja wywali test o 0238

`backend/tests/test_contract_order_workflows_migration.py:60`

> **Nawrót znanej klasy:** lista skopiowana do kolejnego miejsca zamiast wyliczona

```
    assert _alembic_heads() == ["0239_bik_contract_order_backfill"]
```

**Dlaczego to boli.** To jedyny w repo strażnik jednogłowości zapisany jako równość z KONKRETNĄ nazwą rewizji. Pozostałe trzy robią to samo bez kopiowania nazwy: `test_multi_consultant_orders_migration.py:72` i `test_order_lifecycle_migration.py:76` mają `assert len(heads) == 1, f"łańcuch rozszczepiony, głowy: {heads}"`, a `test_analytics_release_gates.py:111` — `assert len(heads) <= _ALEMBIC_HEADS_BASELINE`. Konsekwencja jest już widoczna: #1226 musiał edytować ten plik wyłącznie po to, żeby przepisać nazwę, i tak samo będzie musiał każdy następny PR z migracją. Gorsze od samej edycji jest to, co zobaczy autor: czerwony test nazwany `test_migration_is_the_single_head_after_0237` w pliku o migracji 0238, podczas gdy zmiana dotyczy np. 0245 — komunikat kieruje diagnostykę na niewłaściwą migrację. To ta sama klasa co lista ról kopiowana do kolejnego miejsca zamiast wyliczana: fakt „ile jest głów" jest wyliczalny, a tu został zapisany jako literał w miejscu, które o nim nic nie wie. Klasę wprowadził #1225; #1226 utrwalił ją bumpem zamiast zamienić na wyliczenie.

**Naprawa.** Zamienić na repo-standardowe `heads = _alembic_heads()` + `assert len(heads) == 1, f"łańcuch rozszczepiony, głowy: {heads}"`, a przynależność 0238 do łańcucha sprawdzać tak jak w `test_order_lifecycle_migration.py` — przez obecność rewizji wśród `down_revision` innych plików, a nie przez nazwę aktualnego czubka.

### `P3` Poprawka NFD zastosowana punktowo do jednego wiersza, a nie do predykatu — siostrzane nazwisko z 0238 ma tę samą podatność

`backend/alembic/versions/0238_contract_order_workflows.py:138`

```
                    'michał leśniak',
```

**Dlaczego to boli.** 0238 dopasowywał osoby przez `lower(trim(ca.name) || ' ' || trim(ca.lastname)) IN (...)`, czyli porównanie CAŁEGO napisu — i to właśnie się wywróciło na rekordzie zapisanym w NFD, co 0239 naprawia dla Roberta Łuszczyńskiego prefiksem `LIKE 'Łuszcz%'`. Ale na liście 0238 jest jeszcze jedno nazwisko z tą samą podatnością: `michał leśniak` zawiera `ś` (U+015B), które NFD rozkłada na `s` + U+0301, dokładnie jak `ń` w `Łuszczyński` (`ł` i `Ł` są atomiczne, więc same z siebie nie psują porównania). Pozostałe siedem pozycji to albo czysty ASCII, albo wyłącznie `ł`/`ą` bez znaków rozkładanych w sposób psujący prefiks. 0239 poprawia jeden wiersz i nie usuwa przyczyny, więc jeśli rekord Leśniaka też jest w NFD, jego kontrakt do dziś zostaje szkicem — cicho, bo 0238 nie raportuje, ilu z dziewięciu ludzi faktycznie trafił. Nie mam dostępu do produkcji, więc nie twierdzę, że tak jest — opis PR mówi o dwóch rekordach znalezionych podczas weryfikacji. Zgłaszam klasę, nie fakt.

**Naprawa.** Sprawdzić na prodzie `SELECT id, name, lastname, status FROM contracts JOIN candidates ... WHERE lastname LIKE 'Le%niak'` i przy okazji następnej korekty tego typu porównywać po `normalize('NFC', ...)` albo po prefiksie bez znaków rozkładanych, zamiast po całym napisie — inaczej ta sama pułapka wróci przy kolejnej liście nazwisk.

---

## PR #1227 — `wymaga-poprawki`

PR dokłada do modułu zamówień klienta cztery rzeczy: wspólną warstwę wyszukiwania/filtrów/sortowania po stronie przeglądarki (`lib/client-order-list.ts` + `OrderListControls`), dwa endpointy eksportu XLSX (legacy `POST /clients/{id}/orders/export` i wielo-konsultantowy `POST /clients/{id}/order-groups/export`), administracyjny import CSV Nordea z podglądem dry-run i atomowym zapisem, oraz alfabetyczne sortowanie linii konsultantów z podświetleniem trafienia. Migracji nie ma, więc nie ma też ryzyka brakującego lustra w `entrypoint.sh`. Warstwa uprawnień jest reużyta, nie skopiowana (`TacPlus`, `OrderGroupReader` + `_assert_multi_client`, `AdminUser`), a redakcja finansowa dziedziczy się z `_line_to_read` / `_redact_contractor_finance`, więc eksport nie obchodzi bramki `VIEW_FINANCE` dla stawek. Trasy `/export` są zarejestrowane PRZED `/{order_id}` i `/{group_id}`, więc nie wpadają w pułapkę parsowania „export" jako int. Testy idą przez realną warstwę (prawdziwe endpointy na `app_client`, pełny cykl dry-run → apply → powtórka importu). Jest natomiast jeden nawrót udokumentowanej klasy P0/P1 — nowa powierzchnia pieniędzy (kolumna „Stawka kosztowa" w XLSX) czyta cache'owaną kolumnę `contracts.rate_candidate` zamiast harmonogramu — plus kilka rzeczy do poprawienia w czytelności eksportu, pustych stanach i podglądzie importu.

**Co zrobione dobrze.** Kilka rzeczy zrobiono dokładnie tak, jak wymusza historia tego repo, i warto to nazwać, żeby nie wyparowało przy kolejnym refaktorze:

1. **Kolejność tras.** Oba `POST .../export` są zarejestrowane PRZED `POST .../{order_id}` i `.../{group_id}` (`client_orders.py:625` vs 724/878/1274; `client_order_groups.py:881` vs 1203+). To dokładnie pułapka, która wcześniej zabiła eksport kontraktów — tutaj jej nie ma.

2. **Zakres klienta bez ujawniania cudzych ID.** Oba eksporty odrzucają obce identyfikatory jednym 404 z tym samym komunikatem dla „nie istnieje" i „należy do innego klienta" (`# Do not reveal whether an ID belongs to another client.`), a grupowy dokłada `_assert_multi_client`. Testy asertują ten 404 dla obcego zamówienia i obcej grupy.

3. **Redakcja finansowa jest dziedziczona, nie przepisana.** Legacy eksport woła `list_contractors_with_orders`, która sama robi `_redact_contractor_finance`; grupowy przechodzi przez `_line_to_read` z `with_finance`, więc `rate_cost`/`rate_revenue` znikają dla ról bez `VIEW_FINANCE` bez ani jednej nowej kopii reguły. Zero nowych list ról — użyto istniejących `TacPlus`, `OrderGroupReader`, `AdminUser`.

4. **Import nie tyka zamówień wielo-konsultantowych.** `_pick_existing_order` filtruje `order.order_group_id is None`, więc linie grup są poza zasięgiem, a komentarz w kodzie wprost broni decyzji o nietykaniu stawki kosztowej (`# Intentionally do not mutate Contract.rate_candidate or ClientOrder.md_rate_cost`) — z testem, który to sprawdza (`assert contract.rate_candidate == Decimal("123.456")` po zastosowaniu importu).

5. **Atomowość zapisu jest realna, nie deklarowana.** Dry-run kończy się `db.rollback()`, apply z niedopasowaniami też — i jest test end-to-end (`test_apply_is_blocked_when_a_file_person_is_unmatched`) oraz test idempotencji, który po drugim przebiegu oczekuje `orders_created: 0, orders_updated: 0, orders_unchanged: 2`.

6. **Gałęzie stanu we froncie są kompletne.** Oba taby mają `isLoading`/`isError` przed pustym stanem, a `MultiConsultantOrdersTab` trzyma pusty stan na `!query.isSuccess` z komentarzem tłumaczącym, dlaczego `isLoading` tu nie wystarcza. Eksport i import mają `try/catch` z toastem oraz `role="alert"`.

7. **Zero migracji = zero ryzyka brakującego lustra w `entrypoint.sh`.** Nowe sortowanie po `ClientOrderGroup.created_at` opiera się o kolumnę, która JEST w `CREATE TABLE client_order_groups` w entrypoincie (`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`), więc nie powstał martwy kod na produkcji.

8. **Formula injection w XLSX zabezpieczone i przetestowane** (`_safe_text` + `test_user_text_cannot_become_an_excel_formula`), a `Content-Disposition` świadomie dodane do `expose_headers` w CORS z komentarzem wyjaśniającym, że bez tego cross-origin fetch pobiera bajty, ale nie zna nazwy pliku.

### `P1` Eksport XLSX niesie „Stawkę kosztową" z cache'owanej kolumny `contracts.rate_candidate`, nie z harmonogramu stawek

`backend/app/api/client_orders.py:650`

> **Nawrót znanej klasy:** Pieniądze liczone ze stalej kolumny (`contracts.rate_*` zamiast `effective_rate_fields`) — temat 0 audytu, findingi #27/#64

```
cost_rate=by_id[order_id][0].rate_candidate,
```

**Dlaczego to boli.** `ContractWithOrdersRead.rate_candidate` jest wypełniane w tym samym pliku jako `rate_candidate=c.rate_candidate` (linia 565) — czyli z kolumny, którą w całym backendzie zapisuje wyłącznie zapis kontraktu (`contracts.py:1140/1515/2554` robią `contract.rate_candidate = contract.effective_candidate_rate(date.today())`); żadne zadanie w tle jej nie odświeża w dniu wejścia w życie kroku. Scenariusz: kontraktor ma stawkę progresywną z krokiem od 01.09; 1 września nikt nie zapisuje kontraktu, więc kolumna dalej trzyma stawkę z pierwszego okresu. Rekruter/DL klika „Pobierz do Excela" i dostaje plik, w którym kolumna C to STARA stawka kosztowa obok AKTUALNEJ stawki przychodowej z zamówienia (`order.rate_client`, linia 651) — czyli marża policzona w arkuszu jest zawyżona lub zaniżona o cały krok stawki. Plik krąży mailem, więc zła liczba żyje dłużej niż ekran. Test `backend/tests/test_client_order_excel_export_api.py` zamraża to zachowanie: asertuje `sheet["C2"].value == 123.456`, czyli dokładnie wartość wpisaną do `Contract.rate_candidate`, bez żadnego harmonogramu. Osobno: naprawa #64 na gałęzi długu podpięła `RATE_SCHEDULE_LOADS` i `effective_rate_fields` do marży w tym samym pliku, ale linii 565 NIE ruszyła — więc po zmerdżowaniu obu gałęzi eksport zostanie jedyną nienaprawioną powierzchnią pieniędzy w tym module.

**Naprawa.** W `list_contractors_with_orders` (linia 565) wyliczaj `rate_candidate` z rezolwera — `effective_rate_fields(c, date.today())["rate_candidate"]` albo `c.effective_candidate_rate(date.today())` — i upewnij się, że zapytanie ma `*RATE_SCHEDULE_LOADS` w `.options(...)`, inaczej dostaniesz `MissingGreenlet` zamiast wartości. Wtedy eksport naprawia się bez zmian, bo czyta to samo pole. Do testu eksportu dołóż kontrakt z krokiem harmonogramu wchodzącym w życie po dacie ostatniego zapisu i asertuj, że w kolumnie C jest stawka z kroku, a nie z kolumny.

### `P2` Kolumna „Liczba MD / Kwota zamówienia" zmienia granulację w obrębie jednego arkusza — dla zamówień kosztowych powtarza kwotę GRUPY w każdym wierszu konsultanta

`backend/app/api/client_order_groups.py:948`

```
allocation=(
                        group.budget_amount if group.is_cost_based else line.md_total
                    ),
```

**Dlaczego to boli.** Dla zamówienia MD wartość jest per linia (`line.md_total`), a dla kosztowego — wspólna kwota całej grupy, wklejona osobno do KAŻDEGO wiersza konsultanta. Sąsiednia kolumna „Zużycie zamówienia" jest w obu przypadkach per linia (`consumption = line.invoiced_total`, linia 931). W efekcie w jednym wierszu stoją obok siebie liczby o różnym zakresie: „zużycie 5 000 z 200 000" przy trzech konsultantach czyta się jak „ta osoba ma budżet 200 000", a suma kolumny F (arkusz ma włączony auto-filtr i ludzie będą go sumować) daje trzykrotność wartości zamówienia. Klient może mieć jednocześnie zamówienia kosztowe i MD (`cost_orders_enabled` jest per klient, `is_cost_based` per grupa — Polkomtel ma oba tryby), więc obie semantyki trafiają do jednego pliku pod jednym nagłówkiem.

**Naprawa.** Rozdziel to na dwie kolumny albo wypełniaj kwotę grupy tylko w pierwszym wierszu grupy; alternatywnie dla `is_cost_based` wstaw `None` w wierszach konsultantów i dołóż jeden wiersz zbiorczy per grupa z kwotą i sumą zafakturowaną. Najtaniej: rozbij `MODEL_HEADERS` na „Liczba MD (konsultant)" i „Kwota zamówienia (całe zamówienie)", żeby nagłówek mówił, czego dotyczy liczba.

### `P2` Nowe filtry dat/budżetu/„kończące się" wpadają w pusty stan, który twierdzi, że klient nie ma żadnych kontraktorów

`frontend/src/components/OrdersAndContractsTab.tsx:262`

> **Nawrót znanej klasy:** Awaria (tu: filtr) renderuje się jako pustka — temat 3 audytu

```
? "Brak kontraktorów u tego klienta. Dodaj pierwszego kontraktora i zamówienie."
```

**Dlaczego to boli.** Rozgałęzienie pustego stanu bierze pod uwagę tylko `searching` (linia 91: `const searching = search.trim().length > 0;`) oraz pigułkę statusu — nie zna nowych `listFilters`. Scenariusz w dwóch kliknięciach: użytkownik zostawia pigułkę „Wszyscy", rozwija „Filtry i sortowanie" i ustawia „Data rozpoczęcia od = 2030-01-01". `filterAndSortContractors` zwraca pustą listę, a ekran mówi „Brak kontraktorów u tego klienta. Dodaj pierwszego kontraktora i zamówienie." — czyli zaprzecza istnieniu danych, które są w pamięci przeglądarki, i zaprasza do założenia duplikatu. To ta sama klasa co „awaria renderuje się jako pustka", tylko przyczyną jest filtr. Lustrzany defekt jest w drugim widoku: `frontend/src/components/client-profile/orders/MultiConsultantOrdersTab.tsx:454/461` rozgałęzia wyłącznie na `search.trim()`, więc przy aktywnych filtrach dat pokazuje „Brak zamówień" / „Ten klient nie ma jeszcze zamówień wielo-konsultantowych.". Panel filtrów jest w `<details>`, więc po zwinięciu użytkownik nie widzi nawet, że coś filtruje.

**Naprawa.** W obu tabach policz `hasActiveFilters` z tej samej funkcji, której używa `OrderListControls.activeFilterCount`, i dodaj trzecią gałąź: „Brak wyników dla aktywnych filtrów" + przycisk „Wyczyść filtry". Warunek `pill === "all" && !search` przestaje wtedy być równoznaczny z „klient nie ma danych".

### `P2` Podgląd importu Nordea nie pokazuje, KTÓRE zamówienie zostanie nadpisane ani jakich wartości — a dopasowanie potrafi trafić w bieżące zamówienie o zupełnie innym numerze

`backend/app/services/nordea_order_import.py:249`

```
    return current[0] if len(current) == 1 else None
```

**Dlaczego to boli.** Dla PIERWSZEGO wiersza danej osoby (`first_for_contractor=True`), gdy numer z pliku nie pasuje do żadnego istniejącego zamówienia, kod schodzi po kolejnych heurystykach aż do „jedyne zamówienie obejmujące dziś" i zwraca je jako cel aktualizacji. Wybrane zamówienie dostaje potem nadpisany numer, obie daty i stawkę przychodową (linie 385-388: `order.title = row.order_number`, `order.rate_client = row.revenue_rate`). Scenariusz: kontraktor ma w Nexusie żywe zamówienie „222" na 2026-01-01..2026-12-31, a plik zawiera historyczny wiersz „279411" 25.02..23.08 — po zastosowaniu importu żywe zamówienie nazywa się „279411", ma skrócony okres i inną stawkę przychodową, a poprzedni numer i stawka przepadły bez śladu. Raport dry-run tego nie ujawnia: zwraca wyłącznie liczniki (`orders_updated`, `orders_unchanged`, …), bez identyfikatorów zamówień i bez wartości przed/po, a `NordeaOrderImportPanel` renderuje dokładnie te liczniki. Blokada 409 dotyczy tylko niedopasowanych/niejednoznacznych OSÓB — dopasowanie do złego zamówienia tej samej osoby nie blokuje niczego. Zapis jest atomowy i admin-only, stąd nie P1, ale „podgląd", który nie pokazuje zmienianych wartości, nie spełnia swojej roli.

**Naprawa.** Dołóż do raportu listę `order_changes` z `order_id`, starym i nowym numerem, okresem i stawką przychodową (dla wierszy, gdzie `_order_state(order)` faktycznie się zmienia — te dane już masz w zmiennej `before`), i wyrenderuj ją w panelu jako tabelę „przed → po". Rozważ też osobny licznik `fuzzy_matched` i blokadę 409, dopóki operator nie zatwierdzi dopasowań, które zeszły poniżej dokładnego numeru.

### `P3` Status importowanego zamówienia (`completed` vs `active`) rozstrzyga `date.today()` na zegarze kontenera w UTC

`backend/app/services/nordea_order_import.py:391`

> **Nawrót znanej klasy:** Czas i sortowanie: UTC vs Warszawa — temat 5 audytu

```
                    if row.end_date < date.today()
```

**Dlaczego to boli.** Daty w pliku Nordea to daty handlowe w polskim kalendarzu, a `date.today()` w kontenerze zwraca dzień UTC. Między 00:00 a 02:00 czasu warszawskiego UTC pokazuje jeszcze poprzednią dobę, więc zamówienie kończące się „wczoraj" wg Warszawy zostanie zapisane jako `active`, a nie `completed`. To samo dotyczy linii 246-247 (wybór „zamówienia obejmującego dziś") i 428 (`effective_framework_rate(date.today())`) oraz stempla daty w nazwie pliku eksportu (`order_excel_export.py`, `orders_export_filename`). Skutek jest wąski — import odpala człowiek, rzadko po północy — ale to dokładanie kolejnych wywołań do rodziny 113 już zinwentaryzowanych.

**Naprawa.** Użyj wspólnego helpera granicy doby w `Europe/Warsaw` (na gałęzi długu powstał do tego fundament w `app/core/business_time.py`) zamiast gołego `date.today()` — jedno wywołanie na początku `import_nordea_orders`, przekazywane dalej jako parametr, żeby cały bieg używał JEDNEJ daty.

### `P3` Parser CSV waliduje tylko nagłówki kolumn A i B, a stawki bierze z fallbacku pozycyjnego — zmieniony nagłówek cicho podmienia stawkę przychodową na ramową

`backend/app/services/nordea_order_import.py:142`

```
        indexes.setdefault(label, index)
```

**Dlaczego to boli.** Dopasowanie semantyczne obejmuje sześć kolumn, ale walidacja struktury sprawdza tylko `keys[0] != "numerzamowienia" or keys[1] != "kontraktor"` i `len(header) < 7`. Jeśli Finanse przyślą plik, w którym nagłówek stawki brzmi np. „Stawka przychodowa netto" (klucz przestaje pasować) i jednocześnie doszła kolumna przed stawkami, `setdefault` po cichu przypnie `revenue` do indeksu 5, czyli do innej kolumny — najpewniej do stawki ramowej. Import zapisze wtedy stawkę ramową jako przychodową zamówienia, a raport dry-run pokaże tylko `orders_updated: N`, bez ani jednej kwoty, więc operator nie ma jak tego zauważyć przed zapisem. Wymaga dwóch zmian w pliku naraz, stąd P3, ale awaria jest cicha i dotyczy kwot.

**Naprawa.** Wymagaj dopasowania semantycznego dla obu kolumn stawkowych (`revenue`, `framework`) i podnoś `NordeaImportError` z nazwą nierozpoznanego nagłówka zamiast schodzić na pozycje — pozycyjny fallback zostaw najwyżej dla `start`/`end`, gdzie pomyłka jest widoczna w podglądzie okresu.

---

## PR #1228 — `wymaga-poprawki`

PR usuwa jedną linię: filtr zakresu Delivery Leada (`_apply_delivery_lead_job_scope`) z zapytania w `GET /api/jobs`, żeby DL bez przypisań nie widział „Brak rekrutacji". Wszystkie pozostałe bramki (szczegóły, mutacje, 26 wywołań `_ensure_delivery_lead_job_visible`, `list_train_names`) są nietknięte — to naprawdę chirurgiczna zmiana i test regresji jest prawdziwym testem integracyjnym przez zmienioną warstwę, nie mockiem.

Problem jest w tym, CO niesie projekcja listy. `JobResponse` zawiera `champion_profile` (JSONB), a `_redact_delivery_lead_job_finance` zeruje wyłącznie `salary_min`/`salary_max`. Efekt: Delivery Lead jednym `GET /api/jobs?page_size=100` dostaje pełny Profil Championa KAŻDEJ rekrutacji w organizacji — łącznie z `verification.consultant.consultant_name` + `consultant_candidate_id` (nazwisko i ID naszego konsultanta u obcego klienta), `internal_consultant_insight`, `client.key_corrections`, `sourcing.target_companies` i pytaniami screeningowymi z `ideal_answer`/`deal_breaker`. Dedykowany endpoint na dokładnie te dane, `GET /api/jobs/{id}/champion-profile`, dla tej samej osoby i tej samej oferty nadal zwraca 403. To odtworzenie klasy wycieku zamkniętej w #1069 przez równoległą powierzchnię — dokładnie ten wzorzec, który `champion_suggestions.py` opisuje jako powód swojego istnienia. Poprawka jest dwuliniowa: dopisać `champion_profile` (i `close_notes`) do `_redact_delivery_lead_job_finance` albo w ogóle nie wystawiać `champion_profile` w projekcji listy — front listy go nie konsumuje.

Drugorzędnie: dla persony, pod którą ten PR powstał (DL z pustym grafem przypisań) 100% wierszy rejestru kończy się 403 po kliknięciu — co utrwala własny test PR-a. Przyczyna źródłowa (brak wierszy przypisań) nie została ruszona.

Żadnej z pozostałych klas z audytu PR nie wprowadza: zero migracji, zero pieniędzy (stawki/marża/MD nietknięte), zero zmian we froncie, zero nowych zapytań react-query, zero skopiowanych list ról.

**Co zrobione dobrze.** Zmiana jest naprawdę chirurgiczna — jedna linia zapytania, bez dotykania niczego obok. Konkretnie, i to jest rzadkie:

1. **Bramki nie zostały „przy okazji" rozluźnione.** Wszystkie 26 wywołań `_ensure_delivery_lead_job_visible`, `_assert_delivery_lead_job_visible`, `_assert_delivery_lead_client_visible`, `_assert_delivery_lead_cross_client_disabled` i `_assert_delivery_lead_finance_write` są nietknięte. `_apply_delivery_lead_job_scope` nadal działa w `list_train_names` (jobs.py:1125), więc autor nie zrobił globalnego „usuń wszystkie wystąpienia".

2. **Test regresji przechodzi przez zmienioną warstwę, a nie obok niej.** `test_delivery_lead_list_shows_jobs_outside_relationship_scope` robi prawdziwy login (`POST /api/auth/login`), prawdziwy `GET /api/jobs` przez `app_client` i prawdziwy wiersz w bazie. DL jest seedowany bez żadnego przypisania, więc `resolve_dashboard_scope` zwraca `delivery_clients` z PUSTYM zbiorem par — czyli przed zmianą lista byłaby pusta i test padłby. To nie jest test, który przechodziłby też przed poprawką.

3. **Użyto `app_client`, nie `client`.** Fixture `client` w tym repo daje ciche SKIPPED — test wyglądałby na zielony, nie uruchamiając się. Autor tej pułapki uniknął.

4. **Test pina też połowę NEGATYWNĄ.** `assert detail.status_code == 403` sprawia, że gdyby ktoś później „uprościł" `get_job` zdejmując z niego guard, build zrobi się czerwony. Test broni granicy, której PR nie przesuwa — to dokładnie ten kształt testu, którego brakuje w większości PR-ów rozluźniających RBAC.

5. **Test jednostkowy został PRZEMIANOWANY, nie skasowany.** `test_legacy_job_surface_uses_exact_delivery_scope_and_hides_budget` → `test_scoped_job_operations_...` — semantyka `_apply_delivery_lead_job_scope` (włącznie z deny-all `(-1, -1)` przy pustym zbiorze) zostaje pokryta, mimo że lista już jej nie woła. Łatwiejszą drogą było usunięcie testu razem z wywołaniem.

6. **Komentarz w kodzie wyjaśnia DLACZEGO, nie CO** — i wprost nazywa kompromis („details and every mutation below\"). Że jedna z obietnic tego komentarza (redakcja finansów) nie pokrywa `champion_profile`, to osobna sprawa — ale intencja jest zapisana tam, gdzie następny czytelnik ją znajdzie.

7. **Zero kontaktu z klasami defektów z audytu:** brak migracji (więc pytanie o lustro w `entrypoint.sh` i `ADD CONSTRAINT` bez `DROP` nie powstaje), brak jakiejkolwiek arytmetyki pieniędzy (`effective_rate_fields`, `rate_unit`, MD, MRR — nietknięte), brak zmian we froncie (więc brak nowych `useQuery` bez `isError` i `useMutation` bez `onError`), brak `date.today()`, brak nowej listy ról skopiowanej w kolejne miejsce, brak nowego dostępu do relacji wymagającego eager-loadu (usunięcie filtra `tuple_()` nie dodaje żadnego lazy-loada).

### `P1` Rejestr /api/jobs oddaje Delivery Leadowi champion_profile KAŻDEJ oferty w organizacji, podczas gdy dedykowany endpoint na te same dane nadal zwraca mu 403

`backend/app/api/jobs.py:511`

> **Nawrót znanej klasy:** rbac containment przez równoległą powierzchnię — bramka na jednej trasie, ta sama treść bez bramki na drugiej (klasa zamknięta w #1069 / #791→#815→#819, opisana w test_job_scope_contract.py: „a role guard counts as gated")

```
    # same read-only list contract while finance fields remain redacted.
    query = select(Job)
```

**Dlaczego to boli.** Komentarz obiecuje, że „finance fields remain redacted", ale jedyna redakcja DL-owa w tej pętli to `_redact_delivery_lead_job_finance` (jobs.py:775-183), która zeruje WYŁĄCZNIE `salary_min` i `salary_max`. `JobResponse` (backend/app/schemas/job.py:212) niesie `champion_profile: Optional[Any] = None`, a serializacja listy to gołe `JobResponse.model_validate(j).model_dump()` (jobs.py:751). `redact_job_for_viewer` czyści `champion_profile`, ale tylko dla nie-operacyjnego viewera (`user_has_candidate_read(user)` przepuszcza delivery_lead). Do tego PR-a filtr `(jobs.client_id, jobs.tac_id) IN (...)` obcinał wiersze, więc DL nigdy nie dostawał Championa spoza swoich par; teraz dostaje wszystkie.

Scenariusz: Delivery Lead (dowolny, w tym z pustym grafem przypisań) woła `GET /api/jobs?page_size=100&status=published` i w odpowiedzi ma pełny Profil Championa każdej oferty — `verification.consultant.consultant_name` i `consultant_candidate_id` (nazwisko + ID kandydata naszego konsultanta pracującego u OBCEGO klienta), `verification.client.key_corrections` (czego klient naprawdę potrzebuje vs. co napisał), `internal_consultant_insight`, `sourcing.target_companies`/`keywords`, `screening_questions[].ideal_answer` i `.deal_breaker`, `briefing.audio_storage_key`. Ta sama osoba na `GET /api/jobs/{id}/champion-profile` (jobs.py:1557 → `await _ensure_delivery_lead_job_visible(job, current_user, db)`) i na `GET /api/jobs/{id}` (jobs.py:1148) dostaje 403 — czyli dwie trasy do jednego payloadu, jedna bramkowana, druga nie. To dokładnie klasa, dla której powstało `ensure_champion_job_visible`; `champion_suggestions.py:53` nazywa ją wprost: „any Delivery Lead could read another client's Champion draft by incrementing an integer". Tam trzeba było enumerować po jednym id i zbudowano nawet obronę 404-zamiast-403 przeciw oracle'owi enumeracji — tu wystarczy jedno żądanie z `page_size=100`. Wg pamięci repo ~1000 ofert ma wypełniony Champion, więc to nie jest teoria. Działa na produkcji od 21.08.

Poboczne tym samym mechanizmem: `close_notes` i `custom_fields` (oba na liście `_VIEWER_REDACTED_JOB_FIELDS`, czyli repo uważa je za wrażliwe) też lecą do DL dla całej organizacji.

**Naprawa.** Najprościej: dopisać do `_redact_delivery_lead_job_finance` (jobs.py:175) `payload["champion_profile"] = None` i `payload["close_notes"] = None` — funkcja jest wołana i w liście (778) i w detalu (1191), więc jedna zmiana pokrywa obie powierzchnie, a nazwę warto poszerzyć na `_redact_delivery_lead_job_fields`. Czyściej: nie wystawiać `champion_profile` w projekcji listy w ogóle — `grep -rn champion_profile frontend/src/` pokazuje, że konsumentami są wyłącznie detal (`ChampionProfileEditor`, `ChampionCard`, `ScreeningSheet`) i publiczna karta share, a nie `JobsListV2`; lista wozi ten JSONB bez odbiorcy. Test: rozszerzyć `test_delivery_lead_list_shows_jobs_outside_relationship_scope` o asercję, że wiersz spoza zakresu ma `champion_profile` puste/None — dziś ten test przechodzi z pełnym Championem w payloadzie.

### `P2` Dla persony, pod którą PR powstał (DL bez przypisań), każdy wiersz rejestru kończy się 403 po kliknięciu — przyczyna źródłowa nietknięta

`backend/tests/test_jobs_filters_multi.py:204`

> **Nawrót znanej klasy:** „link widoczny, klik = 403" — bramka wejścia poszerzona bez poszerzenia dostępu do zasobu (klasa z #1215 Talent Radar i #1216 generator B2B)

```
        detail = await app_client.get(f"/api/jobs/{outside_job_id}", headers=headers)
        assert detail.status_code == 403
```

**Dlaczego to boli.** `delivery_lead_job_pairs` (recruitment_access.py:426) ma w docstringu wprost: „An empty set is deny-all and must never fall back to the organization." PR nie naprawia pustego zbioru — omija go na jednej trasie. Dla DL bez żadnego wiersza w ClientTacAssignment (czyli dokładnie dla przypadku z opisu PR: „an empty relationship graph must not turn the top-level /jobs register into 'Brak rekrutacji'") zbiór par jest pusty, więc `_assert_delivery_lead_job_visible` odrzuca KAŻDĄ ofertę. Rejestr pokazuje komplet, ale 100% wierszy jest nieotwieralnych — „Brak rekrutacji" zamieniło się w listę martwych linków. To ta sama sygnatura, którą CLAUDE.md opisuje przy Talent Radar i generatorze B2B: „link widoczny, klik = 403" — z tą różnicą, że tam (#1215, #1216) domknięto ją otwierając też dane pod spodem, a tu otwarto samą listę. Test PR-a utrwala ten stan jako kontrakt.

Łagodzące i dlatego P2, nie wyżej: front obsługuje to poprawnie — `frontend/src/app/jobs/[id]/page.tsx:1128` renderuje `QueryStateNotice` ze stanem `forbidden` i komunikatem „Nie masz uprawnień do tej rekrutacji. Rekrutacja istnieje — poproś o dodanie Cię do jej zespołu albo o rozszerzenie roli.", więc to nie jest 403 udające pustkę ani awarię.

**Naprawa.** Rozstrzygnąć, co ma być prawdą, zamiast trzymać dwie: albo (a) uzupełnić dane — DL-om brakuje wierszy `ClientTacAssignment`/`DeliveryLeadClientAssignment` i to jest właściwa naprawa, jednorazowa i bez zmiany kodu; albo (b) świadomie otworzyć ODCZYT detalu dla DL z tą samą redakcją pól co lista (salary + champion_profile + close_notes), zostawiając mutacje i pipeline na dotychczasowym `_ensure_delivery_lead_job_visible`. Wariant (b) zamyka też P1, bo redakcja staje się jedną, wspólną regułą dla obu powierzchni. Jeśli stan obecny ma zostać — warto to zapisać w CLAUDE.md, bo dziś docstring `delivery_lead_job_pairs` mówi coś przeciwnego niż zachowanie `/api/jobs`.

---

## PR #1229 — `ok-z-uwagami`

PR robi dwie rzeczy: (1) wyjmuje numer zamówienia spod natywnego `<button>` w nagłówku karty, żeby dało się go zaznaczyć i skopiować (przycisk rozwijania przenosi się na awatary + chevron, z `aria-label`/`aria-controls`), oraz (2) dokłada do pickera konsultanta podpowiedź stawki kosztowej zł/MD z aktywnego lub kończącego się kontraktu tej osoby u BIEŻĄCEGO klienta, plus flagę „ten konsultant ma u klienta kontrakty z różnymi stawkami".

Część finansowa jest zrobiona dokładnie tak, jak wymaga tego repo, i nie wprowadza ponownie żadnej z udokumentowanych klas defektów. Stawka idzie przez `contract.effective_candidate_rate(on)` (harmonogram), a NIE przez cache'owaną kolumnę `contracts.rate_candidate` — test wprost seeduje sprzeczny cache (`rate_candidate=999`) i asertuje 560 z harmonogramu, więc dowód przechodzi przez zepsutą warstwę, a nie ją mockuje. Jednostka stawki jest respektowana (`monthly_rate` → ÷22, więc daily robi round-trip 1:1, hourly przez `billing_hours_per_month`), waluta przeliczana przez kanoniczne `rates_to_pln`, a brak kursu daje `None` zamiast cichego 1:1 (test z walutą syntetyczną i kursem 4.0). „Żywy kontrakt" to `active` + `ending` — `ending` jest w środku, więc nie gubi ostatnich 30 dni. Filtr statusów jest listą pozytywną (`LIVE_CONTRACT_STATUSES`/`CLIENT_CONTRACT_STATUSES`), nie negacją; jedyna negacja (`status != void`) dotyczy zbioru „historia do porównania" i jest tam poprawna. `selectinload(Contract.candidate_rate_schedule)` jest obecny dokładnie tam, gdzie resolver sięga po relację — a `monthly_rate`/`currency`/`rate_unit` to kolumny, więc nie ma innej ścieżki na `MissingGreenlet`. Brak migracji → lustro w `entrypoint.sh` nie jest potrzebne. Redakcja stawki dla ról bez uprawnień wylicza się z JEDNEJ istniejącej funkcji `_has_md_line_management_role`, a nie z nowej kopii listy ról; klient-scope dla DL zapewnia `DlAssignedOrAdmin` na trasie (sprawdzone: DL bez `DeliveryLeadClientAssignment` dostaje 403, HoR przechodzi trasę, ale dostaje `None`). Testy backendu idą przez prawdziwy endpoint i prawdziwą bazę (`app_client`, nie skipowany fixture `client`), testy FE przez realny handler zmiany osoby.

Jedno realne, choć drobne, znalezisko: ostrzeżenie o rozbieżnych stawkach potrafi się pokazać razem z PUSTYM polem, twierdząc, że coś do niego wstawiono.

Sprawdziłem też i celowo NIE zgłaszam: `date.today()` (zegar kontenera w UTC) — użyte do rozwiązania kroku harmonogramu i daty kursu; okno błędu to 1-2 h doby warszawskiej na polu, które jest tylko podpowiedzią i które operator i tak nadpisuje, a cała reszta odczytu stawek kontraktu w repo (`_effective_rate_fields(contract, date.today())`) używa tej samej konwencji — to ambient dług, nie regresja tego PR-a. Podobnie stała 22 MD/mc, już zduplikowana w siedmiu miejscach backendu. Reset pola przez `useEffect([open, line, group])` przy zmianie referencji `group` jest sprzed tego PR-a.

**Co zrobione dobrze.** Rzeczy, które ten PR zrobił konkretnie dobrze — nie ogólnikami:

1. **Pieniądze idą z harmonogramu, nie z cache'a — i jest na to dowód przechodzący przez zepsutą warstwę.** `rate_per_md` woła `contract.effective_candidate_rate(on)`, czyli ten sam prymityw, na którym stoi `_effective_rate_fields` w `contracts.py`. Test `test_options_prefill_active_client_rate_warns_on_history_and_order_edit_is_local` seeduje CELOWO sprzeczny cache (`rate_candidate=Decimal(\"999.000\")`) obok dwustopniowego harmonogramu (540 → 560) i asertuje 560 na drucie oraz `stored.rate_candidate == Decimal(\"999.000\")` po zapisie linii. To jest dokładnie ta klasa defektu, która na tym repo wraca najczęściej (finding #64 i #23 w backlogu), i tutaj jest zamknięta dowodowo, a nie deklaratywnie.

2. **Jednostka i waluta są policzone, a nie zignorowane.** Kontrakt trzyma stawkę h/dzień/mc, linia zamówienia zawsze zł/MD. PR normalizuje przez `contract.monthly_rate(rate)` (ten sam mechanizm co marża kontraktu), potem dzieli przez 22 — więc `daily` robi round-trip 1:1, a `hourly` przechodzi przez `billing_hours_per_month`. Kwoty w obcych walutach idą przez kanoniczne `rates_to_pln`, które przy braku kursu zwraca `None`, a nie ciche 1:1 — i PR to honoruje (`if monthly is None or rate_to_pln is None: return None`), więc 100 EUR/h nie wjedzie do formularza jako 100 zł/MD. Test drugi jest tu wzorowy: 19,25/h × 160 h × kurs 4,0 ÷ 22 = 560 zł/MD, czyli tyle samo co historyczne 560 zł/dzień — jednocześnie broni przed skopiowaniem surowej kwoty i przed fałszywym ostrzeżeniem dla równoważnych jednostek.

3. **`ending` jest w środku, `void` na zewnątrz — filtry są listami pozytywnymi.** `LIVE_CONTRACT_STATUSES = (active, ending)` reużyte, nie przepisane; nie ma tu ani `status == active` (gubiącego ostatnie 30 dni), ani `!= draft` (wpuszczającego `ready_for_signature`/`void`).

4. **`selectinload` jest tam, gdzie kod sięga po relację, i tylko tam.** Zapytanie historii dociąga `Contract.candidate_rate_schedule`; reszta odczytów w `rate_per_md` to czyste kolumny (`rate_unit`, `billing_hours_per_month`, `currency`, `status`, `start_date`). Sprawdziłem: nie ma ścieżki na `MissingGreenlet`. Lista pickera nadal ciągnie KOLUMNY, a pełne encje tylko dla kandydatów, którzy i tak trafią do źródła A.

5. **Redakcja uprawnień nie zakłada kolejnej kopii listy ról.** `include_rate_suggestions = _has_md_line_management_role(user)` — jedna, już istniejąca funkcja, ta sama, która rządzi zapisem `rate_cost`. Client-scope dla DL zostaje tam, gdzie był (`DlAssignedOrAdmin` na trasie), zgodnie z tym, co ta funkcja sama o sobie pisze w docstringu. Gate jest liczony RAZ, przed pętlą. Test z realnym userem `head_of_recruitment` sprawdza obie flagi, a nie tylko kwotę — więc `has_different_client_contract_rates` nie wycieka jako kanał boczny. Redakcja jest przy tym węższa niż `_can_see_finance`, czyli w bezpieczną stronę.

6. **Wybór kontraktu dla wiersza został poprawiony przy okazji, świadomie i z zachowaniem starego tie-breaku.** Żywy kontrakt wygrywa z nowszym szkicem, ale gdy żywego nie ma, `max(rows, key=lambda row: (row[6] or date.min, row[0]))` odtwarza dokładnie dawne `ORDER BY start_date DESC NULLS LAST, id DESC`. Dodatkowo jest fallback `if chosen is None`, mimo że przy obecnych zbiorach statusów jest nieosiągalny — to obrona przed przyszłym rozjazdem `LIVE_*` vs `CLIENT_*`, nie martwy kod.

7. **Zmiana w nagłówku karty jest zrobiona do końca, a nie „na oko".** Numer wychodzi spod natywnego `<button>` (który przejmował gest myszy i uniemożliwiał zaznaczenie), przycisk rozwijania dostaje `aria-label` z numerem zamówienia i `aria-controls`, a test asertuje jedno i drugie: `expect(orderNumber.closest(\"button\")).toBeNull()` ORAZ że składanie/rozkładanie nadal działa. Regresja funkcji przy poprawianiu ergonomii jest tu wykluczona testem, nie zapewnieniem.

8. **Zero migracji, zero nowych zapytań FE.** Nie ma czego lustrzeć w `entrypoint.sh`, nie ma nowego `useQuery` bez `isError`, nie ma nowego klucza cache. Istniejący `ConsultantPicker` ma już poprawną kolejność `isError → !isSuccess → pusty stan` i PR jej nie ruszył. Harness `/preview/order-consultant-picker` został zaktualizowany o nowe pola, więc wizualna weryfikacja obu wariantów (z podpowiedzią i bez) dalej działa bez logowania.

### `P3` Ostrzeżenie „Wstawiono stawkę z aktywnego kontraktu" renderuje się także wtedy, gdy nic nie wstawiono i żadnego aktywnego kontraktu nie ma — pole zostaje puste, a komunikat mówi coś nieprawdziwego

`frontend/src/components/client-profile/orders/ConsultantLineModal.tsx:317`

```
{person?.has_different_client_contract_rates ? (
              <p
                role="status"
                className="mt-2 flex items-start gap-1.5 text-xs text-amber-700"
              >
                <AlertTriangle
                  className="mt-0.5 h-3.5 w-3.5 shrink-0"
                  aria-hidden="true"
                />
                Uwaga: ten konsultant ma u klienta kontrakty z różnymi
                stawkami. Wstawiono stawkę z aktywnego kontraktu — sprawdź,
                którą zastosować.
              </p>
            ) : null}
```

**Dlaczego to boli.** Obie flagi wracają z backendu NIEZALEŻNIE od siebie: `suggested` liczy się tylko z kontraktów `active`/`ending`, a `has_different` porównuje WSZYSTKIE nieanulowane, także `ended` i `draft` (backend/app/services/client_order_lines.py:244-254: `live = [c for c in contracts if c.status in LIVE_CONTRACT_STATUSES]` … `current = max(live, …) if live else None` … `suggested = rate_per_md(current) if current is not None else None`, a obok `distinct_rates = {… for contract in contracts if contract.status != ContractStatus.void …}`). Scenariusz osiągalny zwykłymi danymi i dokładnie ten, wokół którego zbudowany jest cały moduł — konsultant wraca do klienta: kontrakt `ended` ze stawką 500 zł/dzień (nie jest w `CLIENT_CONTRACT_STATUSES`, ale JEST w historii) plus nowy `draft` ze stawką 700 zł/dzień, zero `active`/`ending`. Osoba trafia do źródła A po drafcie, więc wiersz istnieje; `suggested_rate_cost = null`, `has_different_client_contract_rates = true`. W modalu `handlePersonChange` ustawia `setRateCost("")`, a pod pustym polem zapala się bursztynowe ostrzeżenie twierdzące, że stawkę wstawiono i że pochodzi z aktywnego kontraktu — podczas gdy aktywnego kontraktu nie ma, a pole jest puste. Drugi wariant: dwa `draft` z różnymi stawkami. Skutek jest wyłącznie informacyjny — `canSubmit` wymaga `parseDecimalInput(rateCost) !== null`, więc pusta stawka nie zapisze się do bazy — ale operator dostaje sprzeczny ekran i może pójść skopiować kwotę z kontraktu historycznego, którego świadomie nie podpowiadamy. Żaden z czterech nowych testów backendu tego stanu nie pokrywa: `test_options_do_not_suggest_a_rate_from_a_draft_contract` seeduje JEDEN draft, więc `has_different` wychodzi `false` i rozbieżność się nie ujawnia.

**Naprawa.** Rozdzielić dwa komunikaty zamiast jednego warunku: przy `person.suggested_rate_cost != null` zostawić dzisiejszy tekst, a przy `has_different_client_contract_rates && suggested_rate_cost == null` pokazać wariant bez fałszywego zdania — np. „Ten konsultant ma u klienta kontrakty z różnymi stawkami, ale żaden nie jest aktywny — wpisz stawkę dla tej linii.". Dołożyć test backendu (`ended` + `draft` o różnych stawkach, brak `active`) asertujący `suggested_rate_cost is None` przy `has_different_client_contract_rates is True`, oraz test FE na wariant komunikatu dla tej pary wartości — inaczej rozjazd wróci przy najbliższej zmianie katalogu statusów.

---

## Kolizja: gałąź długu × PR-y codex — `wymaga-poprawki`

## 1. Konflikty tekstowe — ZERO

Zweryfikowane przez faktyczny rebase w klonie `/tmp/rebasetest` (`git rebase codexmain`, 21 commitów): `Successfully rebased and updated refs/heads/work`, bez ani jednego konfliktu. Dodatkowo `git merge-tree --write-tree HEAD origin/main` zgłasza tylko `CONFLICT (add/add): docs/tech-debt-backlog.json` — a to artefakt MERGE'a, nie rebase'a: trzy commity dokumentacyjne (`e595604f`, `a7f41471`, `2b5ff779`) są na obu stronach jako różne SHA tego samego patcha, więc rebase je pomija (`warning: skipped previously applied commit`) i backlog składa się czysto (`eb929000` po rebase, JSON parsuje się, struktura `meta/themes/findings` zachowana).

Wspólnych plików jest 10: `client_orders.py`, `client_order_groups.py`, `client_order_lines.py`, `contracts.py`, `main.py`, `entrypoint.sh`, `ci-gate.yml`, `.gitleaks.toml`, `docs/tech-debt-audit-2026-08-21.md`, `docs/tech-debt-backlog.json`. W każdym z nich strony trafiły w rozłączne miejsca:
* `contracts.py` — dług wycina `_effective_rate_fields` (:126-162) i zostawia alias; codex rusza `create_contract` (:1132) i `update_contract` (:1536). Rozłączne.
* `client_orders.py` — dług: `_compute_monthly_margin`, `_order_to_read`, `list_contractors_with_orders` options, `create_contract_with_order`; codex: `_activate_complete_draft`, export, `delete_order_po`, `update_order`. Sąsiadują, nie nakładają się.
* `client_order_groups.py` — dług zmienia 5 linii w konstruktorze `OrderGroupRead` (budget_*), codex zmienia sąsiednie (`can_add_consultant`, `filename`/`has_file`). Git złożył poprawnie: po rebase `budget_amount=... if with_finance else None` ORAZ `can_add_consultant=group.status in (ACTIVE, SCHEDULED)`.
* `client_order_lines.py` — dług zmienia WYŁĄCZNIE docstring `_sort_key`.
* `main.py`, `entrypoint.sh`, `ci-gate.yml` — dopisy w różnych sekcjach.

Niezacommitowane zmiany z drzewa roboczego też wchodzą czysto — sprawdzone `patch --dry-run` każdego pliku osobno przeciw wersji z `origin/main`; w szczególności `frontend/src/app/clients/[id]/page.tsx`, gdzie dług przepisuje trzy `<details>` na `LazyDetails` (oryginalne linie 879-942 i 965-980), a codex dokłada `clientName` do `OrdersAndContractsTab` (949-958). Luka między hunkami.

Po scaleniu `ruff check` przechodzi na czterech kluczowych modułach.

## 2. Konflikty semantyczne — SĄ, i to one są problemem

**Rozstrzyganie stawek — dwa źródła, zapis do jednego, odczyt z drugiego.** Dług przestawia CZYTANIE marży na harmonogramy (`_compute_monthly_margin` → `effective_rate_fields`), a codex w tym samym czasie dokłada ZAPIS stawki kosztowej wprost do cache'owanej kolumny (`client_orders.py:1049`, `order.contract.rate_candidate = rate_candidate`, wołane z `OrdersAndContractsTab` po `POST /orders` + `PATCH`). Dla kontraktu z `candidate_rate_schedule` edycja kończy się 200, pole na ekranie się zmienia (czyta tę samą kolumnę), a marża i cała analityka nie. Nikt tego nie zobaczy — to F1.

**Ta sama odpowiedź miesza źródła.** Dług naprawił `latest_order_monthly_margin`, ale nie ruszył `rate_candidate=c.rate_candidate` dwie linie wyżej (`client_orders.py:585`). Karta kontraktora pokazuje więc stawkę kosztową z kolumny obok marży z harmonogramu — „przychodowa − kosztowa ≠ marża". Codex wynosi dokładnie tę stalą kolumnę do nowego Excela (`:650`). To F3.

**Filtr statusów przychodowych — codex zdejmuje niezmiennik, na którym dług oparł nową listę pozytywną.** `REVENUE_BEARING_STATUSES = (active, ending, ended)` z `contract_rates.py` jest bezpieczne TYLKO dlatego, że o „czy kontrakt żył" rozstrzygają daty (`end_date IS NULL OR >= on`). PR #1225 usuwa koercję `_status_after_end_date_change` przy jawnym statusie (`contracts.py:1536`) i otwiera `ContractCreate/Update.status` (`schemas/contract.py:140,188`) — od teraz da się zapisać `ended` z pustą `end_date` (analityka liczy go jako aktywny bezterminowo, a `admin_clients_overview._LIVE_CONTRACT_STATUSES` już nie) oraz ustawić `active` z pominięciem `activate_contract`, którego docstring nadal głosi „The ONLY path to ``active``" i który jako jedyny sprawdza podpis kwalifikowany. Test niezmiennika został przepisany na nowe zachowanie, więc nic tego nie złapie. To F2 — najgroźniejsze w tej parze.

**Liczenie konsultantów — zgodne, ale rozjeżdżają się definicje.** Dług konsekwentnie przechodzi na `active|ending` (`my_clients`, `admin_clients_overview`), codex w module zamówień liczy `is_active` po `ClientOrderStatus.active` — inna domena, nie kolizja. Kolizja pojawia się dopiero przez F2: gdy `ended` da się zapisać bez daty, `admin_clients_overview` (active|ending) i `metrics._active_contracts` (+ended) zaczynają podawać różne liczby dla tego samego wiersza.

**Granice okresów.** Ta sama fala długu wprowadziła `app.core.scheduling.business_today()` i wpięła je w `contract_alerts._promote_statuses` (kontener chodzi w UTC). Codex dokłada NOWĄ granicę doby na `date.today()` — `order_group_lifecycle.py:50` i `client_order_groups.py:312`. Dwa mechanizmy w tym samym module zamówień datują się różnymi dobami przez 1-2 h na dobę. To F5. Ta sama klasa dotyczy zresztą nowego kodu długu (F7).

**Redakcja finansowa vs istniejący front.** Dług zaczyna redagować `budget_amount/used/remaining` dla ról bez VIEW_FINANCE (`client_order_groups.py:453`), ale nie tknął `OrderGroupCard.BudgetBar`, który liczy `?? 0` → `depleted = true` → czerwony pasek. Codex ten plik przepisał i tego nie naprawił, bo u niego pole nigdy nie było `null`. To F4.

## 3. Rekomendacja scalania

**Rebase, nie merge** — `git rebase origin/main` na `chore/debt-fala1-fundamenty` przechodzi bez interwencji i sam zdejmuje trzy zdublowane commity dokumentacyjne. Merge zmusiłby do ręcznego rozstrzygania `tech-debt-backlog.json`.

Plik po pliku:
* **`backend/app/api/contracts.py`** — bierz OBIE strony bez zmian (alias `_effective_rate_fields = effective_rate_fields` z długu + jawny status z codeksu), ale osobnym commitem domknij F2: `→ active` przez `activate_contract`, plus guard „ended/ending wymaga `end_date`". Nie ruszaj `_status_after_end_date_change` w `/bulk-extend` (:2547) ani `/amendments` (:2883) — te trzy miejsca dług już opisał w `contract_lifecycle.reopen_contract`.
* **`backend/app/api/client_orders.py`** — bierz OBIE. Funkcje długu (`_compute_monthly_margin`, `_order_to_read`, options w `list_contractors_with_orders`, `create_contract_with_order`) zostają w wersji z harmonogramami; funkcje codeksu (`_activate_complete_draft`, export, `delete_order_po`) zostają. Domknij F1 i F3 wewnątrz `list_contractors_with_orders` i `update_order` — obie funkcje mają już `RATE_SCHEDULE_LOADS` wczytane, więc to zmiana o kilka linii.
* **`backend/app/api/client_order_groups.py`** — auto-merge jest POPRAWNY, nie ruszaj go. Nowy `export_order_groups` codeksu przechodzi przez `_group_to_read(with_finance=_can_see_finance(user))`, więc redakcja długu obejmuje też Excela — to zachowanie chciane. Napraw za to front (F4).
* **`backend/app/services/client_order_lines.py`** — bierz stronę codeksu w całości; dług zmienił tam wyłącznie tekst docstringu `_sort_key` i ten tekst przetrwał rebase nienaruszony. `_rate_suggestion` codeksu już używa `effective_candidate_rate` z eager-loadem (`:369`) — to jest wzorzec, do którego trzeba dociągnąć `update_order`.
* **`backend/app/services/order_group_lifecycle.py`** — plik wyłącznie codeksowy, ale to tam wchodzi F5 (`business_today()`); sygnatura `materialize_scheduled_order_groups(today=...)` przyjmie to bez zmian u wołających.
* **`backend/entrypoint.sh`, `main.py`, `ci-gate.yml`, `.gitleaks.toml`** — auto-merge, bez uwag. Lustro DDL dla 0238/0239 jest obecne, `ADD COLUMN IF NOT EXISTS` w komplecie.
* **`frontend/src/app/clients/[id]/page.tsx`** — obie strony, konflikt zerowy.

Kolejność: rebase → F2 (blokuje pieniądze w raporcie zarządczym) → F1+F3 (jeden commit, ten sam plik) → F4/F5/F6 → F7 jako sprzątanie.

**Co zrobione dobrze.** Rebase jest CZYSTY — 21 commitów, zero konfliktów, i to nie przypadek: obie strony trzymały się rozłącznych funkcji nawet w tych samych plikach. Auto-merge w `client_order_groups.py` złożył sąsiadujące hunki (`budget_amount if with_finance` długu + `can_add_consultant in (ACTIVE, SCHEDULED)` codeksu) dokładnie tak, jak trzeba.

Po stronie codeksu jakość jest wysoka i miejscami wyższa niż w kodzie, który poprawia:
* `client_order_lines._rate_suggestion` (#1229) rozwiązuje stawkę przez `contract.effective_candidate_rate(on)` Z eager-loadem (`:369 .options(selectinload(Contract.candidate_rate_schedule))`) i jawnym uzasadnieniem w docstringu — to jest wzorzec, którego brakuje `update_order`. `LIVE_CONTRACT_STATUSES` obejmuje `active` i `ending`, czyli dokładnie tę samą definicję „konsultant pracuje", do której niezależnie doszła gałąź długu.
* `nordea_order_import` (`:428`) używa `effective_framework_rate` i dopisuje KROK harmonogramu zamiast nadpisywać kolumnę — czyli robi to, czego brakuje ścieżce `rate_candidate`.
* Nowy front trzyma dyscyplinę stanów pobrania bez podpowiedzi: `MultiConsultantOrdersTab` renderuje na `query.isSuccess` z komentarzem „`isSuccess`, nie `!isLoading && !isError` — w przerwie między ponowieniami", a wszystkie 10 mutacji ma `onError`. `OrdersAndContractsTab` ma jawną gałąź `isError` z `refetch`.
* Lustro DDL w `entrypoint.sh` dla 0238/0239 jest kompletne (7 × `ADD COLUMN IF NOT EXISTS`), a jednorazowe UPDATE-y siedzą pod markerem w `app_settings` z `ON CONFLICT DO NOTHING` w tym samym statemencie — czyli restart kontenera nie cofnie późniejszej decyzji admina.
* `_safe_text` w `order_excel_export` neutralizuje formuły Excela (`=`, `+`, `-`, `@`) — pomyślano o tym, o czym zwykle się nie myśli.
* Oba nowe eksporty zwracają to samo 404 dla ID nieistniejącego i dla ID cudzego klienta („Do not reveal whether an ID belongs to another client").

Po stronie długu: wyniesienie resolvera stawek do `services/contract_rates.py` razem z `RATE_SCHEDULE_LOADS` w jednym imporcie jest właściwym lekarstwem na kopiowanie funkcji między modułami `api.*`, a `REVENUE_BEARING_STATUSES` z uzasadnieniem, dlaczego `ended` ZOSTAJE w zbiorze, to rzadki przypadek komentarza, który broni przed „poprawką" psującą historię.

### `P1` Rejestr kontraktów obchodzi contract_lifecycle — druga droga do `active` bez podpisu i bez audytu, a dług właśnie wpiął `active` w przychód

`backend/app/schemas/contract.py:140`

> **Nawrót znanej klasy:** filtr statusu / swobodny zapis statusu z pominięciem strzeżonej maszyny stanów

```
    status: ContractRegisterStatus = ContractStatus.draft
```

**Dlaczego to boli.** `contract_lifecycle.activate_contract` nadal deklaruje w docstringu "The ONLY path to ``active``. Adds the audit row" i jako jedyna ścieżka egzekwuje `assert_transition`, `validate_ready_for_activation` oraz podpis kwalifikowany. Po #1225 `POST /api/contracts` i `PATCH /api/contracts/{id}` (obie za `TacPlus`) ustawiają `active` wprost — bez tych trzech bramek i bez wiersza `Activity` z przejściem. Po scaleniu z gałęzią długu skutek jest natychmiast finansowy: `contract_rates.REVENUE_BEARING_STATUSES = (active, ending, ended)` wlicza `active` do MRR, marży i „aktywnych konsultantów", więc kontrakt bez podpisu zaczyna generować przychód w raporcie zarządczym w chwili zapisu formularza. Druga połowa tej samej zmiany — `contracts.py:1536` `if "status" not in updates:` — zdejmuje koercję statusu przy jawnym wyborze, więc da się zapisać `ended` z pustą `end_date`. Taki wiersz przechodzi predykat `(Contract.end_date.is_(None)) | (Contract.end_date >= on)` w `metrics._active_contracts` i jest liczony jako aktywny BEZTERMINOWO, podczas gdy `admin_clients_overview._LIVE_CONTRACT_STATUSES = (active, ending)` go nie widzi — dwa ekrany zarządcze zaczynają podawać różne liczby dla tego samego kontraktu. `test_contract_lifecycle_invariant.py` został w tym samym PR przepisany z `test_create_contract_ignores_status_body` na `test_create_contract_honours_register_status_body`, więc regresji nie złapie żaden test.

**Naprawa.** Zostaw jawny wybór statusu w rejestrze, ale rozdziel intencję od przejścia: `→ active` kieruj do `contract_lifecycle.activate_contract` (409 z czytelnym powodem, gdy brak podpisu/pól), `→ ended` do istniejącej ścieżki terminacji, `draft`/`ending` zostaw jako zapis wprost. Niezależnie od tego przywróć guard spójności z datą dla jawnego statusu — 422, gdy `ended`/`ending` przychodzi bez `end_date` — bo `REVENUE_BEARING_STATUSES` zawiera `ended` świadomie i opiera się WYŁĄCZNIE na datach. Jeśli decyzja produktowa ma zostać w obecnym kształcie, to minimum: usuń „ONLY path" z docstringu `activate_contract`, dopisz `Activity` z `from_status`/`to_status` w `update_contract` i wyrównaj `_LIVE_CONTRACT_STATUSES` z `REVENUE_BEARING_STATUSES`.

### `P1` Stawka kosztowa: codex zapisuje cache'owaną kolumnę, dług czyta harmonogram — edycja kończy się 200 i nie robi nic

`backend/app/api/client_orders.py:1049`

> **Nawrót znanej klasy:** pieniądze liczone/zapisywane na stałych kolumnach contracts.rate_* zamiast effective_rate_fields()

```
        order.contract.rate_candidate = rate_candidate
```

**Dlaczego to boli.** Gałąź długu przestawia `_compute_monthly_margin` (client_orders.py:184 na HEAD: `eff = effective_rate_fields(contract, on or date.today())`) na harmonogramy i dociąga `RATE_SCHEDULE_LOADS` w trzech miejscach. Równolegle #1227 dokłada NOWĄ ścieżkę zapisu: `OrdersAndContractsTab` po utworzeniu draftu dosyła `dlPortalApi.updateOrder(..., { rate_candidate })`, a handler przepisuje wartość wprost do kolumny `contracts.rate_candidate`. Dla kontraktu, który ma `candidate_rate_schedule` (stawka progresywna albo aneks `rate_change` — dokładnie ta populacja, dla której powstał resolver), `_resolve_scheduled_rate` schodzi do kolumny TYLKO gdy harmonogram jest pusty, więc zapis jest ignorowany przez marżę wiersza zamówienia, kartę kontraktora, `/my-clients`, `admin_clients_overview` i całą analitykę. Użytkownik dostaje 200, pole na ekranie pokazuje nową wartość (bo czyta tę samą kolumnę), a pieniądze w systemie się nie zmieniają. Awaria cicha w najgorszą stronę: nie ma błędu, nie ma logu, jest rozjazd w raporcie.

**Naprawa.** W `update_order`, w gałęzi `if "rate_candidate" in payload.model_fields_set`, sprawdź `order.contract.candidate_rate_schedule`: gdy niepuste, albo odmów (409 „stawka jest prowadzona harmonogramem — edytuj w kontrakcie"), albo dopisz krok `ContractCandidateRate(rate=..., effective_from=business_today())` dokładnie tak, jak robi to `contracts.update_contract` w gałęzi `schedule_sent`. Zapytanie w `update_order` musi wtedy dociągnąć `selectinload(ClientOrder.contract).selectinload(Contract.candidate_rate_schedule)` — dziś ładuje sam `contract`, więc dotknięcie relacji harmonogramu w async da `MissingGreenlet`. Przy okazji `_order_has_required_activation_data` (`:174`, `order.contract.rate_candidate is not None`) też powinno pytać o stawkę efektywną, a nie o kolumnę.

### `P1` Jedna odpowiedź, dwa źródła stawki: marża z harmonogramu obok stawki kosztowej z kolumny — i codex wynosi tę kolumnę do Excela

`backend/app/api/client_orders.py:585`

> **Nawrót znanej klasy:** pieniądze liczone ze stałych kolumn contracts.rate_* zamiast effective_rate_fields()

```
                rate_candidate=c.rate_candidate,
```

**Dlaczego to boli.** W tej samej funkcji `list_contractors_with_orders` dług dołożył `*RATE_SCHEDULE_LOADS` i przestawił `latest_margin = _compute_monthly_margin(latest, c)` na harmonogramy, ale `rate_candidate` zostawił na cache'owanej kolumnie. `OrdersAndContractsTab` renderuje oba pola na tej samej karcie (`:897` `contractor.rate_candidate`, `:1290` `order.monthly_margin`), więc dla kontraktu z krokiem progresywnym, który już wszedł w życie, karta pokazuje „stawka przychodowa − stawka kosztowa ≠ marża" i nie da się rozstrzygnąć wzrokiem, która liczba jest prawdziwa. Nowy `POST /{client_id}/orders/export` (#1229) czyta DOKŁADNIE tę samą stalą kolumnę do kolumny „Stawka kosztowa" pliku .xlsx (`client_orders.py:650`, `cost_rate=by_id[order_id][0].rate_candidate`), czyli nieaktualna liczba wychodzi teraz z aplikacji do arkusza, który krąży poza nią.

**Naprawa.** W pętli `for c in contracts:` policz raz `eff = effective_rate_fields(c, today)` (schematy są już wczytane dzięki `RATE_SCHEDULE_LOADS`, więc to zero dodatkowych zapytań) i użyj `eff["rate_candidate"]` dla `rate_candidate` oraz `eff["rate_client"]` jako fallbacku w `latest_order_rate_client` zamiast surowego `c.rate_client`. Eksport `export_client_orders` reużywa `list_contractors_with_orders`, więc naprawia się sam i pozostaje spójny z ekranem.

### `P2` Redakcja finansowa długu zamienia pasek budżetu w czerwony komunikat „wyczerpany" dla TAC-a

`frontend/src/components/client-profile/orders/OrderGroupCard.tsx:58`

> **Nawrót znanej klasy:** awaria/brak uprawnień renderowany jako wartość (403 czyta się jak utrata danych)

```
  const total = group.budget_amount ?? 0;
```

**Dlaczego to boli.** Gałąź długu zaczyna redagować kwoty grupy dla ról bez VIEW_FINANCE (`client_order_groups.py:453` na HEAD: `budget_amount=group.budget_amount if with_finance else None`, tak samo `budget_used`, `budget_remaining`, `invoiced`, `unsettled`). `_can_see_finance` świadomie odcina TAC-a („TAC zostaje przy redakcji" — docstring), a TAC tę zakładkę WIDZI (`OrderGroupReader`). Wtedy `total = 0`, `remaining = 0`, więc `depleted = remaining <= 0` jest prawdą i pasek renderuje się klasą `bg-destructive` pod podpisem „Kwota — · wykorzystano — · pozostało —". Brak uprawnień czyta się jak alarm o wyczerpanym budżecie zamówienia — czyli dokładnie odwrotność tego, co repo wymusza gdzie indziej („stawki renderują się jako »—«, znikająca kolumna czytałaby się jak brak danych"). Gałąź długu nie tknęła tego pliku, a codex go przepisał, nie wiedząc, że pole zaraz zacznie przychodzić jako `null`.

**Naprawa.** W `BudgetBar` wyjdź wcześnie: `if (group.budget_amount == null) return null;` (albo wyrenderuj samą etykietę „—" bez paska i bez stanu `depleted`), a decyzję o pokazaniu paska przenieś do wołającego w `OrderGroupCard`. Warunek musi patrzeć na `null`, nie na `0` — zamówienie z realnym budżetem 0 to inny stan niż brak uprawnień.

### `P2` Nowa granica doby na zegarze kontenera (UTC), gdy ta sama fala wprowadziła `business_today()`

`backend/app/services/order_group_lifecycle.py:50`

> **Nawrót znanej klasy:** date.today() na zegarze kontenera (UTC) tam, gdzie chodzi o dobę warszawską

```
    boundary_day = today or date.today()
```

**Dlaczego to boli.** Gałąź długu dodała `app/core/scheduling.business_today()` z uzasadnieniem, że kontener chodzi w UTC i między północą warszawską a UTC (1 h zimą, 2 h latem) `date.today()` zwraca WCZORAJ, i wpięła je w `contract_alerts._promote_statuses`, `_contracts_at_threshold`, `_compliance_documents_expiring`, `_equipment_due_for_return`, `_client_orders_ending`. Codex w tym samym czasie dokłada dwie nowe decyzje datowane zegarem kontenera: `materialize_scheduled_order_groups` (promocja `scheduled → active` + domykanie poprzednika, wołana z `dl_portal_expiry_scanner._promote_statuses` ORAZ z `list_order_groups` przy każdym odczycie) oraz `client_order_groups.py:312` `_initial_group_status`. Skutek: w oknie 00:00-02:00 czasu warszawskiego zamówienie startujące „dziś" jest jeszcze `scheduled` z liniami w `draft`, a bliźniaczy cron kontraktów już przeszedł na nowy dzień — dwa mechanizmy w module zamówień datują się różnymi dobami, a nowo zakładana grupa ze startem „dziś" potrafi dostać status `scheduled` zamiast `active`.

**Naprawa.** `from app.core.scheduling import business_today` i podmień oba wystąpienia. Sygnatura `materialize_scheduled_order_groups(db, *, client_id=None, today=None)` już to przyjmuje, więc wołający z `dl_portal_expiry_scanner` wymaga zmiany jednej linii (`today = business_today()` zamiast `date.today()`), a `list_order_groups` — żadnej.

### `P2` Zapis stawki kosztowej z formularza zamówienia nie przelicza `contracts.margin`, po której filtruje rejestr

`backend/app/api/contracts.py:389`

> **Nawrót znanej klasy:** pieniądze liczone ze stałych kolumn zamiast z jednego resolvera

```
        query = query.where(Contract.margin >= margin_min)
```

**Dlaczego to boli.** `Contract.margin` jest kolumną utrwaloną, a nie wyrażeniem — `PATCH /api/contracts/{id}` kończy się `contract.margin = contract.calculate_margin()` właśnie po to, żeby ten filtr zgadzał się z danymi. Nowa ścieżka zapisu z `client_orders.py:1049` ustawia `order.contract.rate_candidate` i commituje BEZ przeliczenia. Filtr „marża od" w rejestrze kontraktów zaczyna więc kwalifikować kontrakty po nieistniejącej już wartości: kontrakt po podwyżce stawki kosztowej zostaje w wynikach filtra, do którego już nie należy, albo z niego wypada mimo że należy. Ta sama kolumna wychodzi też w `ContractDetailResponse` (`:221`), ale tam jest nadpisywana przez `data.update(_effective_rate_fields(...))` na `:259`, więc objaw widać wyłącznie w filtrze — czyli w miejscu, gdzie nikt nie porówna go z drugą liczbą.

**Naprawa.** W `update_order`, tuż po `order.contract.rate_candidate = rate_candidate`, dopisz `order.contract.margin = order.contract.calculate_margin()`. Docelowo (razem z F1) ta ścieżka i tak powinna przechodzić przez tę samą logikę co `contracts.update_contract`, zamiast dublować dwa jej kroki i pomijać trzeci.

### `P3` Nowy kod gałęzi długu na powierzchniach pieniężnych też sięga po `date.today()` zamiast `business_today()`

`backend/app/api/client_orders.py:184`

> **Nawrót znanej klasy:** date.today() na zegarze kontenera (UTC) tam, gdzie chodzi o dobę warszawską

```
    eff = effective_rate_fields(contract, on or date.today())
```

**Dlaczego to boli.** Ta sama fala napraw wprowadziła `business_today()` i uzasadniła to wprost („objaw jest cichy: liczba jest poprawna, tylko opisuje inny dzień"), ale nowy kod finansowy tej fali go nie używa: poza tą linią także `admin_clients_overview.clients_overview` (`today = date.today()`), `my_clients.client_dashboard` (`today = date.today()`) i cała rodzina zapytań w `analytics/metrics.py`. Konsekwencja jest mała, ale realna: krok harmonogramu z `effective_from` na 1. dnia miesiąca zaczyna obowiązywać w marży o 02:00 czasu warszawskiego, więc raport otwarty rano pierwszego dnia miesiąca i ten sam raport otwarty w nocy podają różne kwoty. Moment scalania jest ostatnim, w którym da się to zamknąć jednym ruchem — potem `date.today()` w tych funkcjach będzie wyglądał na świadomą decyzję.

**Naprawa.** Ustal jedno źródło „dziś" dla pieniędzy i użyj `business_today()` jako domyślnego `on` w `_compute_monthly_margin`, `admin_clients_overview.clients_overview`, `my_clients.client_dashboard` i `order_group_lifecycle`. `metrics.py` zostaw na później — tam `on` bywa datą historyczną z `Period` i zmiana wymaga osobnego przeglądu granic okresów.

---
