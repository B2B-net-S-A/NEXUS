# Domyślny widok modułu Kontrakty: Aktywne **i** Kończące się

`/contracts` bez parametrów pokazuje `["active", "ending"]`
(`DEFAULT_CONTRACT_STATUS_FILTER`). „Kończący się" to `active` z bliskim końcem,
a nie osobny etap życia umowy — konsultant nadal pracuje, więc domyślne
`["active"]` chowało dokładnie te umowy, którymi trzeba się zająć najpilniej.
Etykieta licznika („N kontraktorów / M aktywnych kontraktów") liczy teraz
**cały zbiór obowiązujących**, nie tylko dokładnie jeden status — inaczej
domyślne wejście do modułu cofało ją do generycznego „osób / kontraktów".
Filtrowanie do pojedynczego statusu i sentinel `status=all` działają bez zmian.
