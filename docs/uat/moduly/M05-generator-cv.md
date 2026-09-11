# M05 — Generator CV

| Pole | Wartość |
|---|---|
| Tryb | **R + zapis techniczny** — generacja CV tworzy wiersz `cv_generated_documents` dla kandydata TESTOWEGO; to jedyny dozwolony zapis w Fali 1 (bo generator jest w całości „akcją”). Zawsze kontem admina, NIE w podglądzie. |
| Persony | recruiter, finance (podgląd — tylko lista i podgląd cudzych CV); admin (generacje) |
| Zależności | Fala 0 (D5–D9, D3+D10, D12 reguła CV, `zgoda-rodo.png`), M04 |
| Czas | ~3 h (generacja 2–3 min każda) |
| Głębokość | pełna — dokument idzie do klienta |
| Akcje AI | **TAK, najdroższe w produkcie.** Limit na kartę: 8 generacji (z 10 na UAT). Zapisz zużycie przed/po. Nie równolegle z M02/M04. |

## Zakres

- `/cv-generator` — standalone: tryb „z bazy” (kandydat + rekrutacja) i „upload” (plik + klient),
  3 tryby treści (`basic` / `polished` / `tailored`), kroki (kandydat → klient/rekrutacja →
  Champion → generuj), lista wygenerowanych, wersje, zatwierdzanie, DOCX/HTML, link interaktywny.
- Przepływ produkcyjny: `CV_GENERATION_PIPELINE` domyślnie `legacy` (sprzed przebudowy).
- Reguły CV klienta: `/settings/cv-rules` (odczyt tu; edycja = stop-lista).
- `/cv/[token]`, `/cv/i/[token]` — publiczne (M12).

## Przed startem

- `GET /api/settings/ai` → `cv_generator`, `cv_requirement_map`, `cv_rule_lint`: `used`/`limit`.
- Sprawdź `CV_GENERATION_PIPELINE` przez zachowanie (S05): legacy = brak pogrubień w `polished`.
- Reguła CV D1 (D12) zatwierdzona: `GET /api/settings/cv-rules` → wiersz D1 `confirmed_at != null`.

## NIE KLIKAJ

„Udostępnij link” + przekazanie go komukolwiek (link możesz UTWORZYĆ i otworzyć sam — M12),
„Usuń CV” prawdziwego autora, „Zapisz i zatwierdź” w Regułach CV, „Lint instrukcji”/„CV próbne”
w regułach (kwota; to admin robi w M11), generacje dla PRAWDZIWYCH kandydatów.

## Scenariusze — generacja (admin, kandydaci testowi)

| ID | Kroki | Oczekiwane | Prio |
|---|---|---|---|
| S01 | `/cv-generator` → tryb z bazy → kandydat D5 → rekrutacja D3 | picker rekrutacji pokazuje rekrutacje D5 (po P1) lub wszystkie otwarte; klient D1 wyprowadzony; reguła CV D1 widoczna („język PL, nazwa pliku …”) | P1 |
| S02 | tryb treści: kafelki | 3 kafelki; jeśli reguła D1 ma `content_mode_locked` — kafelki wyłączone z komunikatem; bez blokady — domyślny zaznaczony | P2 |
| S03 | generuj `tailored` dla D5/D3 (generacja 1) | zadanie w kolejce → postęp → dokument po 2–3 min; w liście „Wygenerowane” nowy wiersz z `client_rule_version` | P1 |
| S04 | otwórz wynik: podgląd | nagłówek: rola z tytułu D3 („Senior Backend Developer”), lata doświadczenia = suma z CV (≈ 2015–2026 → ok. 10–11 lat, nie mniej); 3 role; daty `MM.RRRR`; skille MUST pogrubione (tryb tailored); brak zmyślonych obowiązków (porównaj z CV D5) | P1 |
| S05 | generuj `polished` dla D6/D4 (generacja 2) | BRAK pogrubień (legacy_v7); długie punkty skrócone z „…”; daty `03.2020 – 06.2023` zachowane (`apply_date_format`) | P1 |
| S06 | generuj `basic` dla D8 (CV bez miesięcy) (generacja 3) | nagłówek lat z samych lat (bezpiecznik); brak „Invalid Date”; ostrzeżenie, jeśli lat nie da się wyliczyć | P2 |
| S07 | generuj dla D9 (bez CV) | czytelna odmowa PRZED naliczeniem kwoty: „kandydat nie ma CV” (422); zużycie `cv_generator` bez zmian | P1 |
| S08 | tryb upload: `cv-05-skan.pdf` (sam obraz) + klient D1 + checkbox „CV poza zleceniem” odznaczony → generuj (generacja 4) | strona-obraz pominięta, nie blokuje; jeśli CAŁE CV to obraz → odmowa „brak tekstu” przed kwotą; wynik zapisany w raporcie | P2 |
| S09 | tryb upload: `cv-03-maria-fikcyjna.pdf` (EN) → język z reguły D1 = PL (generacja 5) | dokument po POLSKU; ostrzeżenie o tłumaczeniu, jeśli generator je emituje | P2 |
| S10 | tryb upload BEZ klienta, checkbox „CV poza zleceniem” odznaczony → generuj | odmowa: klient wymagany albo jawny checkbox; brak kwoty | P1 |
| S11 | wersja anonimowa (blind) dla D5/D3 (generacja 6) | brak imienia/nazwiska/kontaktu/nazw pracodawców w dokumencie i w JSON podglądu; branża „IT” gdy brak | P0 |
| S12 | klient wymagający zrzutu zgody RODO (jeśli D1 ma `requires_rodo_consent_block` — ustaw w Fali 0 w D12, inaczej SKIP): generuj D5 BEZ zrzutu | 422 „wymagany zrzut zgody” PRZED kwotą | P1 |
| S13 | jw. ze zrzutem `zgoda-rodo.png` (generacja 7) | obraz na końcu dokumentu, pod treścią, nad klauzulą RODO; render nie nakłada się | P1 |
| S14 | pobierz DOCX z S03 | nazwa pliku wg reguły D1 (`CV_Anna_Testowa.docx`); otwiera się; marginesy papieru firmowego; brak pustych stron | P1 |
| S15 | pobierz HTML z S03 (`/generated/{id}/html`) | jeden plik, offline; przełącznik classic/interaktywny; kafelki must/nice z cytatami będącymi podciągami CV; druk = czyste CV | P2 |
| S16 | „Zatwierdź wygenerowane CV” dla S03 | zatwierdzone; zapis `status="unverified"`, `method="evidence_enforcement_off"` (bramka OFF) — NIE „verified”; brak 409 | P1 |
| S17 | edytor: zmień jedno zdanie w S05 → zapisz jako wersję | nowa wersja; historia wersji; poprzednia dostępna | P2 |
| S18 | lista „Wygenerowane”: filtr, wyszukiwanie, sortowanie | testowe wiersze widoczne; kolumna autora = rola+ID (nie tylko e-mail) | P2 |
| S19 | usuń CV z S06 (własne, testowe) | usunięte; lista odświeżona; plik niedostępny | P2 |

## Scenariusze — dostęp (podgląd)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S20 | recruiter (NIE autor, w zespole D3) | lista i podgląd CV z S03 | widzi (odczyt rekrutacji D3); pobranie DOCX działa | P1 |
| S21 | recruiter spoza zespołu D3 i nie autor | S03 | brak dostępu — czytelna odmowa, nie pusty ekran; lista `/generated` bez tego wiersza | P1 |
| S22 | finance | lista + podgląd S03 + „Zatwierdź” | odczyt i zatwierdzenie dostępne (Finanse ma odczyt rekrutacji); usunięcie NIE (autor albo admin) | P1 |
| S23 | recruiter | `/cv-generator` → generuj (formularz do momentu „Generuj”, potem ANULUJ) | każdy z `CandidateWriteAccess` może generować (decyzja 10.09) — brak wymagania członkostwa w zespole; 403 w podglądzie = oczekiwane | P1 |

## Scenariusze — reguły CV (odczyt)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S24 | admin | `/settings/cv-rules` | lista `{rules, unassigned_templates}`: D1 z regułą zatwierdzoną; klienci z szablonem Championa bez reguły widoczni jako „bez reguły” | P1 |
| S25 | admin | `/settings/cv-rules?client={{D1}}` (deep link) | otwiera edytor D1; zakładka „Karta klienta” (`&tab=playbook`) pokazuje D11 | P2 |
| S26 | delivery_lead | `/settings/cv-rules` | dostępne (DeliveryLeadPlus); przycisk „Zapisz i zatwierdź” widoczny | P2 |
| S27 | tac | `/settings/cv-rules` | odmowa (TAC nie prowadzi reguł) | P1 |
| S28 | admin | edytor D1 → „Sygnał zwrotny” | liczy pominięte instrukcje z ostrzeżeń wygenerowanych CV (po S03 ≥ 1 CV); brak 500 | P3 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const list = await fetch('https://api.nexus.dynaminds.pl/api/cv-generator/generated?limit=20',{headers:h}).then(r=>r.json());
console.table((list.items??list).map(d=>({id:d.id,cand:d.candidate_id,mode:d.content_mode,rule_v:d.client_rule_version,approved:!!d.approved_at})));
```

## Znane pułapki

- Generacja żyje w kolejce w procesie web: **deploy w trakcie = zadanie przerwane**; po restarcie
  wznawia się ze snapshotu (`job_snapshot`). Jeśli SHA zmienił się w trakcie — poczekaj 3 min, sprawdź listę.
- `CV_B2B_MAX_RETRIES=3`, budżet 300 s — „upload = Błąd” po 5 min to trap truncation/timeout,
  zgłoś z ID zadania i czasem.
- Legacy: słownik klienta podmienia tekst we WSZYSTKICH polach; brak branży w blind = „IT”.
  To zachowania zamierzone.
- Dla ról bez `VIEW_FINANCE` stawki w CV NIGDY nie występują — jeśli w dokumencie jest kwota, P0.

## Do raportu

ID 7 wygenerowanych dokumentów, czasy generacji, zużycie AI przed/po, zrzuty pierwszej strony
S04/S05/S11, wynik S16 (`status`, `method` z odpowiedzi API), lista pominiętych.
