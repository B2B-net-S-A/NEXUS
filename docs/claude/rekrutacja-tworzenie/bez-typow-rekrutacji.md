# Bez typów rekrutacji (decyzja Artura 25.09.2026)

Nie ma rekrutacji „body leasing”, „sales” ani „przetarg” — każda rekrutacja
jest po prostu rekrutacją. `jobs.recruitment_type` to MARTWA kolumna: zostaje
w bazie (NOT NULL, domyślnie `body_leasing`) wyłącznie do osobnej migracji
usuwającej, ale API jej nie przyjmuje ani nie oddaje, UI jej nie pokazuje,
a statystyki (liga DL, Insights DL, cele KPI DL, stary raport DL) liczą
wszystkie rekrutacje. `/api/reports/tenders` usunięty. Stary `?type=` w adresie
`/jobs` jest ignorowany i zdejmowany. Nie dokładaj logiki zależnej od typu —
pilnuje `tests/test_no_recruitment_types.py`. „Przetargi” w
`/api/analytics/v1/commercial/tenders` to grupowanie po powodzie zamknięcia,
nie typ rekrutacji.
