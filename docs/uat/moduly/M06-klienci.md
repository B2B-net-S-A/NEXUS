# M06 — Klienci

| Pole | Wartość |
|---|---|
| Tryb | **R** |
| Persony | delivery_lead PRZYPISANY do D1 (nie do D2), delivery_lead NIEprzypisany, tac, head_of_recruitment, finance, talent_community_manager (podgląd); admin |
| Zależności | Fala 0 (D1 z DL, D2, D11, D12); najlepiej po P2 (wtedy D1 ma konsultanta i kontrakt) |
| Czas | ~3 h |
| Głębokość | pełna (kwoty per portfel — najczęstsze źródło błędów RBAC) |
| Akcje AI | nie |

## Zakres

- `/clients` — lista + zakładka „Nieaktywni klienci” (z przyciskiem „Czyszczenie listy” — **STOP**).
- `/clients/[id]` — 8 zakładek: **Profil · Zasady współpracy · Projekty · Zamówienia · Delivery Lead · Kontakty klienta · Umowy · Analityka**; `?tab=` w URL (klucze: `profil`, `zasady`, `projekty`, `zamowienia`, `zespol`, `kontakty`, `umowy-ramowe`, `analityka`).
- `/my-clients` — Panel klientów (DL), `/my-clients/[id]/dashboard` przez zakładkę Analityka.
- `/my-relationships` — Moje relacje.
- `/dashboard/delivery-lead` — Panel Managera (patrz M00 S14).
- `/settings/clients-overview` — przegląd klientów (admin/finance).
- Zamówienia (zakładka) → osobna karta M07. Umowy → M08.

## Przed startem

ID D1, D2, ID DL przypisanego do D1, ID DL nieprzypisanego. Jeden PRAWDZIWY klient z ≥ 3
aktywnymi konsultantami (tylko ID) — do S10–S13 na prawdziwych liczbach.

## NIE KLIKAJ

„Czyszczenie listy” (jednorazowe!), „Usuń klienta”, „Scal klientów”, „Edytuj firmę” → Zapisz,
„Dodaj kontakt” → Zapisz, „Wyślij” w Kontaktach, „Przypisz DL” (P2 robi to w Fali 0/2).

## Scenariusze — lista

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | delivery_lead (D1) | `/clients` | lista; filtr „Tylko moi klienci” = filtr, nie granica (widzi też innych); wyszukiwanie „QA-E2E” → D1, D2 | P1 |
| S02 | delivery_lead | zakładka „Nieaktywni klienci” | lista; przycisk „Czyszczenie listy” widoczny TYLKO adminowi; **nie klikaj** | P1 |
| S03 | recruiter | `/clients` ręcznie | odmowa (`/403` lub komunikat) — sekcja delivery | P1 |
| S04 | talent_community_manager | `/clients` | odczyt globalny; brak przycisków mutacji (Dodaj, Edytuj) | P2 |
| S05 | admin | `/settings/clients-overview` | przegląd z kwotami; finance też widzi; HoR — odmowa | P1 |

## Scenariusze — profil D1 (DL przypisany)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S06 | delivery_lead (D1) | `/clients/{{D1}}` → każda z 8 zakładek | wszystkie ładują się; `?tab=` zmienia się w URL; F5 odtwarza zakładkę; klik powiadomienia `/clients/{{D1}}?tab=zamowienia` z INNEJ zakładki tego samego klienta przełącza zakładkę (miękka nawigacja) | P1 |
| S07 | delivery_lead (D1) | Profil → sekcja „Konsultanci” (tabela) | kolumny: Konsultant (nazwisko / tag CC / rekrutacja) · Start date · Stawka kosztowa · Stawka przychodowa · Marża; po P2 ≥ 1 wiersz; kwoty WIDOCZNE (własny portfel); marża = przychodowa − kosztowa | P1 |
| S08 | delivery_lead (D1) | Profil → kafle KPI (`StatsCard`) | „Aktywne MRR” = suma kolumny „Marża” z tabeli (policz ręcznie); kafle jednoliniowe; tooltip z opisem | P1 |
| S09 | delivery_lead (D1) | Profil → podzakładka „Archiwum konsultantów” | te same 3 kolumny kwot + End date; stawki liczone na dzień zakończenia | P2 |
| S10 | delivery_lead (D1) | Analityka | kafle finansowe RENDERUJĄ się (przychód lifetime, aktywny, marża/mc); liczby zgodne z S07/S08 | P1 |
| S11 | delivery_lead (D1) | Zasady współpracy | karta D11 (SLA 5 dni, min 3, limit 2 CV); przycisk edycji widoczny; wersja i historia | P2 |
| S12 | delivery_lead (D1) | Projekty | rekrutacja D3 z etapami; licznik kandydatów = M03 S12 | P1 |
| S13 | delivery_lead (D1) | Delivery Lead (zespół) | DL persony na liście; TAC (jeśli przypisany) | P2 |
| S14 | delivery_lead (D1) | Kontakty klienta | lista lub pusty stan; **nie dodawaj** | P3 |
| S15 | delivery_lead (D1) | Umowy (ramowe) | lista umów ramowych/warunków; pusty stan PL | P2 |

## Scenariusze — profil D1 oczami INNYCH ról (redakcja kwot)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S16 | delivery_lead NIEprzypisany | `/clients/{{D1}}` | 403 z powodem („klient poza portfelem”) — NIE pusta strona, NIE profil bez kwot | P1 |
| S17 | head_of_recruitment | Profil → Konsultanci + kafle + Analityka | tabela z nazwiskami, ale WSZYSTKIE 3 kolumny kwot „—”; kafle finansowe „—”/ukryte; Analityka BEZ kafli finansowych. Redakcja całościowa: jeśli kafel ma liczbę, a kolumna „—” → P1 | P1 |
| S18 | tac (w zespole D1) | jw. | jak HoR: nazwiska tak, kwoty „—” | P1 |
| S19 | talent_community_manager | jw. | jak HoR | P1 |
| S20 | finance | jw. | kwoty WIDOCZNE (pełny odczyt biznesowy) | P1 |
| S21 | admin | jw. | kwoty widoczne | P2 |
| S22 | delivery_lead (D1) | `/clients/{{D2}}` (nieprzypisany do D2) | 403 z powodem | P1 |
| S23 | delivery_lead z ROLĄ HoR jednocześnie (jeśli istnieje takie konto — inaczej SKIP) | `/clients/{{D1}}` | kwoty „—” (hybryda HoR+DL = nadzór nieoskopowany, bez finansów) | P1 |

## Scenariusze — prawdziwy klient (tylko odczyt, tylko ID w raporcie)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S24 | admin | Profil → Konsultanci na kliencie z ≥ 3 aktywnymi | stawki z HARMONOGRAMÓW (nie z kolumn kontraktu): jeśli konsultant ma zaplanowaną podwyżkę od przyszłego miesiąca — tabela pokazuje OBECNĄ stawkę; brak 500 `MissingGreenlet` | P1 |
| S25 | admin | Konsultanci: kolumna „rekrutacja” | pusta komórka, gdy brak powiązanej rekrutacji (nie tekst „brak powiązanej rekrutacji”); znany stan: `job_id` często pusty na prodzie — zapisz odsetek pustych | P3 |
| S26 | admin | Archiwum konsultantów | wiersze z End date; stawka na dzień zakończenia (kontrakt z późniejszą podwyżką NIE pokazuje jej w archiwum) | P2 |
| S27 | admin | Analityka → okresy (jeśli są) | zmiana okresu zmienia liczby; brak `NaN` | P2 |

## Scenariusze — Panel klientów, relacje

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S28 | delivery_lead (D1) | `/my-clients` | tylko klienci portfela (D1, nie D2); karta → link do Analityki | P1 |
| S29 | head_of_recruitment | `/my-clients` | wszyscy klienci (gałąź organizacyjna); BEZ kwot | P1 |
| S30 | finance | `/my-clients` | wszyscy klienci; kwoty w API (`total_revenue_all_time`) — UI ich dziś nie pokazuje; zapisz jako obserwację | P3 |
| S31 | delivery_lead | `/my-relationships` | relacje persony; brak 500 | P2 |
| S32 | admin | `/clients/{{D1}}?tab=orders` i `?tab=framework-contracts` (NIEISTNIEJĄCE klucze) | ląduje na Profilu (fallback), nie 500; zapisz — to znany błąd sprzed 10.09 w linkach alertów | P3 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token');
const call=async(p,imp)=>{const h={Authorization:`Bearer ${tok}`}; if(imp)h['X-Impersonate-User-Id']=String(imp);
  const r=await fetch('https://api.nexus.dynaminds.pl'+p,{headers:h}); return [r.status, await r.json().catch(()=>null)];};
// DL przypisany vs HoR — porównaj obecność kwot
const [s1,dl]=await call('/api/clients/{{D1}}/profile', {{ID_DL_D1}});
const [s2,hor]=await call('/api/clients/{{D1}}/profile', {{ID_HOR}});
console.log(s1, dl?.consultants?.[0]?.rate_cost, dl?.active_mrr);   // liczby
console.log(s2, hor?.consultants?.[0]?.rate_cost, hor?.active_mrr); // null, null
const [s3]=await call('/api/clients/{{D1}}/profile', {{ID_DL_OBCY}}); console.log('DL obcy', s3); // 403
```

## Znane pułapki

- `can_read_client_finance` jest JEDNYM miejscem reguły dla profilu, `/my-clients` i Analityki.
  Rozjazd między zakładkami tego samego klienta = P1 i wskazuje na kopię reguły.
- `AnalyticsTab` ma DRUGĄ bramkę po stronie frontu (`canViewClientFinance` z `data_scope`).
  Jeśli backend zwraca kwoty, a Analityka ich nie pokazuje — P1 (bramka front).
- Kafel `components/StatsCard` ≠ `components/ds/StatCard` — inny komponent, inne miejsca.

## Do raportu

Tabela „rola → kwoty widoczne (tak/nie) na: Konsultanci / kafle / Archiwum / Analityka / my-clients”
dla 7 ról; wynik ręcznego przeliczenia S08; zrzuty S07 i S17 obok siebie.
