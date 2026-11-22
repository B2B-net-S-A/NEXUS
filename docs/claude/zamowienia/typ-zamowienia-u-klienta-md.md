# Typ zamówienia u klienta rozliczanego w MD: szkic po zatrudnieniu i odczyt PDF-a

Zgłoszenie 18.11.2026 (BNP 4643_2026): u klienta z 50 zamówieniami MD na 51
powstało aktywne zamówienie OKRESOWE w zł/h, bez budżetu MD i bez zużycia
z importów (październikowe 14 MD leżały w imporcie „bez dopasowania”).
Naprawione ręcznie przez API; zabezpieczenia wybrał Artur na makietach
(warianty A, B1, C; D w osobnym PR-ze).

- **Szkic po zatrudnieniu bierze typ, w którym klient się rozlicza**
  (`most_common_order_type`), nie typ ostatnio założonego zamówienia.
  Przyczyna zgłoszenia: `_ensure_open_order` wziął `suggested_order_type`
  (ostatni typ) i założył szkic okresowy. Poczta zamówień zostaje przy
  ostatnim typie — ma własny odczyt dokumentu.
- **PDF z liczbą MD przestawia szkic okresowy na MD** (`EditOrderDialog`,
  „Uzupełnij zamówienie”). Odczyt zwracał `md_total`, a okno pomijało go, gdy
  typ był okresowy. Teraz: typ MD, budżet z dokumentu, stawki przeliczone na
  MD (1 MD = 8 h), baner z „Cofnij — zostaw okresowe”, które przywraca stawki,
  jednostkę i budżet sprzed odczytu. Tylko szkic z jawnym typem
  (`canSelectOrderType`); aktywnego zamówienia odczyt nie przestawia.
- **Przełącznik typu pokazuje „zwykle u klienta”** (`OrderTypeSwitch.usualType`)
  w trzech oknach z wyborem typu, a przy innym wyborze zdanie „U tego klienta
  zamówienia są zwykle typu …”. Dopisek w przycisku ma `aria-hidden`: nazwa
  radia zostaje „MD”/„Okresowe”, bo po niej szukają testy i czytniki ekranu.
  W `EditOrderDialog` podpowiedź tylko, gdy wołający poda `suggestedOrderType`
  (domyślne „periodic” nie może udawać typu klienta).
