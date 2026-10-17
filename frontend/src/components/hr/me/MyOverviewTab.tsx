"use client";

import { useState } from "react";
import { CalendarPlus, Clock } from "lucide-react";

import { PersonEquipmentPanel } from "@/components/equipment/PersonEquipmentPanel";
import { Button } from "@/components/ui/button";
import type { HrConfig, PersonFull } from "@/lib/api/hr";
import { useLeaveBalance } from "@/lib/api/hr-leave";
import { warsawToday } from "@/lib/warsaw-date";

import { LeaveRequestDialog } from "../leave/LeaveRequestDialog";
import { AbsenceCard } from "./cards/AbsenceCard";
import { BonusCard } from "./cards/BonusCard";
import { ManagerCard } from "./cards/ManagerCard";
import { MonthCard } from "./cards/MonthCard";
import { OverviewCard } from "./cards/OverviewCard";
import { TodoCard } from "./cards/TodoCard";
import { absenceActionLabel } from "./overview-format";

export interface MyOverviewTabProps {
  config: HrConfig;
  person: PersonFull;
  /** Przejście do innej zakładki „Mojego czasu” (wartość `?tab=`). */
  onOpenTab: (value: string) => void;
}

/**
 * „Mój czas → Przegląd” (etap 2, D1): ile mam nieobecności, co z moim
 * miesiącem, ile i kiedy dostanę, przełożony, sprzęt i moje zadania. Każda
 * karta zależy od swojego modułu (wyłączony = brak karty) i ma własny stan:
 * awaria to zdanie z ponowieniem, nigdy „0”.
 */
export function MyOverviewTab({ config, person, onOpenTab }: MyOverviewTabProps) {
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const open = config.open_modules;
  const [dialogOpen, setDialogOpen] = useState(false);
  const balance = useLeaveBalance(year, open.leave);
  const form = person.employment_type;
  const firstName = person.name.split(/\s+/)[0] ?? person.name;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Dzień dobry, {firstName}</p>
        <div className="flex flex-wrap gap-2">
          {open.time ? (
            <Button variant="outline" size="sm" onClick={() => onOpenTab("month")}>
              <Clock className="mr-1.5 h-4 w-4" aria-hidden />
              Uzupełnij dzień
            </Button>
          ) : null}
          {open.leave ? (
            <Button size="sm" onClick={() => setDialogOpen(true)}>
              <CalendarPlus className="mr-1.5 h-4 w-4" aria-hidden />
              {absenceActionLabel(form)}
            </Button>
          ) : null}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {open.leave ? <AbsenceCard form={form} year={year} today={today} /> : null}
        {open.time ? <MonthCard form={form} today={today} onOpenTab={onOpenTab} /> : null}
        {open.payroll ? <BonusCard today={today} onOpenTab={onOpenTab} /> : null}
        <ManagerCard person={person} leaveOpen={open.leave} />
        {open.equipment ? (
          <OverviewCard title="Mój sprzęt">
            <PersonEquipmentPanel userId="mine" />
          </OverviewCard>
        ) : null}
        <TodoCard config={config} person={person} onOpenTab={onOpenTab} />
      </div>
      {open.leave ? (
        <LeaveRequestDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          mode="self"
          allowedTypes={balance.data?.allowed_types}
          employmentType={form}
        />
      ) : null}
    </div>
  );
}
