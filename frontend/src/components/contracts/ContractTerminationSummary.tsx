import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import {
  agreementModeLabel,
  agreementPartyLabel,
  signedOnLabel,
} from "@/lib/contract-termination";
import type { AgreementTerminationMode } from "@/lib/api";

export interface ContractTerminationFacts {
  terminated_at?: string | null;
  end_date?: string | null;
  agreement_termination_mode?: string | null;
  agreement_termination_party?: string | null;
  agreement_termination_signed_on?: string | null;
  agreement_last_day?: string | null;
}

/**
 * Daty zakończenia współpracy — karta kontraktu i profil konsultanta (ticket
 * 09.2026, pkt 5). Bez rozwiązania umowy: tylko „Koniec zamówienia". Przy
 * rozwiązaniu także ostatni dzień umowy, tryb, strona i data złożenia
 * wypowiedzenia albo zawarcia porozumienia — koniec projektu i koniec umowy
 * to dwie różne daty i obie muszą być widać obok siebie.
 */
export function ContractTerminationSummary({
  contract,
  compact = false,
}: {
  contract: ContractTerminationFacts;
  compact?: boolean;
}) {
  const projectEnd = contract.terminated_at ?? contract.end_date ?? null;
  const mode = contract.agreement_termination_mode ?? null;
  const rows: { label: string; value: string }[] = [];
  if (projectEnd) rows.push({ label: "Koniec zamówienia", value: formatDate(projectEnd) });
  if (mode && contract.agreement_last_day) {
    rows.push({
      label: "Ostatni dzień umowy",
      value: formatDate(contract.agreement_last_day),
    });
    rows.push({ label: "Tryb", value: agreementModeLabel(mode) ?? mode });
    const party = agreementPartyLabel(contract.agreement_termination_party);
    if (party) rows.push({ label: "Strona", value: party });
    if (contract.agreement_termination_signed_on) {
      rows.push({
        label: signedOnLabel(mode as AgreementTerminationMode),
        value: formatDate(contract.agreement_termination_signed_on),
      });
    }
  }
  if (rows.length === 0) return null;
  if (compact) {
    return (
      <span className="text-xs text-muted-foreground">
        {rows.map((r) => `${r.label}: ${r.value}`).join(" · ")}
      </span>
    );
  }
  return (
    <dl className="text-sm space-y-0.5" data-testid="contract-termination-summary">
      {rows.map((r) => (
        <div key={r.label}>
          <dt className="inline text-muted-foreground">{r.label}: </dt>
          <dd className="inline">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}
