"use client";

import Link from "next/link";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import type { PersonFull } from "@/lib/api/hr";
import { useAbsences } from "@/lib/api/hr-leave";

import { OverviewCard } from "./OverviewCard";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function ManagerCard({ person, leaveOpen }: { person: PersonFull; leaveOpen: boolean }) {
  const managerId = person.manager_user_id;
  const absences = useAbsences(managerId ? [managerId] : [], { enabled: leaveOpen && Boolean(managerId) });
  const absence = managerId ? absences.byUser.get(managerId) : undefined;
  return (
    <OverviewCard title="Mój przełożony">
      {person.manager_name && managerId ? (
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground"
          >
            {initials(person.manager_name)}
          </span>
          <div className="min-w-0">
            <Link href={`/people/${managerId}`} className="block truncate text-sm font-medium text-foreground hover:underline">
              {person.manager_name}
            </Link>
            {leaveOpen && absences.isSuccess ? (
              absence ? (
                <AbsenceBadge absence={absence} />
              ) : (
                <span className="text-xs text-muted-foreground">w pracy</span>
              )
            ) : null}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Przełożony nie jest ustawiony — ustawią go Kadry.</p>
      )}
      {leaveOpen ? (
        <p className="text-xs text-muted-foreground">Zastępcę na czas nieobecności wskazujesz we wniosku.</p>
      ) : null}
    </OverviewCard>
  );
}
