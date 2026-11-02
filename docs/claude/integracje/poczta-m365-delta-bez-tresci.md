# Poczta M365: aktualizacja delty bez treści nie zmienia zapisanego maila

Delta Graph potrafi oddać zmienioną wiadomość bez `body`, zwykle po samym
przeczytaniu, choć `$select` je zawiera. Brak klucza znaczy „bez zmian”, a nie
pustą wartość. Do 02.11.2026 sync czytał go jak pustą wartość, więc przeczytany
mail tracił treść, podgląd i flagę załączników (pomiar 02.11: 2782 wiersze
z 13 skrzynek, 1477 przy kandydatach). Ślad w danych: `body_html IS NULL`,
pusty `body_text` i `body_preview`, a `has_attachments = false` mimo wierszy
w `email_attachments`.

Reguły w `app/services/m365/sync.py`:

- Wiadomość bez `body` idzie przez `_apply_partial_delta`: zmienia tylko pola,
  które przyszły. Bez dopasowania do kandydata i bez pobierania załączników,
  bo nie ma z czego ich liczyć.
- Wiadomość bez `body`, której nie ma w bazie, nie zakłada wiersza: nie ma
  nadawcy ani tematu.
- `_apply_email_update` nie kasuje zapisanej treści pustą. Kasuje ją wyłącznie
  kategoria prywatna (`M365_IGNORE_CATEGORY`), bo to decyzja właściciela skrzynki.
- Nowe pole czytane z wiadomości Graph czytaj z rozróżnieniem „brak klucza” i
  „pusta wartość”; `msg.get(...) or ""` zaciera tę różnicę.

Log `m365_partial_delta` niesie same nazwy kluczy wiadomości, bez treści.

Odzyskanie starych wierszy: `python -m app.cli.m365_email_body_refetch`
(opis, próba na sucho i cofnięcie w docstringu skryptu). Uruchamiaj po wdrożeniu
poprawki i po zgodzie Artura.
