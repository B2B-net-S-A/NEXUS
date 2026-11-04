// Jedyne miejsce importu zod w aplikacji (formularze importują stąd).
// Zod 4 przy tworzeniu schematu obiektu sprawdza `Function("")` (szybka
// ścieżka JIT). Pod CSP bez 'unsafe-eval' przeglądarka raportuje to jako
// naruszenie — do 25.09.2026 kilkadziesiąt raportów dziennie w Sentry
// (NEXUS-FE-18). Nasze formularze są małe, JIT nic im nie daje.
// Ustawienie musi zadziałać PRZED pierwszym schematem, stąd osobny moduł.
import { z } from "zod";

z.config({ jitless: true });

export { z };
