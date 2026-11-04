# Poczta M365: odpowiedź na zaproszenie bez treści nie zasłania rozmowy
<!-- indeks: puste eventMessageResponse w `emails`, decyzja Artura z 03.11.2026: oznaczenie w UI, dane i automaty bez zmian, liczby z pomiaru -->

Decyzja Artura z 03.11.2026. Outlook zapisuje odpowiedź na zaproszenie jako
osobną wiadomość, zwykle pustą. Delta Graph podaje wtedy `@odata.type`
(`#microsoft.graph.eventMessageResponse`) mimo `$select` bez tego pola: w próbie
z 03.11 wszystkie 14 pustych wiadomości z 50 w Wysłanych miało ten typ.

Takie wiersze dalej zapisujemy przy kandydacie. Zmienia się tylko ekran, bo
rekruter widział „Wczytuję wiadomość...” bez końca, a pusty wiersz zasłaniał temat
i podgląd rozmowy (181 z 5099 wątków, w 90 z nich była starsza treść).

- `_has_content` w `app/api/email_threads.py`: wiersz listy wątków bierze temat
  i podgląd z ostatniej wiadomości z treścią. Załącznik i kategoria prywatna liczą
  się jak treść.
- `lib/email-blank-message.ts` na froncie: opis pustej wiadomości. Odpowiedź na
  zaproszenie nie ma plakietki „Wysłane z ATS” ani przycisku „Odpowiedz”, a
  `planThreadReply` jej nie wybiera. Rozpoznanie opiera się na pustej treści
  i początku tematu; nowy język Outlooka trafi najwyżej do opisu „Ta wiadomość
  nie ma treści.”.
- „Wczytuję” tylko w trakcie zapytania, a awaria ma własny komunikat, bo nie może
  wyglądać jak brak treści.

Automaty liczą te wiersze jak zwykły mail i zostaje tak świadomie. Pomiar z 03.11:

- Follow-upy: po usunięciu pustych wierszy 0 z 429 terminów się zmienia (kontrola
  bez wszystkich wysłanych maili: 34). Kliknięcie „Akceptuj” przy kandydacie
  czekającym na klienta przesunie jednak termin telefonu o 14 dni. Gdyby to zaczęło
  się zdarzać, filtr należy do `_last_contacts` w `services/candidate_followups.py`.
- Rytm pracy: 6 wierszy u rekruterów w 30 dni.
- Oś firmy w Sprzedaży: 225 z 237 pustych wpisów to takie odpowiedzi, bez wpływu na
  wskaźniki.
