"use client";

// „Błędy i uwagi” (makiety 24.11.2026): powody pogrupowane po tym, co znaczą dla
// przyjęcia — błąd blokuje, uwagę Finanse mogą przyjąć, plik nieodczytany wymaga
// wpisania MD, zamówienie bez MD rozstrzyga opiekun. Jedna tabela zamiast kafelków.

import Link from "next/link";

import { StatusDot } from "@/components/ds/StatusDot";
import type { MonthCloseReason, MonthCloseReasonLevel } from "@/lib/api/client-settlements";

import { monthLabel } from "../settlements/format";
import { LEVEL_LOOK, STEP_DOT } from "./month-model";
import { reasonPlan } from "./reason-plan";

const ORDER: MonthCloseReasonLevel[] = ["fail", "warn", "order", "unread", "returned", "missing"];

/** Powód bez `level` (starsze API): brak raportu, plik bez MD, reszta jako uwaga. */
export function levelOf(r: MonthCloseReason): MonthCloseReasonLevel {
  if (r.level) return r.level;
  if (r.key === "missing") return "missing";
  if (r.key === "no_md") return "unread";
  return "warn";
}

interface IssuesByLevelProps {
  reasons: MonthCloseReason[];
  month: string;
  clientHref: (clientId: number, extra?: Record<string, string>) => string;
}

export function IssuesByLevel({ reasons, month, clientHref }: IssuesByLevelProps) {
  if (reasons.length === 0) {
    return (
      <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
        W {monthLabel(month)} nic nie czeka na decyzję.
      </p>
    );
  }
  const groups = ORDER.map((level) => ({
    level,
    items: reasons.filter((r) => levelOf(r) === level),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="relative overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[880px] table-fixed text-[13px]">
        <colgroup>
          <col className="w-[31%]" />
          <col className="w-[6%]" />
          <col className="w-[24%]" />
          <col className="w-[23%]" />
          <col className="w-[16%]" />
        </colgroup>
        <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 font-medium">Powód</th>
            <th className="px-2 py-1.5 text-right font-medium">Osób</th>
            <th className="px-2 py-1.5 font-medium">U kogo</th>
            <th className="px-2 py-1.5 font-medium">Kto rozstrzyga</th>
            <th className="px-3 py-1.5 font-medium">
              <span className="sr-only">Akcja</span>
            </th>
          </tr>
        </thead>
        {groups.map(({ level, items }) => {
          const look = LEVEL_LOOK[level];
          const total = items.reduce((acc, r) => acc + r.count, 0);
          return (
            <tbody key={level} className="divide-y border-t">
              <tr className="bg-muted/25">
                <td colSpan={5} className="px-3 py-1.5">
                  <StatusDot tone={STEP_DOT[look.tone]}>
                    {look.label} <span className="tabular-nums text-muted-foreground">· {total} os.</span>
                    <span className="font-normal text-muted-foreground"> — {look.hint}</span>
                  </StatusDot>
                </td>
              </tr>
              {items.map((r) => {
                const plan = reasonPlan(r.key);
                const first = r.clients[0];
                return (
                  <tr key={`${r.key}-${level}`} className="hover:bg-muted/30">
                    <td className="px-3 py-1.5 pl-7" title={r.title}>
                      <span className="block truncate">{r.title}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {r.people.slice(0, 3).map((p, i) => (
                          <span key={p.contract_id}>
                            {i ? ", " : ""}
                            <Link href={clientHref(p.client_id, { stContract: String(p.contract_id) })} className="hover:text-foreground hover:underline">
                              {p.person}
                            </Link>
                          </span>
                        ))}
                        {r.count > 3 ? ` i ${r.count - 3} innych` : ""}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right font-medium tabular-nums">{r.count}</td>
                    <td className="truncate px-2 py-1.5 text-[12px] text-muted-foreground">
                      {r.clients.slice(0, 3).map((c, i) => (
                        <span key={c.client_id}>
                          {i ? " · " : ""}
                          <span className="text-foreground">{c.name}</span> {c.count}
                        </span>
                      ))}
                      {r.clients.length > 3 ? ` · +${r.clients.length - 3}` : ""}
                    </td>
                    <td className="truncate px-2 py-1.5 text-[12px]">{plan.who}</td>
                    <td className="truncate px-3 py-1.5 text-right">
                      {first ? (
                        <Link
                          href={clientHref(first.client_id, plan.sub === "rules" ? { stSub: "rules" } : {})}
                          className="text-xs font-medium text-primary hover:underline"
                        >
                          {plan.action}
                        </Link>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}
