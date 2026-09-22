/**
 * Data „dziś" w kalendarzu firmy (Europe/Warsaw), jako "YYYY-MM-DD".
 *
 * `new Date().toISOString().slice(0, 10)` daje datę UTC: między północą
 * w Warszawie a północą UTC (1–2 h na dobę) wychodzi WCZORAJ. Formularz
 * aneksu otwarty o 00:30 podpowiadał więc wczorajszą datę wejścia w życie,
 * a zwrot sprzętu zapisywał się dniem wcześniej. Backend liczy „dziś"
 * tak samo (`business_today()`), więc obie strony mówią o tym samym dniu.
 *
 * `now` jest parametrem wyłącznie dla testów.
 */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}
