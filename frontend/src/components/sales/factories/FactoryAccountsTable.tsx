"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { StatusDot } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Opportunity } from "@/lib/api/sales";
import type { FactoryAccount, KnownCounts } from "@/lib/api/sales-factories";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";

import { daysLabel, daysSince } from "../format";
import { stepLabel, stepTone } from "../step";

import { ClientHandoff } from "./ClientHandoff";
import { peopleLabel, stageHint, STAGE_HINT_TITLE } from "./factories";

/** Stan liczników „Kogo znamy”: skan trwa sekundy i może się nie udać. */
export type KnownState = "loading" | "error" | "ready";

interface FactoryAccountsTableProps {
  items: readonly Opportunity[];
  /** `null`: liczniki map się nie wczytały; wiersze zostają, liczby nie. */
  accounts: ReadonlyMap<number, FactoryAccount> | null;
  known: ReadonlyMap<number, KnownCounts>;
  knownState: KnownState;
}

function Coverage({ done, total }: { done: number; total: number }) {
  if (total === 0) return <span className="whitespace-nowrap text-xs text-muted-foreground">brak osób na mapie</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 shrink-0 rounded-full bg-muted" aria-hidden>
        <div className="h-1.5 rounded-full bg-primary" style={{ width: `${Math.round((done / total) * 100)}%` }} />
      </div>
      <span className="whitespace-nowrap text-xs tabular-nums text-foreground">
        {done} z {total}
      </span>
    </div>
  );
}

function KnownCell({ value, state }: { value: number | undefined; state: KnownState }) {
  if (state === "loading") return <span className={CALM_EMPTY}>…</span>;
  if (state === "error" || value === undefined) return <span className={CALM_EMPTY}>—</span>;
  return <>{value}</>;
}

/**
 * Lista kont lejka Fabryki IT: obok etapu (który opisuje research) widać, ile osób
 * z mapy ma kontakt za sobą i ilu ludzi z bazy kandydatów pracuje w firmie.
 */
export function FactoryAccountsTable({ items, accounts, known, knownState }: FactoryAccountsTableProps) {
  const router = useRouter();
  return (
    <div className="relative overflow-x-auto">
      <Table className="min-w-[940px]">
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} sticky left-0 min-w-[18rem] bg-background`}>Konto</TableHead>
            <TableHead className={CALM_HEAD}>Opiekun</TableHead>
            <TableHead className={CALM_HEAD}>Mapa po kontakcie</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Znamy teraz</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Kiedyś</TableHead>
            <TableHead className={CALM_HEAD}>Ostatni ruch</TableHead>
            <TableHead className={CALM_HEAD}>Co dalej</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const account = accounts?.get(item.id);
            const counts = known.get(item.company.id);
            const hint = stageHint(account);
            const idle = daysSince(item.last_touch_at);
            const peopleHref = `/sales/companies/${item.company.id}?tab=people`;
            return (
              <TableRow
                key={item.id}
                className={`${CALM_ROW} cursor-pointer`}
                onClick={() => router.push(`/sales/opportunities/${item.id}`)}
              >
                <TableCell className="sticky left-0 bg-card py-1.5">
                  <span className="flex flex-wrap items-center gap-x-1.5">
                    <Link
                      href={`/sales/opportunities/${item.id}`}
                      title={item.title}
                      className="font-medium text-foreground hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {item.company.name}
                    </Link>
                    {account?.client && (
                      <Badge variant="info" size="sm">
                        Klient NEXUSA
                      </Badge>
                    )}
                  </span>
                  <p className={CALM_SUBLINE}>
                    {item.stage.name}
                    {hint && (
                      <span className="text-warning" title={STAGE_HINT_TITLE}>
                        {" "}
                        · {hint}
                      </span>
                    )}
                  </p>
                </TableCell>
                <TableCell className="whitespace-nowrap py-1.5 text-sm text-muted-foreground">
                  {item.owner?.name ?? "—"}
                </TableCell>
                <TableCell className="py-1.5">
                  {account ? (
                    <Coverage done={account.map_contacted} total={account.map_total} />
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </TableCell>
                <TableCell className={`${CALM_AMOUNT} py-1.5 font-medium text-foreground`}>
                  {knownState === "ready" && counts && counts.current > 0 ? (
                    <Link
                      href={peopleHref}
                      aria-label={`Kto ich zna: ${item.company.name}`}
                      title="Kto ich zna: osoby z bazy na karcie firmy"
                      className="text-primary hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {counts.current}
                    </Link>
                  ) : (
                    <KnownCell value={counts?.current} state={knownState} />
                  )}
                </TableCell>
                <TableCell className={`${CALM_AMOUNT} py-1.5 text-muted-foreground`}>
                  <KnownCell value={counts?.past} state={knownState} />
                </TableCell>
                <TableCell className="whitespace-nowrap py-1.5 text-sm tabular-nums">
                  {formatIsoDatePl(item.last_touch_at)}
                  {idle !== null && <span className={CALM_SUBLINE}>{idle === 0 ? "dziś" : `${daysLabel(idle)} temu`}</span>}
                </TableCell>
                <TableCell className="whitespace-nowrap py-1.5 text-sm">
                  {account?.client ? (
                    <ClientHandoff client={account.client} />
                  ) : (
                    <StatusDot tone={stepTone(item)}>{stepLabel(item)}</StatusDot>
                  )}
                  {account && account.waiting > 0 && (
                    <span className={CALM_SUBLINE} title="Osoby z poziomu 1 i 2 bez kontaktu">
                      w kolejce: {peopleLabel(account.waiting)}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
