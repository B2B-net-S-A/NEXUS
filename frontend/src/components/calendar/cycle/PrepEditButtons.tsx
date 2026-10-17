"use client";

import { usePrep } from "@/lib/api/prepMeetings";
import { cn } from "@/lib/utils";

/**
 * „Zmień” i „Odwołaj” przy zaplanowanym prepie — tylko dla ludzi pary
 * (`can_edit` z serwera: prowadzący, Delivery Lead rekrutacji, rekruter
 * kandydata, osoba planująca, HoR, admin). 17.10.2026, decyzja D2: do tej
 * daty zaplanowany prep nie miał w panelu osoby żadnej akcji.
 */
export function PrepEditButtons({
  eventId,
  onEdit,
  className,
}: {
  eventId: number;
  onEdit: (mode: "edit" | "cancel") => void;
  className?: string;
}) {
  const prep = usePrep(eventId);
  if (!prep.data?.can_edit || prep.data.status === "cancelled") return null;
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <button
        type="button"
        onClick={() => onEdit("edit")}
        className="h-8 rounded-md border border-border bg-card px-2.5 text-xs font-semibold hover:bg-muted"
      >
        Zmień
      </button>
      <button
        type="button"
        onClick={() => onEdit("cancel")}
        className="h-8 rounded-md px-2 text-xs font-semibold text-destructive hover:bg-destructive/10"
      >
        Odwołaj
      </button>
    </span>
  );
}
