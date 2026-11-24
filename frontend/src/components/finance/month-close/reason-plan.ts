import type { StatusDotTone } from "@/components/ds/StatusDot";

/** Kto rozstrzyga powód z kolejki „Do decyzji” i dokąd prowadzi akcja. */
export interface ReasonPlan {
  who: string;
  tone: StatusDotTone;
  action: string;
  /** Podzakładka „Rozliczeń klientów” (`stSub`), na którą prowadzi akcja. */
  sub?: "rules" | "month";
  hint?: string;
}

const CONSULTANT_FIX: ReasonPlan = {
  who: "Konsultant: poprawka pliku",
  tone: "danger",
  action: "Odeślij do poprawy",
  sub: "month",
};
const ORDER: ReasonPlan = {
  who: "Opiekun: zamówienie lub stawka",
  tone: "warning",
  action: "Sprawdź zamówienie",
  sub: "month",
};

const PLANS: Record<string, ReasonPlan> = {
  missing: { who: "Konsultant albo opiekun", tone: "neutral", action: "Zobacz brakujące", sub: "month", hint: "raportu nie ma w poczcie rozliczeń" },
  no_md: { who: "Finanse: wpisz MD z pliku", tone: "info", action: "Wpisz MD", sub: "month" },
  "proof.accept_has_hours": {
    who: "Finanse: decyzja reguły",
    tone: "warning",
    action: "Reguła klienta",
    sub: "rules",
    hint: "czy samo „Akceptuję” od kierownika wystarcza",
  },
  "proof.excel_with_mail": { who: "Konsultant: mail z akceptacją", tone: "warning", action: "Poproś o akceptację", sub: "month" },
  "pay.per_person": { who: "Opiekun: podpis klienta", tone: "warning", action: "Sprawdź podpisy", sub: "month" },
  "travel.extra_costs_confirm": { who: "Finanse: koszty dodatkowe", tone: "warning", action: "Zatwierdź koszty", sub: "month" },
  "travel.rcp_costs": { who: "Finanse: koszty delegacji", tone: "warning", action: "Sprawdź delegację", sub: "month" },
  "fields.md_month_limit": ORDER,
  needs_fix: { who: "Konsultant: odesłane do poprawy", tone: "danger", action: "Otwórz", sub: "month" },
};

export function reasonPlan(key: string): ReasonPlan {
  if (PLANS[key]) return PLANS[key];
  if (/zamówieni|stawki|MD przy/i.test(key)) return ORDER;
  return CONSULTANT_FIX;
}
