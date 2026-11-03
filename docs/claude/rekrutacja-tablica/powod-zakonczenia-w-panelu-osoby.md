# Powód zakończenia poprzedniej rekrutacji w panelu osoby (03.11.2026)
<!-- indeks: zakończona rekrutacja bez notatek też ma kartę w „Wcześniej u nas”, powód w osobnej linii, zwinięte „Co już wiemy” zaczyna od wyniku i powodu -->

Decyzja Artura 03.11.2026 (wariant A + B z makiet `Reff75vQdNfDNnRQD6mMUw`).
Delivery Lead szukał powodu odrzucenia z ostatniej rekrutacji w „Notatkach
i historii” i go nie znalazł, bo grupy powstawały wyłącznie z notatek, a powód
leży w etapie osoby. Na kopii z 03.11 dotyczyło to 1428 z 2141 osób z otwartą
kartą i zapisanym powodem w ostatniej zakończonej rekrutacji.

- **Karta bez notatek.** `splitPersonNotes` z historią osoby tworzy grupę także
  dla zakończonej rekrutacji bez notatek. Rekrutacja w toku bez notatek karty
  nie dostaje, bieżąca też nie. Taka karta nie ma czego rozwijać, więc nie ma
  przycisku. Karty idą od najświeższego zdarzenia: notatki albo ruchu etapu.
- **Powód w osobnej linii** pod tytułem karty, a nie w linii z faktami, żeby
  był widoczny bez przewijania przy 1280 × 720. Odrzucenie i rezygnacja bez
  powodu mówią „bez zapisanego powodu”; zatrudnienie i zamknięta rekrutacja nie
  mają tej linii (`outcomeReasonText`).
- **Zwinięte „Co już wiemy”** zaczyna drugą linię od wyniku i powodu, potem
  tytuł rekrutacji, „W bazie od” i „W innych rekrutacjach”. Ta linia zawija się
  do dwóch wierszy, bo ucięcie ma zabrać tytuł, a nie powód. Bez zakończonej
  rekrutacji linia zostaje jednowierszowa.
- **Odrzucone:** pigułka w głowie panelu (wariant C). Głowa się nie przewija,
  więc zabierałaby 16 px na każdej zakładce.
- **Wąski dok** pyta `splitPersonNotes` bez historii, więc jego licznik i skrót
  rozmów się nie zmieniają.
