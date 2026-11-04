// Nordea: pozycja faktury cyklicznej (ticket 8). Formułę składa SERWER
// (`nordea_invoice_lines.py`); tu tylko rozpoznanie brakującego pola.

/** Znacznik pola, którego nie udało się odczytać z PDF-a zamówienia. */
export const INVOICE_LINE_MISSING = "[brak]";

export function hasMissingInvoiceData(text: string): boolean {
  return text.includes(INVOICE_LINE_MISSING);
}

/** Tekst pocięty tak, że każdy `[brak]` jest osobnym kawałkiem (podświetlenie). */
export function invoiceLineSegments(text: string): string[] {
  return text
    .split(/(\[brak\])/)
    .filter((segment) => segment.length > 0);
}
