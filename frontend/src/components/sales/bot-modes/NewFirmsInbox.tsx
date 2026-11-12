"use client";

import { Building2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import { useLatestSignalRun } from "@/lib/api/sales";
import {
  newFirmPayload,
  useAcceptBotResult,
  useBotResults,
  useRejectBotResult,
  type BotResult,
} from "@/lib/api/sales-bot-results";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { Block, BotConclusion, INBOX_LAYOUT, InboxRow, NotNow, Panel, RunLine, SourceLink } from "./kit";

export type NewFirmsFilter = "open" | "accepted" | "rejected";

const FILTERS: { value: NewFirmsFilter; label: string }[] = [
  { value: "open", label: "Do decyzji" },
  { value: "accepted", label: "Założone" },
  { value: "rejected", label: "Odrzucone" },
];

const EMPTY: Record<NewFirmsFilter, string> = {
  open: "Bot nie znalazł nowych centrów IT do sprawdzenia.",
  accepted: "Nie założono jeszcze żadnego konta z tej listy.",
  rejected: "Nic jeszcze nie odrzucono.",
};

export function groupNewFirms(items: readonly BotResult[]): Record<NewFirmsFilter, BotResult[]> {
  return {
    open: items.filter((item) => item.status === "new" || item.status === "partial"),
    accepted: items.filter((item) => item.status === "accepted"),
    rejected: items.filter((item) => item.status === "rejected"),
  };
}

/** „W NEXUSIE”: czy jest karta, kto jest opiekunem i czy pracuje w Sprzedaży. */
export function inBaseLine(item: BotResult): string {
  if (!item.company) return "Firmy nie ma w kartotece Sprzedaży.";
  const card = `Karta ${item.company.name} jest w kartotece`;
  if (!item.owner) return `${card}, bez opiekuna.`;
  if (!item.owner_in_sales) return `${card}; jej opiekun nie pracuje już w Sprzedaży.`;
  return `${card}, opiekun ${item.owner.name}.`;
}

function NewFirmActions({ item, reasons }: { item: BotResult; reasons?: readonly string[] }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const accept = useAcceptBotResult();
  const reject = useRejectBotResult();
  const { showError, showSuccess } = useToast();
  if (!canEdit) return null;
  if (item.status === "accepted") {
    return (
      <p className="text-xs text-muted-foreground">
        Konto założone.{" "}
        {item.company && (
          <Link href={`/sales/companies/${item.company.id}`} className="text-primary hover:underline">
            Karta firmy
          </Link>
        )}
      </p>
    );
  }
  if (item.status === "rejected") {
    return <p className="text-xs text-muted-foreground">Odrzucone.</p>;
  }
  return (
    <div className="flex flex-wrap gap-2" data-tour="sales.leads.new-firms.actions">
      <Button
        size="sm"
        loading={accept.isPending}
        onClick={() =>
          accept.mutate(item.id, {
            onSuccess: (outcome) => {
              showSuccess(
                outcome.existed ? "Ta firma ma już konto w Fabrykach IT." : "Założono konto w Fabrykach IT.",
              );
              router.push(`/sales/opportunities/${outcome.opportunity_id}`);
            },
            onError: (error) => showError(apiErrorMessage(error, "Nie udało się założyć konta.")),
          })
        }
      >
        Załóż konto w Fabrykach IT
      </Button>
      <NotNow
        reasons={reasons}
        pending={reject.isPending}
        onReject={(reason) =>
          reject.mutate(
            { id: item.id, reason },
            {
              onSuccess: () => showSuccess("Odrzucono."),
              onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać decyzji.")),
            },
          )
        }
      />
    </div>
  );
}

function NewFirmPanel({ item, reasons }: { item: BotResult; reasons?: readonly string[] }) {
  const firm = newFirmPayload(item);
  return (
    <Panel>
      <div className="space-y-0.5">
        <p className="text-xs text-muted-foreground">
          {[firm.city, firm.published ? formatIsoDatePl(firm.published) : null].filter(Boolean).join(" · ")}
        </p>
        <p className="text-sm font-semibold text-foreground">{firm.company}</p>
        <p className="text-sm text-foreground">{firm.what}</p>
      </div>
      {firm.scale && (
        <Block label="Skala">
          <p className="text-xs text-muted-foreground">{firm.scale}</p>
        </Block>
      )}
      {firm.why && (
        <Block label={<BotConclusion>Dlaczego konto dla Fabryk IT</BotConclusion>}>
          <p className="text-xs text-muted-foreground">{firm.why}</p>
        </Block>
      )}
      <Block label="W NEXUSIE">
        <p className="text-xs text-muted-foreground">{inBaseLine(item)}</p>
      </Block>
      <SourceLink url={firm.url} />
      <NewFirmActions item={item} reasons={reasons} />
    </Panel>
  );
}

/** G-D „Nowe centra IT”: zapowiedzi nowych i rosnących centrów w Polsce jako kandydaci na konta. */
export function NewFirmsInbox() {
  const [filter, setFilter] = useState<NewFirmsFilter>("open");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const latest = useLatestSignalRun("discovery");
  const query = useBotResults({ kind: "discovery" });
  const groups = useMemo(() => groupNewFirms(query.data?.items ?? []), [query.data]);
  const items = groups[filter];
  const selected = items.find((item) => item.id === selectedId) ?? items[0];
  const run = latest.data?.run ?? null;
  const reasons = latest.data?.reject_reasons?.length ? latest.data.reject_reasons : undefined;
  // Wyłączony kanał to nie pusta lista: mówimy to wprost.
  const disabled = query.isSuccess && query.data?.enabled === false;
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: items.length === 0,
  });
  const report = (run?.report ?? {}) as { results?: number; in_base?: number };

  return (
    <div className="space-y-2">
      <RunLine>
        {latest.isError ? (
          "Nie udało się pobrać raportu bota."
        ) : run ? (
          <>
            <span className="font-medium text-foreground">Nowe centra IT w Polsce, {formatIsoDatePl(run.started_at)}:</span>{" "}
            {run.status === "received"
              ? `${report.results ?? 0} zapowiedzi z ostatnich 6 miesięcy; ${report.in_base ?? 0} firm jest już w kartotece.`
              : run.status === "started"
                ? "bot jeszcze szuka."
                : "bieg nie dostał raportu od bota."}
          </>
        ) : latest.isSuccess ? (
          "Bot szuka nowych centrów raz w miesiącu, w pierwszy poniedziałek. Pierwszego biegu jeszcze nie było."
        ) : null}
      </RunLine>
      {disabled ? (
        <p className="py-6 text-sm text-muted-foreground">Zadania bota są wyłączone.</p>
      ) : (
        <>
          <SegmentedRadio
            size="sm"
            label="Filtr: nowe centra IT"
            options={FILTERS.map(({ value, label }) => ({
              value,
              label: query.isSuccess ? `${label} (${groups[value].length})` : label,
            }))}
            value={filter}
            onChange={setFilter}
          />
          {state === "loading" ? (
            <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>
          ) : state === "forbidden" || state === "not_found" || state === "error" ? (
            <QueryStateNotice
              state={state}
              description="Nie udało się pobrać listy. Pozycje mogą istnieć, spróbuj ponownie za chwilę."
              onRetry={() => void query.refetch()}
            />
          ) : (
            <div className={INBOX_LAYOUT}>
              <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
                {state === "empty" ? (
                  <EmptyState icon={Building2} title="Pusto" description={EMPTY[filter]} />
                ) : (
                  <ul className="divide-y divide-border">
                    {items.map((item) => {
                      const firm = newFirmPayload(item);
                      return (
                        <InboxRow
                          key={item.id}
                          selected={item.id === selected?.id}
                          onSelect={() => setSelectedId(item.id)}
                          title={
                            <>
                              <span className="font-medium">{firm.company}</span>{" "}
                              <span className="text-muted-foreground">{firm.what}</span>
                            </>
                          }
                          sub={[
                            firm.city || null,
                            firm.scale || null,
                            item.company ? `karta ${item.company.name}` : "nie ma w kartotece",
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                          right={firm.published ? formatIsoDatePl(firm.published) : ""}
                        />
                      );
                    })}
                  </ul>
                )}
              </div>
              {selected && <NewFirmPanel key={selected.id} item={selected} reasons={reasons} />}
            </div>
          )}
        </>
      )}
    </div>
  );
}
