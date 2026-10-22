"use client";

import { useState } from "react";
import Link from "next/link";

import { RejectLeaveDialog, type RejectTarget } from "@/components/hr/leave/RejectLeaveDialog";
import { leaveToast } from "@/components/hr/leave/leave-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useDecideLeave } from "@/lib/api/hr-leave";
import type { MyTeam } from "@/lib/api/hr-team";
import { useDecideTimesheet } from "@/lib/api/hr-time";
import { monthTitlePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { VISIBLE_DECISIONS, decisionRows, type DecisionRow } from "./decision-rows";
import { decisionCount, type DecisionCard } from "./team-week";

const TAG: Record<DecisionCard["kind"], string> = {
  leave: "bg-info-muted text-info-muted-foreground",
  timesheet: "bg-muted text-foreground",
  bonus: "bg-warning-muted text-warning-muted-foreground",
};

const APPROVALS = "/people/approvals";

/**
 * „Do Twojej decyzji” (decyzja Artura 19.10.2026, wiersze 22.10.2026): wniosek
 * i raport godzin akceptuje się tutaj — te same hooki i trasy co „Ludzie →
 * Akceptacje” (`useDecideLeave`, `useDecideTimesheet`), odrzucenie przez
 * `RejectLeaveDialog`. Propozycje premii tylko do wiadomości — decydują Płace.
 * O prawie do decyzji rozstrzyga serwer (odmowa = komunikat z `apiErrorMessage`).
 * Toast idzie z obietnicy `mutateAsync`: po decyzji wiersz znika razem
 * z przyciskiem, a callbacki `mutate()` przepadają z odmontowaniem.
 */
export function TeamDecisions({ team }: { team: MyTeam }) {
  const rows = decisionRows(team);
  const decideLeave = useDecideLeave();
  const decideTimesheet = useDecideTimesheet();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [rejecting, setRejecting] = useState<RejectTarget | null>(null);

  if (rows.length === 0) {
    // Sprawa zniknęła przy otwartym oknie (ktoś inny zdecydował) — bez tego
    // okno odrzucenia samo wracało przy następnej sprawie (audyt 21.10.2026).
    if (rejecting !== null) setRejecting(null);
    return null;
  }
  const count = decisionCount(rows.map((row) => row.card));
  const visible = rows.slice(0, VISIBLE_DECISIONS);
  const hidden = rows.length - visible.length;

  const approveLeave = async (card: Extract<DecisionCard, { kind: "leave" }>) => {
    try {
      const saved = await decideLeave.mutateAsync({ id: card.item.id, decision: "approve" });
      showToast(...leaveToast("Wniosek zaakceptowany", saved));
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error");
    }
  };

  const approveTimesheet = async (card: Extract<DecisionCard, { kind: "timesheet" }>) => {
    const ok = await askConfirm({
      title: `Zaakceptować timesheet: ${card.person.name}?`,
      description: `${monthTitlePl(card.item)}${
        card.hoursText ? ` · ${card.hoursText}` : ""
      }. Po akceptacji powstaje PDF z sumą kontrolną.`,
      confirmLabel: "Akceptuj",
    });
    if (!ok) return;
    try {
      await decideTimesheet.mutateAsync({ id: card.item.id, decision: "approve" });
      showToast("Timesheet zaakceptowany", "success");
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error");
    }
  };

  const busy = decideLeave.isPending || decideTimesheet.isPending;

  const actions = (row: DecisionRow) => {
    const { card } = row;
    if (card.kind === "leave") {
      return (
        <>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() =>
              setRejecting({
                id: card.item.id,
                user_name: card.person.name,
                start_date: card.item.start_date,
                end_date: card.item.end_date,
              })
            }
          >
            Odrzuć
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void approveLeave(card)}>
            Akceptuj
          </Button>
        </>
      );
    }
    if (card.kind === "timesheet") {
      return (
        <>
          <Button size="sm" variant="outline" asChild>
            <Link href={card.item.link}>Podgląd</Link>
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void approveTimesheet(card)}>
            Akceptuj
          </Button>
        </>
      );
    }
    return null;
  };

  return (
    <section
      aria-labelledby="team-decisions-title"
      className="overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-3.5 py-2">
        <div className="flex items-baseline gap-1.5">
          <h2 id="team-decisions-title" className="text-sm font-semibold text-foreground">
            Do Twojej decyzji
          </h2>
          {count > 0 ? (
            <span className="text-sm font-semibold tabular-nums text-muted-foreground">
              · {count}
            </span>
          ) : null}
        </div>
        <Link href={APPROVALS} className="text-xs font-medium text-primary hover:underline">
          Wszystkie w Akceptacjach →
        </Link>
      </div>
      <ul className="divide-y divide-border/60">
        {visible.map((row) => (
          <li
            key={row.key}
            className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3.5 py-2"
          >
            <span
              className={cn(
                "w-[104px] shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-center text-[11px] font-medium",
                TAG[row.card.kind],
              )}
            >
              {row.tag}
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
              {row.card.kind === "leave" ? (
                <Link
                  href={APPROVALS}
                  title="Szczegóły w Akceptacjach"
                  className="truncate text-sm font-semibold text-foreground hover:underline"
                >
                  {row.name}
                </Link>
              ) : (
                <span className="truncate text-sm font-semibold text-foreground">{row.name}</span>
              )}
              <span className="text-[13px] text-muted-foreground">{row.summary}</span>
              {row.age ? (
                <span className="text-xs text-muted-foreground/80">{row.age}</span>
              ) : null}
            </div>
            {row.card.kind === "bonus" ? null : (
              <div className="ml-auto flex shrink-0 gap-1.5">{actions(row)}</div>
            )}
          </li>
        ))}
      </ul>
      {hidden > 0 ? (
        <Link
          href={APPROVALS}
          className="block border-t border-border/60 px-3.5 py-2 text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground"
        >
          {`i jeszcze ${hidden} — w Akceptacjach`}
        </Link>
      ) : null}
      <RejectLeaveDialog
        request={rejecting}
        onClose={(rejected) => {
          setRejecting(null);
          if (rejected) showToast("Wniosek odrzucony", "success");
        }}
      />
      {confirmDialog}
    </section>
  );
}
