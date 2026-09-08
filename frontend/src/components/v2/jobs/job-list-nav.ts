/**
 * Nawigacja „N z M" w doku listy rekrutacji (makieta „01 Lista", `.dnav`).
 *
 * Kontrakt między `JobsListV2` (dostawcą) a `JobReadinessDock` (konsumentem).
 * Osobny plik, żeby obie strony wiązały się z TĄ SAMĄ deklaracją — a nie
 * z dwoma kształtami, które są zgodne dopóki nikt żadnego nie poprawi.
 *
 * `index` jest **1-based** (tak, jak się to czyta: „1 z 12"), więc pierwszy
 * wiersz to `1`, nie `0`.
 */
export interface JobListNav {
  index: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}
