"use client";

/**
 * Zakładka „Zespół” w „Moich ludziach” (decyzja Artura 25.10.2026) — dla
 * Head of Recruitment i admina: czyja lista leży. Wiersz osoby otwiera jej
 * listę do podglądu (bez uśpień i dodawania — to decyzje właściciela).
 */

import { useState } from "react";
import { ChevronLeft } from "lucide-react";

import type { TeamMember } from "@/lib/api/myPeople";
import { useMyPeopleOfMember } from "@/lib/api/myPeople";
import { apiErrorMessage } from "@/lib/api-error";
import { plural, splitPeople } from "@/lib/my-people-summary";
import { cn } from "@/lib/utils";
import { EmptyListView, ErrorView, PeopleListView } from "./MyPeopleViews";

const ROLE_LABEL: Record<string, string> = {
  recruiter: "Rekruter",
  delivery_lead: "Delivery Lead",
  talent_community_manager: "TCM",
  head_of_recruitment: "Head of Recruitment",
  admin: "Admin",
};

/** Najważniejsza rola do podpisu — HoR i DL przed rekruterem. */
export function roleLabel(roles: readonly string[]): string {
  for (const role of ["head_of_recruitment", "delivery_lead", "talent_community_manager", "recruiter"]) {
    if (roles.includes(role)) return ROLE_LABEL[role];
  }
  return roles[0] ? (ROLE_LABEL[roles[0]] ?? roles[0]) : "";
}

/** Bez siebie i bez pustych list; od największej zaległości. */
export function teamRows(members: readonly TeamMember[], selfId: number): TeamMember[] {
  return members
    .filter((m) => m.user_id !== selfId && m.total > 0)
    .sort((a, b) => b.idle - a.idle || b.total - a.total || a.name.localeCompare(b.name, "pl"));
}

/** Więcej niż 70% listy czeka — wiersz dostaje kolor ostrzeżenia. */
export function isStale(m: Pick<TeamMember, "idle" | "total">): boolean {
  return m.total > 0 && m.idle / m.total > 0.7;
}

const GRID = "grid grid-cols-[minmax(0,1fr)_3.25rem_3.75rem_3.5rem] gap-x-2";

function MemberList({
  member,
  categories,
  onBack,
}: {
  member: TeamMember;
  categories: { id: number; name_pl: string }[];
  onBack: () => void;
}) {
  const people = useMyPeopleOfMember(member.user_id);
  const split = people.data ? splitPeople(people.data.rows) : null;
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        Cały zespół
      </button>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{member.name}</h3>
        <p className="text-xs text-muted-foreground">
          {roleLabel(member.roles)} · {member.total}{" "}
          {plural(member.total, "osoba", "osoby", "osób")} na liście, {member.idle} czeka · podgląd
        </p>
      </div>
      {people.isError ? (
        <ErrorView
          message={apiErrorMessage(people.error, "Nie udało się wczytać listy tej osoby.")}
          onRetry={() => void people.refetch()}
        />
      ) : !people.isSuccess || !split ? (
        <p className="px-2 py-6 text-center text-sm text-muted-foreground">Wczytuję listę…</p>
      ) : people.data.rows.length === 0 ? (
        <EmptyListView />
      ) : (
        <PeopleListView
          active={split.active}
          working={split.working}
          snoozed={split.snoozed}
          categories={categories}
          actions={{}}
          truncated={people.data.truncated}
        />
      )}
    </div>
  );
}

export function TeamListsView({
  members,
  idleDays,
  selfId,
  categories,
}: {
  members: readonly TeamMember[];
  idleDays: number;
  selfId: number;
  categories: { id: number; name_pl: string }[];
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  const rows = teamRows(members, selfId);
  const open = rows.find((m) => m.user_id === openId);
  if (open) {
    return <MemberList member={open} categories={categories} onBack={() => setOpenId(null)} />;
  }
  if (!rows.length) {
    return (
      <p className="px-2 py-6 text-center text-sm text-muted-foreground">
        Nikt w zespole nie ma jeszcze nikogo na liście „Moi ludzie”.
      </p>
    );
  }
  const idleSum = rows.reduce((sum, m) => sum + m.idle, 0);
  const top = rows[0];
  return (
    <div className="space-y-3">
      <p className="rounded-md bg-primary/5 px-3 py-2 text-xs text-foreground">
        Na listach zespołu {idleSum}{" "}
        {plural(idleSum, "osoba czeka", "osoby czekają", "osób czeka")} ponad {idleDays} dni bez
        wysyłki CV i bez procesu.
        {top.idle > 0 ? ` Najwięcej u: ${top.name} (${top.idle} z ${top.total}).` : ""}
      </p>
      <div
        className={cn(
          GRID,
          "px-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground",
        )}
        aria-hidden
      >
        <span>Osoba</span>
        <span className="text-right">Na liście</span>
        <span className="text-right">&gt; {idleDays} dni</span>
        <span className="text-right">Nowe dop.</span>
      </div>
      <ul className="space-y-0.5">
        {rows.map((m) => (
          <li key={m.user_id}>
            <button
              type="button"
              onClick={() => setOpenId(m.user_id)}
              aria-label={`${m.name}: ${m.total} na liście, ${m.idle} czeka ponad ${idleDays} dni, ${m.new_matches} nowych dopasowań — otwórz listę`}
              className={cn(GRID, "w-full items-center rounded-lg px-2 py-1.5 text-left hover:bg-muted/60")}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-foreground">{m.name}</span>
                <span className="block text-[11px] text-muted-foreground">{roleLabel(m.roles)}</span>
              </span>
              <span className="text-right text-sm tabular-nums text-foreground">{m.total}</span>
              <span
                className={cn(
                  "text-right text-sm tabular-nums",
                  isStale(m) ? "font-semibold text-warning" : "text-foreground",
                )}
              >
                {m.idle}
              </span>
              <span className="text-right text-sm tabular-nums text-foreground">
                {m.new_matches}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="px-2 text-[11px] text-muted-foreground">
        Kliknięcie osoby otwiera jej listę do podglądu. „Nowe dop.” to dopasowania do nowych
        rekrutacji, których ta osoba jeszcze nie obejrzała.
      </p>
    </div>
  );
}
