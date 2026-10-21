"use client";

import Link from "next/link";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import type { OwnProfile } from "@/lib/api/hr";
import { formatDays } from "@/components/hr/people/hr-format";
import { useAbsences } from "@/lib/api/hr-leave";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";
import { cn } from "@/lib/utils";

import { OverviewCard } from "./OverviewCard";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * „Ja w firmie”: stanowisko, przełożony (koordynator) i link do kartoteki —
 * zastępuje zakładkę „Kartoteka” (makieta 21.10.2026). Pula nieobecności tylko
 * przy zamkniętym module nieobecności; otwarty pokazuje ją karta obok.
 */
export function ManagerCard({
  person,
  leaveOpen,
  year,
}: {
  person: OwnProfile;
  leaveOpen: boolean;
  year: number;
}) {
  const managerId = person.manager_user_id;
  const absences = useAbsences(managerId ? [managerId] : [], { enabled: leaveOpen && Boolean(managerId) });
  const absence = managerId ? absences.byUser.get(managerId) : undefined;
  // UoP „przełożony” i „wniosek”, B2B i zlecenie „koordynator” i „zgłoszenie” (D4, D5).
  const terms = employmentTerms(person.employment_type);
  const position = [person.job_title, person.department].filter(Boolean).join(" · ");
  const pool = person.entitlements?.find((row) => row.year === year);
  return (
    <OverviewCard title="Ja w firmie">
      <p className="text-sm">
        {position ? (
          <span className="text-foreground">{position}</span>
        ) : (
          <span className="text-muted-foreground">Stanowisko nieuzupełnione — uzupełnią je Kadry.</span>
        )}
      </p>
      <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        {capitalize(terms.coordinator)}
      </p>
      {person.manager_name && managerId ? (
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary",
              // Pierścień „w pracy” tylko, gdy wiemy (moduł nieobecności otwarty i odpowiedź jest).
              leaveOpen && absences.isSuccess
                ? absence
                  ? "ring-2 ring-warning ring-offset-2 ring-offset-card"
                  : "ring-2 ring-success ring-offset-2 ring-offset-card"
                : null,
            )}
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
                <span className="text-xs text-muted-foreground">dostępny(a)</span>
              )
            ) : null}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {capitalize(terms.coordinator)} nie jest ustawiony — ustawią go Kadry.
        </p>
      )}
      {leaveOpen ? (
        <p className="text-xs text-muted-foreground">
          Zastępcę na czas nieobecności wskazujesz {terms.flow === "request" ? "we wniosku" : "w zgłoszeniu"}.
        </p>
      ) : pool ? (
        <p className="text-xs text-muted-foreground">
          {person.employment_type === "uop" ? "Pula urlopowa" : "Płatne dni przerwy"} {year}:{" "}
          {pool.entitlement_days == null ? "bez puli" : `${formatDays(pool.entitlement_days)} dni`}
          {Number(pool.carried_over_days) > 0 ? ` + ${formatDays(pool.carried_over_days)} dni zaległego` : ""}
        </p>
      ) : null}
      <Link href={`/people/${person.user_id}`} className="mt-auto text-sm font-medium text-primary hover:underline">
        Otwórz kartotekę
      </Link>
    </OverviewCard>
  );
}
