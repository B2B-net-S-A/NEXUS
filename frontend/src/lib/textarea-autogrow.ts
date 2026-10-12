// Czysty rachunek wysokości pola, które rośnie z tekstem (MentionTextarea).

export interface TextareaMetrics {
  /** Wysokość treści z paddingiem, bez ramki (`scrollHeight`). */
  scrollHeight: number;
  /** Wysokość linii w px — na dotyku bywa ułamkowa (16 px × 4/3). */
  lineHeight: number;
  /** Padding góra + dół w px. */
  padding: number;
  /** Ramka góra + dół w px (`offsetHeight − clientHeight`). */
  border: number;
}

export interface TextareaFit {
  /** Wysokość do `style.height` — pole jest `border-box`, więc z ramką. */
  height: number;
  /** Tekst nie mieści się w `maxRows` linii — pole przewija się w środku. */
  scroll: boolean;
}

/**
 * Wysokość pola dla treści: tyle, ile zajmuje tekst, najwyżej `maxRows` linii.
 * Minimum daje przeglądarka z atrybutu `rows` — jest już w `scrollHeight`.
 * `null` = układ niepoliczony (jsdom, pole w ukrytym panelu): nie ustawiaj nic.
 */
export function textareaFitHeight(metrics: TextareaMetrics, maxRows: number): TextareaFit | null {
  const { scrollHeight, lineHeight, padding, border } = metrics;
  if (!(scrollHeight > 0) || !(lineHeight > 0)) return null;
  const cap = Math.ceil(lineHeight * maxRows) + padding;
  return { height: Math.min(scrollHeight, cap) + border, scroll: scrollHeight > cap };
}
