"use client";

import { useId, useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  useChart,
  useRevenueChoices,
  useSetRevenueChoice,
  type RevenueBuyer,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

/** Konta, na które FVS może zaksięgować przychód: aktywne, bez kont pod sobą i bez słownika. */
function useRevenueAccounts(enabled: boolean) {
  const chart = useChart(enabled);
  return useMemo(
    () => (chart.data ?? []).filter((account) => account.active && account.postable && !account.dictionary),
    [chart.data],
  );
}

/** „dd.mm.rrrr” z daty ISO; puste, gdy daty nie ma. */
export function choiceDay(at: string | null): string {
  if (!at) return "";
  const day = new Date(at);
  if (Number.isNaN(day.getTime())) return "";
  return day.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Warsaw" });
}

/**
 * Wskazanie konta przychodu na problemie „brak historii” w Źródłach (decyzja
 * Artura z 18.11.2026). Konto zapisuje się dla nabywcy, a liczy się dopiero
 * wtedy, gdy nabywca nie ma dekretu w archiwum eBI24 ani zatwierdzonej FVS —
 * potem regułę przejmuje poprzednia faktura nabywcy.
 */
export function RevenueChoiceForm({ buyer, canEdit }: { buyer: RevenueBuyer; canEdit: boolean }) {
  const { showToast } = useToast();
  const save = useSetRevenueChoice();
  const accounts = useRevenueAccounts(canEdit);
  const listId = useId();
  const [account, setAccount] = useState(buyer.account ?? "");

  if (!canEdit) {
    return (
      <span className="mt-1 block text-[12px] text-muted-foreground">
        Konto przychodu dla nabywcy wskazuje osoba z listy „Księgowi”.
      </span>
    );
  }
  const submit = () =>
    save.mutate(
      { counterpartyId: buyer.counterparty_id, account: account.trim() },
      {
        onSuccess: (result) =>
          showToast(
            `Konto ${result.account} zapisane dla nabywcy ${buyer.name}. „Zaksięguj miesiąc” zrobi FVS.`,
            "success",
          ),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać konta przychodu."), "error"),
      },
    );
  return (
    <form
      className="mt-1.5 flex flex-wrap items-center gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <datalist id={listId}>
        {accounts.map((item) => (
          <option key={item.id} value={item.number}>
            {item.name}
          </option>
        ))}
      </datalist>
      <input
        aria-label={`Konto przychodu dla nabywcy ${buyer.name}`}
        className={cn(CONTROL, "w-32 font-mono text-[13px]")}
        list={listId}
        value={account}
        placeholder="np. 701-12-1"
        onChange={(event) => setAccount(event.target.value)}
      />
      <Button type="submit" size="sm" variant="outline" disabled={!account.trim() || save.isPending}>
        {save.isPending ? "Zapisywanie…" : "Zapisz dla nabywcy"}
      </Button>
    </form>
  );
}

/** Lista wskazanych kont przychodu w Ustawieniach: podgląd i zdjęcie wskazania. */
export function RevenueChoicesCard() {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const choices = useRevenueChoices();
  const save = useSetRevenueChoice();
  const canEdit = config.me.approver;
  const title = "Konta przychodu nabywców bez historii";

  if (choices.isError) {
    return (
      <SectionCard title={title}>
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => choices.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!choices.isSuccess) return null;
  const remove = (counterpartyId: number, name: string) =>
    save.mutate(
      { counterpartyId, account: "" },
      {
        onSuccess: () => showToast(`Zdjęto wskazanie konta przychodu dla ${name}.`, "success"),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zdjąć wskazania."), "error"),
      },
    );
  return (
    <SectionCard title={title} aside="wskazuje się w Źródłach">
      <p className="px-3.5 pt-2.5 text-[12px] text-muted-foreground">
        Konto działa tylko wtedy, gdy nabywca nie ma dekretu w Symfonii (archiwum eBI24) ani zatwierdzonej FVS. Po
        pierwszej zatwierdzonej FVS przychód idzie jak poprzednia faktura nabywcy.
      </p>
      {choices.data.length ? (
        <ul className="mt-1.5 divide-y divide-border/70 border-t border-border/70">
          {choices.data.map((item) => {
            const name = item.name ?? `kontrahent ${item.counterparty_id}`;
            const who = [item.by, choiceDay(item.at)].filter(Boolean).join(", ");
            return (
              <li key={item.counterparty_id} className="flex items-center gap-2 px-3.5 py-1.5 text-[13px]">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium" title={name}>
                    {name}
                  </span>
                  <span className="block truncate text-[12px] text-muted-foreground">
                    {item.id_value ? `${item.id_type?.toUpperCase() ?? ""} ${item.id_value}` : "spoza kartoteki"}
                    {who ? ` · ${who}` : ""}
                  </span>
                  {item.problem ? (
                    <span className="block text-[12px] text-warning-muted-foreground">Plan kont: {item.problem}</span>
                  ) : null}
                </span>
                <span className="shrink-0 font-mono text-[13px]">{item.account}</span>
                {canEdit ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={save.isPending}
                    onClick={() => remove(item.counterparty_id, name)}
                  >
                    Usuń
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-3.5 py-2.5 text-[13px] text-muted-foreground">
          Nie ma wskazanych kont. Nabywca bez historii czeka w Źródłach na „Zapisz dla nabywcy”.
        </p>
      )}
    </SectionCard>
  );
}
