# Jarvis: szkic maila do kandydata (27.10.2026)
<!-- indeks: draft_email (tier link), zdarzenie mail_draft, JarvisMailDraftCard → SendEmailV2 z defaultSubject/defaultBody, plainTextToHtml -->

Decyzja Artura z 27.10.2026: na prośbę o mail do kandydata Jarvis pisze
szkic, a człowiek wysyła go z okna maila NEXUSA (Microsoft 365, mail
w historii kandydata). Wysyłka dalej nigdy nie idzie od Jarvisa.

- `draft_email` (tier `link`, obsługa w `agent._draft_email`): adres
  i nazwisko serwer czyta z `GET /api/candidates/{id}/quick-view` tokenem
  pytającego — nie ze słów modelu. Brak adresu albo dostępu = błąd do
  modelu, bez karty. Rozmowa wiąże się z kandydatem (RODO).
- Karta „Szkic maila — nic nie wysłano”: „Otwórz w oknie maila” otwiera
  `SendEmailV2` z `defaultSubject`/`defaultBody`; szkic z historii nie ma
  adresu i doczytuje go przy kliknięciu. „Kopiuj treść” jako zapas.
- Treść od modelu idzie do edytora przez `plainTextToHtml` (escapowanie) —
  nigdy jako HTML.
