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

import { decisionCards, decisionCount, type DecisionCard } from "./team-week";

const BADGE: Record<DecisionCard["kind"], string> = {
  leave: "bg-info-muted text-info-muted-foreground",
  timesheet: "bg-muted text-foreground",
  bonus: "bg-warning-muted text-warning-muted-foreground",
};

/**
 * „Do Twojej decyzji” (decyzja Artura 19.10.2026): wniosek i timesheet
 * akceptuje się tutaj — te same hooki i trasy co „Ludzie → Akceptacje”
 * (`useDecideLeave`, `useDecideTimesheet`), odrzucenie przez
 * `RejectLeaveDialog`. Propozycje premii tylko do wiadomości — decydują Płace.
 * O prawie do decyzji rozstrzyga serwer (odmowa = komunikat z `apiErrorMessage`).
 */
export function TeamDecisions({ team }: { team: MyTeam }) {
  const cards = decisionCards(team);
  const decideLeave = useDecideLeave();
  const decideTimesheet = useDecideTimesheet();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [rejecting, setRejecting] = useState<RejectTarget | null>(null);

  if (cards.length === 0) return null;
  const count = decisionCount(cards);

  const approveLeave = (card: Extract<DecisionCard, { kind: "leave" }>) =>
    decideLeave.mutate(
      { id: card.item.id, decision: "approve" },
      {
        onSuccess: (saved) => showToast(...leaveToast("Wniosek zaakceptowany", saved)),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error"),
      },
    );

  const approveTimesheet = async (card: Extract<DecisionCard, { kind: "timesheet" }>) => {
    const ok = await askConfirm({
      title: `Zaakceptować timesheet: ${card.person.name}?`,
      description: `${monthTitlePl(card.item)}${
        card.hoursText ? ` · ${card.hoursText}` : ""
      }. Po akceptacji powstaje PDF z sumą kontrolną.`,
      confirmLabel: "Akceptuj",
    });
    if (!ok) return;
    decideTimesheet.mutate(
      { id: card.item.id, decision: "approve" },
      {
        onSuccess: () => showToast("Timesheet zaakceptowany", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error"),
      },
    );
  };

  const busy = decideLeave.isPending || decideTimesheet.isPending;
  return (
    <section aria-labelledby="team-decisions-title" className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 id="team-decisions-title" className="text-sm font-semibold text-foreground">
          Do Twojej decyzji
        </h2>
        {count > 0 ? (
          <span className="rounded-full bg-primary px-2 py-px text-[11px] font-semibold text-primary-foreground">
            {count}
          </span>
        ) : null}
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <li
            key={card.key}
            className={cn(
              "flex flex-col gap-2.5 rounded-xl border border-border p-3.5",
              card.kind === "bonus" ? "bg-muted/30" : "bg-card",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span
                className={cn(
                  "whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
                  BADGE[card.kind],
                )}
              >
                {card.badge}
              </span>
              {"waited" in card && card.waited ? (
                <span className="text-xs text-muted-foreground">{card.waited}</span>
              ) : null}
            </div>
            <div className="min-w-0">
              <p className="truncate font-semibold text-foreground">{card.title}</p>
              <p className="text-[13px] text-muted-foreground">{card.detail}</p>
            </div>
            <div className="mt-auto flex flex-wrap gap-1.5">
              {card.kind === "leave" ? (
                <>
                  <Button size="sm" disabled={busy} onClick={() => approveLeave(card)}>
                    Akceptuj
                  </Button>
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
                  <Button size="sm" variant="ghost" asChild>
                    <Link href="/people/approvals">Szczegóły</Link>
                  </Button>
                </>
              ) : card.kind === "timesheet" ? (
                <>
                  <Button size="sm" disabled={busy} onClick={() => void approveTimesheet(card)}>
                    Akceptuj
                  </Button>
                  <Button size="sm" variant="outline" asChild>
                    <Link href={card.item.link}>Podgląd</Link>
                  </Button>
                </>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
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
