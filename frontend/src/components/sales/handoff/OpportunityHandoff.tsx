"use client";

import { useState } from "react";

import { useOpportunityHandoff } from "@/lib/api/sales-handoffs";
import { hasRole, useAuthStore } from "@/store/auth";

import { BookMeetingDialog } from "./BookMeetingForm";
import { HandoffCard, type HandoffPanel } from "./HandoffCard";

/**
 * Przekazanie spotkania na karcie szansy: te same odpowiedzi, termin i werdykt co
 * w „Mój dzień”, żeby prowadzący nie musiał wracać do kolejki. Szansa bez przekazania,
 * wczytywanie i błąd nic nie pokazują: to dodatek do karty, nie jej warunek.
 */
export function OpportunityHandoff({ opportunityId, canEdit }: { opportunityId: number; canEdit: boolean }) {
  const query = useOpportunityHandoff(opportunityId);
  const user = useAuthStore((state) => state.user);
  const [panel, setPanel] = useState<HandoffPanel>(null);
  const [rebooking, setRebooking] = useState(false);
  const handoff = query.data;
  if (!handoff) return null;
  const leads = handoff.host?.id === user?.id || hasRole(user, "admin");
  return (
    <>
      <HandoffCard
        handoff={handoff}
        viewer={leads ? "host" : "booker"}
        canEdit={canEdit && (leads || handoff.booked_by?.id === user?.id)}
        panel={panel}
        onPanel={setPanel}
        onVerdict={() => setPanel(null)}
        onRebook={() => setRebooking(true)}
        embedded
      />
      {rebooking && (
        <BookMeetingDialog
          opportunity={{ id: handoff.opportunity.id, name: handoff.opportunity.name, company: handoff.company }}
          handoff={handoff}
          onClose={() => setRebooking(false)}
        />
      )}
    </>
  );
}
