# Rozliczenia: kosmetyka raportu przy dobrym MD nie zatrzymuje automatu, konsultant dostaje informację

<!-- indeks: kosmetyka raportu, forma raportu, informacja bez poprawki, notice, note.rows_sum, note.row_dates, note.template_month, Wiersze opisu prac nie sumują się do SUMA, Wiersze z datą spoza miesiąca, Szablon z innym miesiącem w nagłówku, Miesiąc z nazwy pliku, RCP za inny miesiąc, Time Sheet za inny miesiąc, template_month, days_fit, full_month, sum_from_days, template_dates_month, named_month, _named_month, Bez uwag z dopiskiem, Na przyszłość, proof.month, proof.row_dates, proof.name_match, kesu.jira_accept, proof.private_screenshot, cudzy szablon, zrzut z prywatnej skrzynki, Brak maila z Jiry -->

Decyzja Artura z 25.11.2026. Próby na kopiach produkcji (IX–X i VI–VIII 2026) miały
ok. 9 przypadków z MD równymi fakturze Finansów, w których automat „Bez uwag”
(`rozliczenia-automat-przyjecia-bez-uwag.md`) stawał tylko przez formę raportu.
Teraz kosmetyka raportu przy dobrym MD daje status „Bez uwag” z dopiskiem na karcie
i jeden komunikat do konsultanta, co poprawić w kolejnym raporcie.

## Co przestaje blokować i pod jakim warunkiem

Wszystkie warunki muszą być spełnione naraz. Bez któregoś zostaje uwaga jak dotąd.

| Uwaga | Czytnik | Warunek |
|---|---|---|
| „Wiersze opisu prac nie sumują się do SUMA” (BNP, 4 przypadki VI–X) | `rcp_checks.sum_from_days` | SUMA = godziny dni / `fields.md_hours`; pełna siatka 31 dni, suma dni = godziny z wiersza SUMA; „Total MD's” = SUMA; bez wierszy „Godziny dodatkowe …” i bez godzin ponad „Godziny w tygodniu”; dni z godzinami to dni robocze rozliczanego miesiąca. MD z SUMA. |
| „Wiersze z datą spoza miesiąca” (BIK, 1 przypadek VII) | `timesheet_bik.template_dates_month` | pole „Miesiąc” = rozliczany miesiąc; każdy wiersz ma datę, wszystkie z jednego innego miesiąca (szablon, także zeszły rok); dni z godzinami to dni robocze rozliczanego miesiąca, a nie wszystkie są dniami roboczymi miesiąca z dat. |
| „RCP za inny miesiąc” (BNP, VI) | `rcp_checks.template_month_fixed` | `proof.month` włączona; miesiąc z nazwy pliku albo tematu maila = rozliczany (`service._named_month`); pełna siatka dni; bez pracy dodatkowej; dni z godzinami pasują do rozliczanego miesiąca, nie do miesiąca z pola „Rozliczenie”. |
| „Time Sheet za inny miesiąc” (PKO, VIII) | `timesheet_pko.template_month_fixed` | `proof.month` włączona; miesiąc z nazwy pliku albo tematu maila = rozliczany; nowszy szablon: dni z godzinami pasują do rozliczanego miesiąca, nie do miesiąca z dat nagłówka; starszy, bez kolumn dni: godziny to pełny rozliczany miesiąc (dni robocze × godziny MD), a nie pełny miesiąc z nagłówka. |

„Pasują” znaczy: każdy dzień z godzinami jest dniem roboczym rozliczanego miesiąca
(kalendarz firmy, święta), a choć jeden nie jest dniem roboczym miesiąca z szablonu
(`template_month.days_fit`, wzór `timesheet.template_year_fixed`). Dni pasujące do obu
kalendarzy (np. tylko 1–2 października i 1–2 września) niczego nie dowodzą. Starszy
Time Sheet PKO, który ma tyle samo godzin co pełny miesiąc z nagłówka (czerwiec
i sierpień 2026 mają po 21 dni roboczych), też zostaje uwagą.

Miesiąc z nazwy pliku albo tematu maila to okres pliku z poczty, który czytnik poczty
wziął z nazwy albo tematu (`mailbox.period_for`, nie zgadnięty z daty maila). Plik
wgrany w panelu ma okres wybrany ręcznie i niczego nie dowodzi.

Te same informacje (z komunikatem dla konsultanta) dają odtąd przypadki, które już
wcześniej przechodziły bez uwagi: Time Sheet „Rok w szablonie” i „Daty wierszy
z innego miesiąca” (`rozliczenia-falszywe-blokady-przy-zgodnych-md.md`) oraz PKO
„Miesiąc z nazwy pliku” („TimeSheet RRMM” przy nagłówku z poprzedniego miesiąca).

## Dalej blokuje (decyzja Artura)

Brak podpisu PDF (`proof.signed_pdf`), brak maila akceptującego
(`proof.excel_with_mail`, `proof.accept_has_hours`, `proof.request_reply`), inna osoba
w raporcie (`proof.name_match`) i kwota inna niż w protokole Orlenu
(`cl.protocol_amount`). Rozbieżność godzin (`fields.md_hours`, „Suma … inna niż suma
wierszy”, godziny ≠ SUMA) też zostaje uwagą.

## Jak to wygląda

- Uwaga zostaje na karcie rozliczenia jako informacja: `state: "none"` i klucz
  `notice` z kodem (`rcp_checks.NOTE_*`), ten sam tytuł albo „Szablon z innym miesiącem
  w nagłówku”. Nie ustawia `warn` ani `blocking`, więc silnik daje `ok`, a automat
  przyjmuje RCP. Lista miesiąca nie pokazuje jej jako uwagi (liczą się tylko
  `warn`/`fail`). Front rysuje ją jak każdą informację (szara ikona), bez zmian w kodzie.
- Informacja nie zmienia MD ani kwot: liczymy z SUMA albo z wierszy przeniesionych na
  rozliczany miesiąc, tak jak Finanse.

## Informacja zwrotna (`feedback.CATALOG`)

**Informacje bez poprawki** (`Defect.notice`): idą też przy statusie `ok` i `accepted`
(`NOTICE_STATUSES`), jeden komunikat na kod i miesiąc, bez przypomnień. Po komunikacie
(także na sucho albo bez adresata) wiersz dostaje `resolved_on` i nie otwiera się
ponownie. W mailu pozycja ma „Na przyszłość:” zamiast „Co zrobić:”, a mail z samymi
informacjami kończy się zdaniem, że raportu nie trzeba poprawiać. Wada do poprawy
w tym samym mailu dalej ma przypomnienia, informacja nie. `report()` oddaje `notice`.

| Kod | Kto | Kiedy |
|---|---|---|
| `note.rows_sum` | konsultant | wiersze ≠ SUMA przy SUMA = godziny dni |
| `note.row_dates` | konsultant | daty wierszy z szablonu (BIK, Time Sheet: rok albo miesiąc) |
| `note.template_month` | konsultant | nagłówek z innego miesiąca przy dowodzie z nazwy i godzin |

**Wady do poprawy dopisane 25.11.2026** (dotąd bez komunikatu):

| Kod | Kto | Uwaga |
|---|---|---|
| `proof.month` | konsultant | każda `proof.month` poza datami wierszy: „RCP/Time Sheet/KEŚU/KCP/… za inny miesiąc”, „… bez miesiąca” |
| `proof.row_dates` | konsultant | „Wpisy spoza rozliczanego miesiąca”, „Wiersze z datą spoza miesiąca”, „Godziny w dniu spoza miesiąca”; w katalogu przed `proof.month`, bo „Wpisy spoza…” mają tę samą regułę |
| `proof.name_match` | konsultant | „Inne imię lub nazwisko niż w kontrakcie” i braki imienia w szablonach konsultanta; bez eksportów klienta (Fieldglass, Redmine) i bez szczegółu (bywa w nim cudze nazwisko) |
| `kesu.jira_accept` | konsultant | „Brak maila z Jiry z akceptacją opiekuna”: poprosić opiekuna o akceptację w Jirze albo przekazać mail z Jiry |
| `proof.private_screenshot` | konsultant | raport-zdjęcie bez MD z prywatnej skrzynki; z adresu firmowego zostaje `proof.image_file` |

Tryb na sucho i `external=off` bez zmian: nic nie wychodzi poza dziennik
(`rozliczenia-informacja-zwrotna-o-wadach.md`).

## Brak raportu to nie wada

„Brak RCP” z przypomnień dotyczy kontraktu bez rozliczenia i bez pliku
(`reminders.missing_reports`), a informacja zwrotna czyta tylko rozliczenia. Żaden
przypadek nie dostaje więc obu komunikatów (test
`test_brak_raportu_zostaje_przypomnieniom_a_wada_rozliczeniu`).

## Pomiar (25.11.2026, pliki z kopii prób, lokalnie)

Nowy kod na prawdziwych plikach siedmiu przypadków: uwaga z formy raportu zmienia się
w informację we wszystkich, bez blokady, MD bez zmian (BNP wiersze ≠ SUMA: 22, 22, 16
i 21 MD; BNP szablon styczniowy w czerwcu: 21; PKO nagłówek „lipiec” w sierpniu,
168 h: 21; BIK daty z lipca 2025: 22). W jednym przypadku BNP została osobna uwaga
o kosztach delegacji (odczyt bez akceptacji kosztów), której ta zmiana nie dotyczy.
Te same pliki bez miesiąca z nazwy pliku albo tematu (BNP, PKO) dalej blokują.
Przeliczenia rozliczeń na kopii bazy w tej zmianie nie było: sprawdzi je powtórka
próby na XI.
