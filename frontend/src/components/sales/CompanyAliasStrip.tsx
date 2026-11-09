"use client";

import Link from "next/link";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCompanyAliases,
  useDecideCompanyAlias,
  useUndoCompanyAlias,
  type AliasDecision,
  type AliasStatus,
  type AliasVariant,
  type CompanyAliases,
} from "@/lib/api/sales";

import { plural } from "./peoplePlural";

interface CompanyAliasStripProps {
  companyId: number;
  canEdit: boolean;
}

function restNote({ other_count: count, other_min: min, other_max: max }: CompanyAliases): string | null {
  if (count === 0) return null;
  const notes = plural(count, "rzadki zapis", "rzadkie zapisy", "rzadkich zapisów");
  const range = min === max ? `${min}` : `${min}–${max}`;
  return `największe trzy, poza nimi ${count} ${notes}, po ${range} ${plural(max, "osobie", "osoby", "osób")}`;
}

function peopleLine(variant: AliasVariant): string {
  return `${variant.people} ${plural(variant.people, "osoba", "osoby", "osób")}, ${variant.current} teraz`;
}

const DECIDED_LABEL: Record<AliasStatus, string> = {
  joined: "Dołączone",
  rejected: "Nie ta firma",
};

/**
 * Pas „Inne nazwy z CV” na karcie firmy: warianty do dołączenia, decyzje do
 * cofnięcia i nazwy, które mają już własną kartę. Osobne zapytanie, bo skan
 * wpisów CV nie może zatrzymywać listy osób.
 */
export function CompanyAliasStrip({ companyId, canEdit }: CompanyAliasStripProps) {
  const aliases = useCompanyAliases(companyId);
  const decide = useDecideCompanyAlias(companyId);
  const undo = useUndoCompanyAlias(companyId);
  const { showError } = useToast();
  const busy = decide.isPending || undo.isPending;

  if (aliases.isError) {
    return (
      <p className="text-xs text-muted-foreground">
        Nie udało się sprawdzić innych nazw z CV.{" "}
        <button type="button" className="text-primary hover:underline" onClick={() => void aliases.refetch()}>
          Spróbuj ponownie
        </button>
      </p>
    );
  }
  if (!aliases.isSuccess) return null;
  const data = aliases.data;
  if (data.suggestions.length === 0 && data.decisions.length === 0 && data.own_cards.length === 0) {
    return null;
  }

  const onError = (error: unknown) =>
    showError(apiErrorMessage(error, "Nie udało się zapisać decyzji o nazwie firmy."));
  const save = (name: string, status: AliasStatus) => decide.mutate({ name, status }, { onError });
  const revert = (decision: AliasDecision) => undo.mutate(decision.id, { onError });
  const note = restNote(data);

  return (
    <section aria-label="Inne nazwy z CV" className="rounded-md border border-border bg-muted/40 px-3 py-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Inne nazwy z CV</span>
          {note && ` · ${note}`}
        </p>
        {data.own_cards.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Mają własne karty:{" "}
            {data.own_cards.map((card, index) => (
              <span key={card.id}>
                {index > 0 && ", "}
                <Link href={`/sales/companies/${card.id}`} className="text-primary hover:underline">
                  {card.name}
                </Link>
                <span className="tabular-nums"> · {card.current} teraz</span>
              </span>
            ))}
          </p>
        )}
      </div>
      {data.suggestions.length > 0 && (
        <ul className="mt-0.5 grid gap-x-4 gap-y-1 [grid-template-columns:repeat(auto-fit,minmax(13rem,1fr))]">
          {data.suggestions.map((variant) => (
            <li key={variant.key} className="min-w-0">
              <div className="flex min-w-0 items-baseline gap-1.5 text-sm">
                <TruncatedText className="min-w-0 max-w-none text-foreground">{variant.name}</TruncatedText>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">· {peopleLine(variant)}</span>
              </div>
              {canEdit && (
                <p className="flex gap-3 text-xs">
                  <button
                    type="button"
                    aria-label={`Dołącz: ${variant.name}`}
                    className="text-primary hover:underline disabled:opacity-50"
                    disabled={busy}
                    onClick={() => save(variant.name, "joined")}
                  >
                    Dołącz
                  </button>
                  <button
                    type="button"
                    aria-label={`Nie ta firma: ${variant.name}`}
                    className="text-muted-foreground hover:underline disabled:opacity-50"
                    disabled={busy}
                    onClick={() => save(variant.name, "rejected")}
                  >
                    Nie ta firma
                  </button>
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {data.decisions.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
          {data.decisions.map((decision) => (
            <li key={decision.id} className="flex min-w-0 items-baseline gap-1.5">
              <span className="min-w-0 truncate">
                {DECIDED_LABEL[decision.status]}: {decision.name}
              </span>
              {canEdit && (
                <button
                  type="button"
                  aria-label={`Cofnij: ${decision.name}`}
                  className="shrink-0 text-primary hover:underline disabled:opacity-50"
                  disabled={busy}
                  onClick={() => revert(decision)}
                >
                  Cofnij
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
