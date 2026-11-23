# Dzwonienie: po co oddzwaniamy — decyzje Artura 23.11.2026
<!-- indeks: powód oddzwonienia, Po co oddzwaniamy, callback_reason, calling_reasons.py, notatka ostatniego telefonu, komentarz z Excela, Przypomnienia, Mój dzień, Oddzwaniasz bo, opcjonalny nie blokuje -->

Zgłoszenie osób dzwoniących (23.11.2026): w przypomnieniu o oddzwonieniu ma być
wpisana przez nas informacja, dlaczego dzwonimy. Na kopii produkcji z 23.11 notatkę
miało 12 z 41 wyników „Oddzwonić” z kolejki, a Przypomnienia i kolejka nie pokazywały
jej wcale (Marcel: 116 zaległych przypomnień bez treści). Makiety: prywatny artefakt
https://claude.ai/artifact/Gxjj6erDvtVBijP4S73g6p (punkt 4). Artur wybrał wariant
rekomendowany: powód opcjonalny, ale na wierzchu.

Kod: `backend/app/services/sales/calling_reasons.py`, pole `callback_reason` pozycji
kolejki (`calling.QueueItem`, `QueueItemOut`), front `CallCard.tsx`
(„Po co oddzwaniamy?”, `CallbackReasonNote`), `CallRemindersView.tsx`,
`CallQueueView.tsx`, `MyDayReminders.tsx`. Bez migracji.

## Zasady

- **Powód to notatka ostatniego telefonu rekordu**, gdy ten telefon ma wynik
  „Oddzwonić” albo „Oferta ogólna wysłana” i niepustą notatkę. Starszego powodu nie
  pokazujemy: po kolejnym telefonie bez notatki mógł już nie obowiązywać. Bez nowej
  kolumny, bo notatka i tak leży w dzienniku (`external_source = call_queue`).
- **Rekord z Excela bez telefonu w dzienniku** bierze komentarz po rozmowie z notatki
  rekordu (pierwszy fragment po „Z Excela: ”, przed „Uwagami”). Notatka z innym
  początkiem (np. „Typ usługi: …”) nie jest powodem.
- **Pole jest opcjonalne** („moduł podpowiada, nie blokuje”). Po „Oddzwonić…” karta
  pokazuje „Po co oddzwaniamy?” z kursorem zamiast ogólnej notatki; zapis bez powodu
  przechodzi, a przypomnienie mówi „Bez powodu: dopisz przy rozmowie”.
- Powód widać w Przypomnieniach (z autorem i dniem albo „Komentarz z Excela”),
  w oddzwonieniach kolejki (przed numerem rozmowy), w „Moim dniu” i na górze karty
  („Oddzwaniasz, bo: …”). Tabela go nie liczy, żeby nie dokładać zapytania na 200
  wierszy.

Testy: `backend/tests/test_sales_calling_reasons.py`, w
`frontend/src/components/sales/__tests__/sales-calling.test.tsx` „po co oddzwaniamy”.
