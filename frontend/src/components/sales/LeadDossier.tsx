import Link from "next/link";
import type { ReactNode } from "react";

import type { Lead, LeadDossier as Dossier } from "@/lib/api/sales";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

/** NIP z 10 cyfr jako 000-000-00-00; inny zapis bez zmian. */
export function formatNip(nip: string): string {
  const digits = nip.replace(/\D/g, "");
  return digits.length === 10
    ? `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 8)}-${digits.slice(8)}`
    : nip;
}

function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p className="min-w-0">
      <span className="font-medium text-foreground">{label}:</span>{" "}
      <span className="text-muted-foreground">{children}</span>
    </p>
  );
}

/**
 * Teczka leada (decyzja Artura 13.11.2026): firma, kogo znamy, decydenci i punkty
 * na pierwszą rozmowę, liczone z danych NEXUSA. Pusta teczka nie rysuje bloku.
 */
interface LeadDossierProps {
  dossier: Dossier | null | undefined;
  /** Wąski panel obok listy: jedna kolumna zamiast dwóch. */
  compact?: boolean;
}

export function LeadDossier({ dossier, compact = false }: LeadDossierProps) {
  if (!dossier) return null;
  const company = [
    dossier.industry,
    dossier.city,
    dossier.nip ? `NIP ${formatNip(dossier.nip)}` : null,
    dossier.website,
  ].filter(Boolean);
  const known = [
    dossier.known > 0
      ? `${countPl(dossier.known, "osoba", "osoby", "osób")}, ${dossier.known_with_email} z e-mailem`
      : null,
    dossier.owner ? `opiekun ${dossier.owner}` : null,
  ].filter(Boolean);
  const lines = [
    company.length > 0 && (
      <Line key="company" label="Firma">
        {company.join(" · ")}
      </Line>
    ),
    known.length > 0 && (
      <Line key="known" label="Znamy">
        {known.join(" · ")}
      </Line>
    ),
    dossier.decision_makers.length > 0 && (
      <Line key="people" label="Decydenci">
        {dossier.decision_makers.join(", ")}
      </Line>
    ),
    dossier.points > 0 && (
      <Line key="points" label="Na pierwszą rozmowę">
        {countPl(dossier.points, "punkt", "punkty", "punktów")} ·{" "}
        <Link href={`/sales/companies/${dossier.company_id}`} className="text-primary hover:underline">
          karta firmy
        </Link>
      </Line>
    ),
  ].filter(Boolean);
  if (lines.length === 0) return null;
  return (
    <div
      data-testid="lead-dossier"
      className={cn(
        "mt-2 grid gap-x-6 gap-y-1 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs",
        !compact && "sm:grid-cols-2",
      )}
    >
      {lines}
    </div>
  );
}

/** W grupie leadów jednej firmy teczka stoi raz: przy pierwszym leadzie tej firmy na liście. */
export function firstLeadOfCompany(leads: readonly Pick<Lead, "id" | "company_id">[]): Set<number> {
  const seen = new Set<number>();
  const first = new Set<number>();
  for (const lead of leads) {
    if (lead.company_id == null || seen.has(lead.company_id)) continue;
    seen.add(lead.company_id);
    first.add(lead.id);
  }
  return first;
}
