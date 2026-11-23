/**
 * Stan formularza CV klienta jednym zdaniem — karta Tablicy, kolejka
 * „Do wysłania do klienta” i przegląd DL mówią to samo (0521, 23.11.2026).
 *
 * Klient bierze własny formularz CV (np. SWZ Centrum e-Zdrowia): mówimy
 * o formularzu, nie o CV firmowym. Od 23.11.2026 brak wypełnienia trzyma kartę
 * przed „QC CV” (prośba DL CEZ, #3738); puste pola tylko przypominają — nie
 * blokują ruchu ani wysyłki (decyzja Artura D3).
 */

/** `template` = jest wzór w Plikach, `missing` = puste pola (`null` = niewypełniony). */
export interface ClientFormState {
  template: boolean;
  missing: number | null;
  /** Tabela punktowa (Excel) — od 23.11.2026 też warunek „QC CV”. */
  score_template?: boolean;
  score_missing?: number | null;
}

export interface ClientFormBadgeView {
  label: string;
  tone: "wait" | "ok";
  title: string;
}

export function clientFormStateBadge(form: ClientFormState): ClientFormBadgeView {
  if (!form.template) {
    return {
      label: "Formularz: brak wzoru",
      tone: "wait",
      title:
        "Klient bierze swój formularz CV, a w Plikach rekrutacji nie ma wzoru — dodaje go Delivery Lead.",
    };
  }
  if (form.missing == null) {
    return {
      label: "Brak formularza",
      tone: "wait",
      title:
        "Klient bierze swój formularz CV zamiast CV firmowego — wypełnij go w sekcji CV osoby. Bez formularza karta nie przejdzie na „QC CV”.",
    };
  }
  if (form.score_template && form.score_missing == null) {
    return {
      label: "Brak tabeli punktowej",
      tone: "wait",
      title:
        "Rekrutacja ma wzór tabeli punktowej klienta — wypełnij ją w sekcji CV osoby. Bez niej karta nie przejdzie na „QC CV”.",
    };
  }
  if (form.missing > 0) {
    return {
      label: `Formularz: ${form.missing} do uzupełnienia`,
      tone: "wait",
      title: "Formularz CV klienta ma puste pola — uzupełnij je w sekcji CV osoby. Puste pola nie blokują ruchu.",
    };
  }
  return {
    label: "Formularz gotowy",
    tone: "ok",
    title: "Formularz CV klienta ma wypełnione wszystkie pola.",
  };
}
