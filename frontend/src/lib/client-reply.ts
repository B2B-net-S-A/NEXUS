/**
 * „Odpisz klientowi” (0487, 20.10.2026): rekruter wybrał termin z kandydatem,
 * rozmowa jest już w kalendarzu, a Delivery Lead potwierdza ją klientowi
 * mailem. Tekst to propozycja do skopiowania — DL może go poprawić.
 */
const DAY = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  weekday: "long",
  day: "numeric",
  month: "numeric",
});
const TIME = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  hour: "2-digit",
  minute: "2-digit",
});

export function clientReplyText({
  candidateName,
  start,
  durationMinutes,
  signature,
}: {
  candidateName: string;
  start: string;
  durationMinutes: number;
  signature: string | null;
}): string {
  const when = new Date(start);
  const lines = [
    "Dzień dobry,",
    // Imię i nazwisko w mianowniku — odmiana nazwisk w kodzie myliłaby się.
    `potwierdzamy termin rozmowy (kandydat: ${candidateName}): ${DAY.format(when)} o ${TIME.format(when)}, ${durationMinutes} min.`,
    "",
    "Pozdrawiam",
  ];
  if (signature) lines.push(signature);
  return lines.join("\n");
}
