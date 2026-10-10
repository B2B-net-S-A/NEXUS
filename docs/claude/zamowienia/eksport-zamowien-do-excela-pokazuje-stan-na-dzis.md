# Eksport zamówień do Excela pokazuje stan NA DZIŚ

`POST /api/clients/{id}/orders/export` bierze wyłącznie zamówienia
OBOWIĄZUJĄCE w dniu pobrania i **dokładnie jedno na konsultanta**.

- Reguła jest JEDNA i mieszka po obu stronach: `is_current_order_period`
  (`order_excel_export.py`) oraz `isCurrentOrder` (`lib/client-order-list.ts`).
  Brak daty końca = bezterminowo; brak daty startu = już obowiązuje (rekordy
  historyczne nagminnie nie mają startu). Status `completed`/`cancelled`
  odpada niezależnie od dat — linia domknięta bez daty przechodzi test okresu.
- **Zamówienie „kończące się" JEST aktualne** — dopóki data nie minęła,
  konsultant pracuje.
- **Deduplikacja idzie po KONTRAKCIE, nie po imieniu**: imiona się powtarzają,
  a ta sama osoba u tego samego klienta ma dokładnie jeden kontrakt. Obejmuje
  też linie grup, więc konsultant nie pojawi się raz w grupie i raz jako karta.
- **Filtr linii grupy czyta okres LINII, a w jego braku okres GRUPY.** Linie
  zwykle nie niosą własnych dat (arkusz renderuje je z okresu zamówienia), więc
  filtr patrzący tylko na kolumny linii przepuszczałby całą obsadę zamówienia
  zakończonego rok temu.
- Wiersz zbiorczy grupy („Całe zamówienie…") zostaje niezależnie od filtra —
  opisuje zamówienie, nie osobę.
