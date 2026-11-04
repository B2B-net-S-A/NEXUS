"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useLinkTechCard,
  useUnlinkedTechCards,
  type LinkableContract,
  type UnlinkedTechCard,
} from "@/lib/api/care";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { CONTRACT_STATUS_LABELS } from "@/lib/status-labels";
import { cn } from "@/lib/utils";

/** „Anna Nowak · 01.03.2026 – bezterminowo · Aktywny” (bez stawek). */
export function contractLabel(contract: LinkableContract): string {
  const from = contract.start_date ? formatIsoDatePl(contract.start_date) : "bez daty startu";
  const to = contract.end_date ? formatIsoDatePl(contract.end_date) : "bezterminowo";
  const status = CONTRACT_STATUS_LABELS[contract.status] ?? contract.status;
  return `${contract.candidate_name ?? "Bez kandydata"} · ${from} – ${to} · ${status}`;
}

function LinkDialog({
  clientId,
  card,
  contracts,
  onClose,
}: {
  clientId: number;
  card: UnlinkedTechCard;
  contracts: LinkableContract[];
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const link = useLinkTechCard(clientId);
  const suggestedIds = new Set(card.suggestions.map((contract) => contract.id));
  const others = contracts.filter((contract) => !suggestedIds.has(contract.id));
  const [picked, setPicked] = useState<number | null>(card.suggestions[0]?.id ?? null);
  const [error, setError] = useState<string | null>(null);

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Połącz kartę z kontraktem`}
      description={`${card.person_name ?? "Konsultant bez nazwiska"} · rozmowa ${formatIsoDatePl(card.interview_on)}. Karta trafi do zakładki „Opieka” wybranego kontraktu.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={picked === null || link.isPending}
            onClick={() =>
              picked !== null &&
              link.mutate(
                { cardId: card.id, contractId: picked },
                {
                  onSuccess: () => {
                    showToast("Karta połączona z kontraktem", "success");
                    onClose();
                  },
                  onError: (err) => setError(apiErrorMessage(err, "Nie udało się połączyć karty.")),
                },
              )
            }
          >
            Połącz
          </Button>
        </>
      }
    >
      {card.suggestions.length ? (
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-sm font-medium">Propozycje (ta sama osoba u klienta)</legend>
          {card.suggestions.map((contract) => (
            <label key={contract.id} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="care-link-contract"
                className="mt-1"
                checked={picked === contract.id}
                onChange={() => setPicked(contract.id)}
              />
              <span>{contractLabel(contract)}</span>
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="text-sm text-muted-foreground">
          Import nie znalazł kontraktu z tym imieniem i nazwiskiem u klienta — wybierz go z listy.
        </p>
      )}
      <FormField label="Inny kontrakt klienta" htmlFor="care-link-other" className="mt-3">
        <Select
          value={picked !== null && !suggestedIds.has(picked) ? String(picked) : ""}
          onValueChange={(value) => setPicked(Number(value))}
        >
          <SelectTrigger id="care-link-other">
            <SelectValue placeholder={others.length ? "Wybierz kontrakt" : "Brak innych kontraktów"} />
          </SelectTrigger>
          <SelectContent>
            {others.map((contract) => (
              <SelectItem key={contract.id} value={String(contract.id)}>
                {contractLabel(contract)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/**
 * Karty z Compassa, których import nie połączył z kontraktem (18.10.2026).
 * Bez kart nic nie pokazuje; awaria odczytu mówi o sobie, nie udaje pustki.
 */
export function UnlinkedCardsPanel({ clientId }: { clientId: number }) {
  const query = useUnlinkedTechCards(clientId);
  const [open, setOpen] = useState(false);
  const [linking, setLinking] = useState<UnlinkedTechCard | null>(null);

  if (query.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać kart do połączenia.")}
      </p>
    );
  }
  if (!query.isSuccess || !query.data.items.length) return null;
  const { items, contracts, can_link: canLink } = query.data;
  const suggested = items.filter((card) => card.suggestions.length).length;

  return (
    <section
      aria-label="Karty z Compassa do połączenia"
      className="space-y-2 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Karty z Compassa do połączenia ({items.length})</h3>
          <p className="text-xs text-muted-foreground">
            Mapa już je liczy. Połączenie z kontraktem przenosi kartę do zakładki „Opieka”
            konsultanta. {suggested ? `Z propozycją: ${suggested}.` : null}
          </p>
        </div>
        <Button variant="outline" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "Zwiń" : "Pokaż karty"}
        </Button>
      </div>
      {open ? (
        <ul className="max-h-[40dvh] divide-y divide-border/60 overflow-y-auto text-sm">
          {items.map((card) => (
            <li key={card.id} className="flex flex-wrap items-start justify-between gap-2 py-2">
              <div className="min-w-0">
                <span className="font-medium">{card.person_name ?? "Bez nazwiska"}</span>
                <span className={CALM_SUBLINE}>
                  {[
                    formatIsoDatePl(card.interview_on),
                    card.area,
                    card.author,
                    card.is_draft ? "szkic" : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                {card.skills.length || card.unrecognized_skills.length ? (
                  <span className={cn(CALM_SUBLINE, "line-clamp-1")}>
                    {[...card.skills, ...card.unrecognized_skills].join(", ")}
                  </span>
                ) : null}
                <span className={CALM_SUBLINE}>
                  {card.suggestions.length
                    ? `Propozycja: ${contractLabel(card.suggestions[0])}${
                        card.suggestions.length > 1 ? ` (+${card.suggestions.length - 1})` : ""
                      }`
                    : "Brak kontraktu z tym nazwiskiem u klienta"}
                </span>
              </div>
              {canLink ? (
                <Button variant="ghost" size="sm" onClick={() => setLinking(card)}>
                  Połącz…
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {linking ? (
        <LinkDialog
          clientId={clientId}
          card={linking}
          contracts={contracts}
          onClose={() => setLinking(null)}
        />
      ) : null}
    </section>
  );
}
