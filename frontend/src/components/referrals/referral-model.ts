import type { CandidateReferral, ReferralStatus } from "@/lib/api/candidateReferrals";

/** Premia 1–5 tys. zł zależnie od profilu (Artur, 28.11.2026); serwer sprawdza to samo. */
export const BONUS_MIN = 1000;
export const BONUS_MAX = 5000;

export const REFERRAL_STATUSES: readonly ReferralStatus[] = [
  "new",
  "contacted",
  "started",
  "paid",
  "rejected",
];

export const REFERRAL_STATUS_LABEL: Record<ReferralStatus, string> = {
  new: "Nowe",
  contacted: "Rozmowa",
  started: "Zaczął projekt",
  paid: "Premia wypłacona",
  rejected: "Odrzucone",
};

export type ReferralActionKind = "status" | "bonus" | "paid";

export interface ReferralAction {
  kind: ReferralActionKind;
  to?: Exclude<ReferralStatus, "paid">;
  label: string;
  destructive: boolean;
}

/** Te same przejścia co `TRANSITIONS` w `services/website_referrals.py`. */
const RECRUITER_ACTIONS: Record<ReferralStatus, readonly ReferralAction[]> = {
  new: [
    { kind: "status", to: "contacted", label: "Rozmowa", destructive: false },
    { kind: "status", to: "rejected", label: "Odrzuć", destructive: true },
  ],
  contacted: [
    { kind: "status", to: "started", label: "Zaczął projekt", destructive: false },
    { kind: "status", to: "rejected", label: "Odrzuć", destructive: true },
  ],
  started: [
    { kind: "bonus", label: "Zmień kwotę", destructive: false },
    { kind: "status", to: "contacted", label: "Cofnij do rozmowy", destructive: false },
    { kind: "status", to: "rejected", label: "Odrzuć", destructive: true },
  ],
  rejected: [{ kind: "status", to: "new", label: "Przywróć", destructive: false }],
  paid: [],
};

export function actionsFor(
  referral: CandidateReferral,
  { canPay }: { canPay: boolean },
): readonly ReferralAction[] {
  const actions = RECRUITER_ACTIONS[referral.status];
  if (canPay && referral.status === "started") {
    return [{ kind: "paid", label: "Wypłacona", destructive: false }, ...actions];
  }
  return actions;
}

/** Kwota z okna („2 500”, „2500,00”) → tekst dla API albo `null`, gdy poza widełkami. */
export function parseBonus(raw: string): string | null {
  const value = Number(raw.replace(/\s/g, "").replace(",", "."));
  if (!Number.isFinite(value) || value < BONUS_MIN || value > BONUS_MAX) return null;
  return value.toFixed(2);
}

export function formatBonus(amount: string | null): string {
  if (amount === null) return "nie ustalono";
  return `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 }).format(Number(amount))} zł`;
}

/** Jak premia trafi do polecającego (decyzja Artura 28.11.2026). */
export function payoutLine(referral: CandidateReferral): string {
  return referral.referrer_contract_id !== null
    ? "konsultant B2B, premię dopisze do faktury"
    : "spoza B2B, premia na podstawie krótkiej umowy";
}
