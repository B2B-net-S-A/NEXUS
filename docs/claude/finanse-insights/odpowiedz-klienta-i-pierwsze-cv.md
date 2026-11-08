# Odpowiedź klienta w 7 dni i pierwsze CV po otwarciu
<!-- indeks: audyt 2 z 08.11.2026, kafelek „Odpowiedź klienta” dla HoR i DL, `client_response_metrics.py`, dni robocze kalendarza firmy, rekrutacje masowe od 30 CV, bez importu Traffita, pas w Insights → Zespół, baseline w pamięci projektu, cel 40% -->

Audyt 2 z 08.11.2026: na ścieżce 66 zatrudnionych od karty do CV mija ok. 1 dzień,
a od CV do zatrudnienia 22,7 dnia. Dwa kafle `_unavailable_kpi` na pulpitach HoR
i DL zastąpiły liczby, które pokazują też stronę klienta. Kod:
`backend/app/services/client_response_metrics.py`. Testy definicji:
`tests/test_client_response_metrics.py`, zapytania: `..._db.py`.

**Obie miary liczą dni robocze** kalendarza firmy (`WorkCalendar`: Pon–Pt bez
świąt i dni wolnych firmy), przedział `(start, koniec]`, ta sama data to 0.

## Odpowiedź klienta w 7 dni

- Odpowiedź = po pierwszym `cv_sent` pary pierwszy `client_interview`,
  `acceptance`, `hired` albo `rejected` z `ended_by='client'`. Odrzucenie przez
  rekrutera lub DL i pusty `ended_by` to nie odpowiedź klienta.
- Mianownik: CV, którym minęło 7 dni roboczych, z 4 tygodni, nie sprzed 12.10.2026.
  Świeże wysyłki zaniżałyby wynik.
- Rekrutacja masowa (30 i więcej CV od początku okna, także niedojrzałych) wypada
  z procentu, ale jej CV zostają w „CV w toku”. Kafelek podaje, ile CV pominięto.
- „Brak odpowiedzi” znaczy brak odpowiedzi zapisanej w NEXUSIE.

Tabela per klient: „CV w toku” to kolumna „Czekają na decyzję klienta” z „W drodze”
(`_pairs_now`, ta sama reguła co Tablica), „najstarsze bez odpowiedzi” w dniach
roboczych. Najpierw najniższy procent, klienci poniżej 5 CV na końcu.

## Pierwsze CV po otwarciu

Start: `opened_at`, a bez niego `created_at`. Odpadają rekrutacje z importu
Traffita (ich `created_at` to chwila importu) i wysyłki sprzed startu. Okno:
8 tygodni, nie sprzed 12.10.2026. Procent w 5 dniach roboczych liczy tylko
rekrutacje, którym tyle minęło.

Pas „Od otwarcia rekrutacji do pierwszego CV u klienta” w Insights → Zespół
(`TeamFirstCvStrip`, `GET /api/insights/recruitment/first-cv`) pokazuje medianę
pierwszej ruszonej karty, „Zweryfikowanego”, CV i procent, z linią tygodni bez
trwającego tygodnia. Pierwsza dodana karta nic nie mówi: ręczna rekrutacja też
dostaje karty systemu w dniu otwarcia.

## Dostęp

`GET /api/dashboard/v2/client-response`: admin, Head of Recruitment, Delivery Lead;
zakres z `resolve_scope`. Trasa bez bramki sekcji, bo DL nie zawsze ma Insights,
a HoR Delivery. Tylko liczby i nazwy klientów, bez kwot.

Baseline sprzed porcji dnia (19,3% przy 7 dniach roboczych, 14,0% kalendarzowych)
i cel 40% w 6 tygodni są w pamięci projektu.
