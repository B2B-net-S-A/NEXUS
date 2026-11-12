"use client";

import { Check, X } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { TIER_LABELS, type CompanyTier, type SalesCompany } from "@/lib/api/sales";
import {
  ENRICH_FIELDS,
  useCompanyEnrich,
  useDecideEnrich,
  useRejectEnrich,
  useStartEnrich,
  type EnrichField,
  type EnrichFieldKey,
} from "@/lib/api/sales-bot";
import { formatIsoDatePl } from "@/lib/date-pl";

import { BotTag, SourceLink } from "./kit";

export const ENRICH_LABELS: Record<EnrichFieldKey, string> = {
  domain: "Domena",
  website_url: "Strona",
  nip: "NIP",
  hq_city: "Miasto",
  industry: "Branża",
  tier: "Wielkość",
  parent_name: "Firma matka",
};

/** Obecna wartość na karcie, tak jak ją widać w faktach firmy. */
export function currentValue(company: SalesCompany, key: EnrichFieldKey): string | null {
  switch (key) {
    case "tier":
      return company.tier ? TIER_LABELS[company.tier] : null;
    case "parent_name":
      return company.parent?.name ?? null;
    default:
      return company[key] || null;
  }
}

function proposedValue(key: EnrichFieldKey, field: EnrichField): string {
  if (key === "tier") {
    const label = TIER_LABELS[field.value as CompanyTier] ?? field.value;
    return field.employees ? `${label} (${field.employees} osób)` : label;
  }
  return field.value;
}

/** „Uzupełnij z bota” w nagłówku karty firmy; z wyłączoną flagą go nie ma. */
export function EnrichButton({ companyId, disabled }: { companyId: number; disabled?: boolean }) {
  const state = useCompanyEnrich(companyId);
  const start = useStartEnrich(companyId);
  const { showError, showSuccess } = useToast();
  if (!state.isSuccess || !state.data.enabled) return null;
  const running = state.data.run?.status === "started";
  return (
    <Button
      size="sm"
      variant="outline"
      data-tour="sales.company.enrich"
      disabled={disabled || running || start.isPending}
      onClick={() =>
        start.mutate(undefined, {
          onSuccess: () => showSuccess("Bot sprawdza kartę. Propozycje pojawią się tu za kilka minut."),
          onError: (error) => showError(apiErrorMessage(error, "Nie udało się zlecić sprawdzenia karty.")),
        })
      }
    >
      {running ? "Bot sprawdza kartę…" : "Uzupełnij z bota"}
    </Button>
  );
}

interface EnrichCardProps {
  company: SalesCompany;
  canEdit: boolean;
}

/**
 * G-A: bot proponuje pola karty, człowiek przyjmuje je po kolei. Nic nie zapisuje
 * się samo. Pole z inną wartością na karcie przyjmuje się tylko pojedynczo.
 */
export function EnrichCard({ company, canEdit }: EnrichCardProps) {
  const state = useCompanyEnrich(company.id);
  const decide = useDecideEnrich(company.id);
  const reject = useRejectEnrich(company.id);
  const { showError, showSuccess, showInfo } = useToast();

  if (state.isError) {
    return (
      <Card className="p-4">
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać propozycji bota dla tej karty."
          onRetry={() => void state.refetch()}
        />
      </Card>
    );
  }
  if (!state.isSuccess || !state.data.enabled) return null;
  const { result, run } = state.data;
  if (!result) {
    return run?.status === "started" ? (
      <Card className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <BotTag />
        Bot sprawdza kartę, zwykle kilka minut.
      </Card>
    ) : null;
  }

  const fields = ENRICH_FIELDS.filter((key) => result.payload.fields[key]);
  const decisions = result.payload.decisions ?? {};
  const open = fields.filter((key) => !decisions[key]);
  const blank = open.filter((key) => !currentValue(company, key));
  const busy = decide.isPending || reject.isPending;

  const send = (vars: { fields?: EnrichFieldKey[]; reject?: EnrichFieldKey[] }) =>
    decide.mutate(
      { resultId: result.id, ...vars },
      {
        onSuccess: (outcome) => {
          if (outcome.applied.length > 0) {
            showSuccess(`Zapisano na karcie: ${outcome.applied.map((key) => ENRICH_LABELS[key]).join(", ")}.`);
          }
          outcome.notes.forEach((note) => showInfo(note));
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać pola na karcie.")),
      },
    );

  return (
    <Card className="space-y-2 p-4" aria-label="Propozycje bota dla karty">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-foreground">Bot uzupełnił kartę</h2>
          <BotTag />
        </div>
        <span className="text-xs text-muted-foreground">
          sprawdzone {formatIsoDatePl(result.payload.checked_at ?? result.created_at)} · {fields.length}{" "}
          {fields.length === 1 ? "pole" : "pól"} ze źródeł publicznych
        </span>
      </div>
      <ul className="divide-y divide-border">
        {fields.map((key) => {
          const field = result.payload.fields[key] as EnrichField;
          const decision = decisions[key];
          const current = currentValue(company, key);
          return (
            <li
              key={key}
              className="grid grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-2 py-1.5 text-sm"
            >
              <span className="text-xs text-muted-foreground">{ENRICH_LABELS[key]}</span>
              <span className="min-w-0">
                <span
                  className={
                    decision === "rejected"
                      ? "break-words text-muted-foreground line-through"
                      : "break-words font-medium text-foreground"
                  }
                >
                  {proposedValue(key, field)}
                </span>
                <span className="ml-2 inline-flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {current ? <span>teraz: {current}</span> : <span>teraz puste</span>}
                  <SourceLink url={field.source} />
                  {field.published && <span>{formatIsoDatePl(field.published)}</span>}
                </span>
              </span>
              {decision ? (
                <span className="text-xs text-muted-foreground">
                  {decision === "accepted" ? "przyjęte" : "odrzucone"}
                </span>
              ) : canEdit ? (
                <span className="flex gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2"
                    aria-label={`Przyjmij: ${ENRICH_LABELS[key]}`}
                    disabled={busy}
                    onClick={() => send({ fields: [key] })}
                  >
                    <Check className="size-3.5" aria-hidden />
                  </Button>
                  <Button
                    size="sm"
                    variant="quiet"
                    className="h-7 px-2"
                    aria-label={`Odrzuć: ${ENRICH_LABELS[key]}`}
                    disabled={busy}
                    onClick={() => send({ fields: [], reject: [key] })}
                  >
                    <X className="size-3.5" aria-hidden />
                  </Button>
                </span>
              ) : (
                <span />
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Nic nie zapisuje się samo. Domena dołącza maile z Outlooka i osoby do „Kogo znamy”.
          {blank.length < open.length && blank.length > 0 && " Pola z inną wartością na karcie przyjmij pojedynczo."}
        </p>
        {canEdit && open.length > 1 && (
          <span className="flex gap-2">
            <Button size="sm" variant="quiet" disabled={busy} onClick={() =>
              reject.mutate(result.id, {
                onError: (error) => showError(apiErrorMessage(error, "Nie udało się odrzucić propozycji.")),
              })
            }>
              Odrzuć resztę
            </Button>
            {blank.length > 0 && (
              <Button size="sm" disabled={busy} onClick={() => send({ fields: blank })}>
                {blank.length === open.length ? "Przyjmij wszystkie" : "Przyjmij puste pola"}
              </Button>
            )}
          </span>
        )}
      </div>
    </Card>
  );
}
