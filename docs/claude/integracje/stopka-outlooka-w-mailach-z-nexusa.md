# Stopka Outlooka w mailach z NEXUSA

Mail wysłany z NEXUSA (profil kandydata, odpowiedź w wątku) ma wyglądać jak
wysłany z Outlooka. 26.10.2026 zespół dostał próbny mail z profilu kandydata
z „--” nad stopką, domyślną czcionką zamiast stopki firmowej i pustą ramką
zamiast logo.

## Jak to działa

- Graph nie daje dostępu do podpisu ustawionego w Outlooku, więc
  `m365/signature_cache.py` bierze stopkę z jednego z 10 ostatnich maili
  w „Wysłanych” (reguły wycinania: `audyty/audyt-25-09-2026-reguly-po-naprawie.md`).
  Wynik jest trzymany 24 h na skrzynkę, a wdrożenie go czyści.
- `m365/sender.py` dokleja stopkę pod treścią po jednym pustym wierszu
  w `<div class="nexus-signature">`. Bez „--”: Outlook go nie wstawia.

## Czego nie cofać

- **Style stopki zostają.** Stopka przechodzi przez `sanitize_signature_html`
  (lista dozwolonych właściwości CSS w `html_sanitize.py`), a nie przez
  `sanitize_html` treści maila, który `style` wycina. Bez stylów klauzula
  RODO i dane kontaktowe wychodzą domyślną czcionką jako zbity blok.
- **Logo to załącznik.** Obrazek w stopce Outlooka to załącznik `isInline`
  tej samej wysłanej wiadomości, do którego HTML odsyła przez `src="cid:…"`.
  NEXUS pobiera go razem ze stopką i dołącza do szkicu
  (`POST /me/messages/{id}/attachments`, `isInline`, ten sam `contentId`)
  przed `/send`. Obrazek, którego nie udało się pobrać, wypada z HTML-a.
  Pusta ramka u odbiorcy jest gorsza niż brak logo.
- Błąd przy pobieraniu albo dołączaniu logo nie blokuje wysyłki: mail
  wychodzi bez logo. Tak samo jak przy samej stopce, brak stopki jest
  lepszy niż niewysłany mail.
