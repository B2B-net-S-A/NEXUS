"use client";

// Koszty integracji konsultanta na koszt B2B (roadmapa E5.1, reguła `cl.integration_costs`):
// Finanse wpisują koszt przy osobie i miesiącu, DL klienta go przyjmuje albo odrzuca.
// Przyjęty koszt obniża marżę miesiąca; limit liczy się na rok kalendarzowy.
import { useState } from "react";

import { StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAddIntegrationCost,
  useIntegrationCosts,
  useWithdrawIntegrationCost,
} from "@/lib/api/client-settlements";

import { INTEGRATION_STATUS, integrationUsageText, monthLabel, pln } from "./format";

interface IntegrationCostsSectionProps {
  contractId: number;
  month: string;
  canWrite: boolean;
}

export function IntegrationCostsSection({ contractId, month, canWrite }: IntegrationCostsSectionProps) {
  const query = useIntegrationCosts(contractId, month);
  const add = useAddIntegrationCost(contractId, month);
  const withdraw = useWithdrawIntegrationCost(contractId, month);
  const { showSuccess, showError } = useToast();
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");

  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-destructive">
        {apiErrorMessage(query.error, "Nie udało się pobrać kosztów integracji.")}
      </p>
    );
  }
  if (!query.isSuccess || !query.data.enabled) return null;
  const card = query.data;
  const value = amount.trim().replace(/\s/g, "").replace(",", ".");
  const valid = value !== "" && Number(value) > 0 && description.trim().length >= 3;

  async function onAdd() {
    try {
      await add.mutateAsync({ amount: value, description: description.trim() });
      setAmount("");
      setDescription("");
      showSuccess("Koszt zapisany. Czeka na zgodę DL-a klienta.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać kosztu."));
    }
  }

  async function onWithdraw(costId: number) {
    try {
      await withdraw.mutateAsync(costId);
      showSuccess("Koszt cofnięty.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się cofnąć kosztu."));
    }
  }

  return (
    <section className="rounded-xl border bg-card p-3">
      <h3 className="text-sm font-semibold">Koszty integracji</h3>
      <p className="text-xs text-muted-foreground">
        Na koszt B2B, klient ich nie zwraca. Zgodę daje DL klienta; przyjęty koszt obniża marżę miesiąca.
      </p>
      <p className="mt-1 text-xs font-medium tabular-nums">{integrationUsageText(card.usage)}</p>
      {card.items.length > 0 ? (
        <ul className="mt-1 divide-y text-[13px]">
          {card.items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 py-1.5">
              <span className="min-w-0 flex-1 truncate">
                {monthLabel(item.month)} · {item.description}
              </span>
              <span className="tabular-nums">{pln(item.amount)}</span>
              <StatusDot tone={INTEGRATION_STATUS[item.status].tone}>{INTEGRATION_STATUS[item.status].label}</StatusDot>
              {canWrite && item.status === "pending" ? (
                <Button size="sm" variant="ghost" disabled={withdraw.isPending} onClick={() => onWithdraw(item.id)}>
                  Cofnij
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {canWrite ? (
        <div className="mt-2 flex flex-wrap items-end gap-2 text-xs">
          <label className="grid gap-0.5">
            <span className="text-muted-foreground">Kwota (zł)</span>
            <Input
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="h-8 w-28 text-sm tabular-nums"
            />
          </label>
          <label className="grid min-w-0 flex-1 gap-0.5">
            <span className="text-muted-foreground">Czego dotyczy</span>
            <Input
              value={description}
              maxLength={300}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="np. faktura za wyjście zespołu"
              className="h-8 text-sm"
            />
          </label>
          <Button size="sm" variant="outline" disabled={!valid || add.isPending} onClick={onAdd}>
            Dodaj koszt za {monthLabel(month)}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
