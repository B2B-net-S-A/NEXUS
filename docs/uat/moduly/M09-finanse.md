# M09 — Finanse

| Pole | Wartość |
|---|---|
| Tryb | **R** (import MD/kosztowy → P3) |
| Persony | finance, admin; do negatywnych: delivery_lead, head_of_recruitment, recruiter (podgląd) |
| Zależności | Fala 0; P3 dla danych importu |
| Czas | ~2 h |
| Głębokość | pełna, jeśli Finanse są w pilotażu; inaczej przegląd |
| Akcje AI | nie |

## Zakres

- `/finance` — 3 widoki (`ViewMode`): **Wyniki miesięczne** (`results`), **Archiwum** (`archive`),
  **Import zużycia MD** (`md`; tylko z `canWrite` = capability `manage_finance`); parametr `?view=`.
- Korekty finansowe (`financial_adjustments`), faktury (`invoices`), kursy FX (`fx`), benchmarki stawek (`/settings/rate-benchmarks`).
- Redakcja kwot na WSZYSTKICH powierzchniach spoza `/finance` — to karta A/B; tu tylko `/finance` i jego API.
- `/settings/chats` (admin, finance) — czaty audytowe.

## NIE KLIKAJ

„Importuj”, „Zapisz wyniki miesiąca”, „Zatwierdź”, „Dodaj korektę” → Zapisz, „Przelicz kursy”,
„Przypisz” w wierszach `Wymaga przypisania`.

## Scenariusze

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | finance | `/finance` | widok „Wyniki miesięczne”; przełącznik trybów z `aria-label="Tryb modułu Finanse"`; przycisk „Import zużycia MD” widoczny TYLKO z `manage_finance` | P1 |
| S02 | finance | Wyniki miesięczne: wybór miesiąca (bieżący, poprzedni, sprzed roku) | tabela per klient/konsultant; sumy w stopce = suma wierszy (policz 3 kolumny); brak `NaN`; kwoty z walutą | P1 |
| S03 | finance | miesiąc bieżący (niepełny) | oznaczenie „trwa”/częściowy; bez porównania YTD z pełnym miesiącem | P2 |
| S04 | finance | Archiwum | miesiące zamknięte; wejście w miesiąc → dane tylko do odczytu; brak przycisków zapisu | P2 |
| S05 | finance | `/finance?view=md` | historia importów MD i kosztowych; kolumny: miesiąc, plik, wiersze OK / „Brak aktywnego zamówienia” / „Wymaga przypisania”; `cost_status` osobno od `status` | P1 |
| S06 | finance | wiersz `Wymaga przypisania` (jeśli jest) | lista kandydackich zamówień do wyboru; system NIE zgadł; **nie przypisuj** | P1 |
| S07 | finance | F5 na `?view=md` i `?view=archive` | widok odtworzony z URL | P2 |
| S08 | admin | `/finance` | pełny dostęp jak finance | P2 |
| S09 | delivery_lead | `/finance` ręcznie | odmowa (`/403`); menu bez „Finanse” | P1 |
| S10 | head_of_recruitment / recruiter | `/finance` ręcznie | odmowa | P1 |
| S11 | finance | korekty finansowe (jeśli w UI) | lista z autorem, datą, powodem; formularz z walidacją PL; **Anuluj** | P2 |
| S12 | finance | faktury (jeśli w UI) | lista; filtr klienta; kwoty; brak 500 | P2 |
| S13 | finance | `/settings/rate-benchmarks` | benchmarki stawek; widoczne dla finance; recruiter → odmowa | P2 |
| S14 | finance | `/settings/chats` | dostępne (admin, finance); recruiter → odmowa | P2 |
| S15 | finance | kursy FX: kontrakt w EUR (jeśli istnieje; tylko ID) w Wynikach | przewalutowanie na PLN; brak kursu → „—”/ostrzeżenie, nie 0 | P2 |
| S16 | finance | eksport Wyników (jeśli przycisk) | plik; sumy zgodne z ekranem | P2 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token');
const call=async(p,imp)=>{const h={Authorization:`Bearer ${tok}`}; if(imp)h['X-Impersonate-User-Id']=String(imp);
  const r=await fetch('https://api.nexus.dynaminds.pl'+p,{headers:h}); return r.status;};
console.log('finance results (fin):', await call('/api/finance/monthly-results?month=2026-08', {{ID_FIN}}));  // 200
console.log('finance results (DL):',  await call('/api/finance/monthly-results?month=2026-08', {{ID_DL}}));   // 403
console.log('fx:', await call('/api/fx/rates', {{ID_FIN}}));                                                   // 200
```
(Ścieżki potwierdź w zakładce sieci; zapisz prawdziwe.)

## Znane pułapki

- Ewidencja kontraktów jest MŁODSZA niż firma (17 kontraktów w 01.2024 vs 452 w 08.2026) —
  porównania międzyroczne pieniędzy w Insights są ostrzegane; w `/finance` nie ma YoY, ale
  Archiwum sprzed 2025 może być puste — to nie błąd.
- `_can_see_finance` w module zamówień i `can_read_client_finance` w profilu klienta to
  wąskie powierzchnie, nie capability — DL widzi kwoty tam, ale NIE w `/finance`.

## Do raportu

Zrzut Wyników z sumami i ręczne przeliczenie 3 kolumn; wynik S09/S10; lista przycisków dostępnych finance vs admin.
