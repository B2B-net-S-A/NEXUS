"use client";

import { useState } from "react";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { Handoff, Handoffs, HandoffVerdict } from "@/lib/api/sales-handoffs";

import { PlanPanel } from "../MyDayRowPanels";
import { BookMeetingDialog } from "./BookMeetingForm";
import { HandoffCard, type HandoffPanel } from "./HandoffCard";
import { BookedByMeSection, HandedToMeSection } from "./HandoffSections";
import { planRow } from "./helpers";

interface Selection {
  id: number;
  panel: HandoffPanel;
}

/** Przekazanie, które prosi o ruch teraz: werdykt albo potwierdzenie terminu. */
function needsAction(handoffs: Handoffs): Handoff | undefined {
  return handoffs.to_me.find((row) => row.phase === "verdict" || row.phase === "confirm");
}

/**
 * Stan wyboru dla sekcji przekazań w „Mój dzień”: lewa kolumna pokazuje listy,
 * prawa kartę wybranego spotkania. Bez wyboru prawa kolumna zostaje przy
 * przygotowaniu do najbliższego spotkania z kalendarza.
 */
export function useMyDayHandoffs(handoffs: Handoffs | undefined, canEdit: boolean, hasPrep: boolean) {
  const [selection, setSelection] = useState<Selection | null | undefined>(undefined);
  const [followUp, setFollowUp] = useState<Handoff | null>(null);
  const [rebooking, setRebooking] = useState<Handoff | null>(null);
  const all = handoffs ? [...handoffs.to_me, ...handoffs.booked_by_me] : [];
  // Dopóki nikt nie kliknął, karta otwiera się sama tam, gdzie jest coś do zrobienia.
  const automatic = handoffs ? (needsAction(handoffs) ?? (hasPrep ? undefined : handoffs.to_me[0])) : undefined;
  const current = selection === undefined ? (automatic ? { id: automatic.opportunity.id, panel: null } : null) : selection;
  const selected = current ? all.find((row) => row.opportunity.id === current.id) : undefined;
  const viewer = selected && handoffs?.to_me.includes(selected) ? "host" : "booker";

  const open = (handoff: Handoff, panel: HandoffPanel) => {
    setFollowUp(null);
    setSelection({ id: handoff.opportunity.id, panel });
  };
  const onVerdict = (handoff: Handoff, kind: HandoffVerdict) => {
    setSelection(null);
    // Po kwalifikacji od razu krok: bez niego szansa wraca na listę „bez kroku”.
    setFollowUp(kind === "qualified" ? handoff : null);
  };

  const sections = handoffs ? (
    <>
      <HandedToMeSection rows={handoffs.to_me} selectedId={selected?.opportunity.id ?? null} canEdit={canEdit} onOpen={open} />
      <BookedByMeSection
        rows={handoffs.booked_by_me}
        weeks={handoffs.weeks}
        selectedId={selected?.opportunity.id ?? null}
        canEdit={canEdit}
        onOpen={open}
        onRebook={setRebooking}
      />
    </>
  ) : null;

  const card = followUp ? (
    <Card className="space-y-2 p-4" data-testid="handoff-follow-up">
      <p className="text-xs text-muted-foreground">Kwalifikuje się · Lead kwalifikowany</p>
      <h2 className="truncate text-base font-semibold text-foreground">{followUp.company.name}</h2>
      <div className="overflow-hidden rounded-md border border-border">
        <PlanPanel row={planRow(followUp)} onDone={() => setFollowUp(null)} />
      </div>
      <div className="flex justify-end">
        <Button size="sm" variant="ghost" onClick={() => setFollowUp(null)}>
          Bez kroku
        </Button>
      </div>
    </Card>
  ) : selected && current ? (
    <HandoffCard
      key={selected.opportunity.id}
      handoff={selected}
      viewer={viewer}
      canEdit={canEdit}
      panel={current.panel}
      onPanel={(panel) => setSelection({ id: selected.opportunity.id, panel })}
      onVerdict={(kind) => onVerdict(selected, kind)}
      onRebook={() => setRebooking(selected)}
    />
  ) : null;

  const dialog = rebooking ? (
    <BookMeetingDialog
      opportunity={{ id: rebooking.opportunity.id, name: rebooking.opportunity.name, company: rebooking.company }}
      handoff={rebooking}
      onClose={() => setRebooking(null)}
    />
  ) : null;

  return { sections, card, dialog, count: all.length };
}
