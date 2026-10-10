# Zapis zamówienia: „Network Error" znaczy nieobsłużone 500

`UnhandledErrorMiddleware` (`app/main.py`) jest dodane jako PIERWSZE, czyli
NAJGŁĘBIEJ w stosie — pod `CORSMiddleware`. Bez niego wyjątek z handlera leci
ponad całym stosem do starlette'owego `ServerErrorMiddleware`, które odpowiada
gołym 500 bez `Access-Control-Allow-Origin`; przeglądarka blokuje odpowiedź
i użytkownik widzi wyłącznie „Network Error" — bez statusu, bez treści, bez
śladu w zgłoszeniu. Kolejność `add_middleware` jest tu load-bearing.

Warstwa wyżej: `commit_order_write` (`services/order_write_errors.py`) zamienia
znane naruszenia więzów modułu zamówień na 409 z komunikatem po polsku.
Dopisując CHECK w migracji, dopisz tam zdanie — inaczej operator dostanie
komunikat ogólny i nie będzie wiedział, którego pola dotyczy.

Cztery odtworzone ścieżki, które kończyły się „Network Error" (wszystkie
naprawione, każda ma test w `test_order_write_unhandled_500.py`):
`POST /orders` z `md_quantity` (brak `md_remaining` → CHECK; regresja
PR #1276), nazwa pliku PDF > 255 znaków, nieistniejące `job_id` /
`framework_contract_id` w PATCH, przepełnienie `Numeric(12,3)` przy
relabelingu stawek w materializerze.
