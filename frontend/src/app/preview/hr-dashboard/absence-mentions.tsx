"use client";

/**
 * Część makiety 1 „Plakietka i wzmianka”: nieobecność przy osobie w kolumnie
 * „Rekruter” listy rekrutacji (`JobRecruiterCell` z kropką `AbsenceDot`)
 * i podpowiedź zastępcy przy „@” w polu notatki (`MentionTextarea`).
 *
 * Kolumna dostaje nieobecności wprost (tak jak od `useJobListAbsences` na
 * liście), pole notatki pobiera osoby i nieobecności samo — oba klucze zasiewa
 * `seedAbsenceMentions`.
 */

import { useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { JobRecruiterCell, type JobListRowFields } from "@/components/v2/jobs/JobListCells";
import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";
import { leaveKeys, type PersonAbsence } from "@/lib/api/hr-leave";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import type { ChatUserMini } from "@/types/job-chat";

import { HR_CAST, HR_CLIENTS, shiftDay, type HarnessPerson } from "../hr-fixtures";

const { ola, kamil, ewa, adam, marta, tomasz } = HR_CAST;

function absence(person: HarnessPerson, until: string, substitute: HarnessPerson | null): PersonAbsence {
  return {
    user_id: person.id,
    until,
    half_day: null,
    substitute_user_id: substitute?.id ?? null,
    substitute_name: substitute?.name ?? null,
  };
}

/** Dzisiejsze nieobecności (te same osoby co w „Nieobecnych dziś”). */
export function todayAbsences(today: string): PersonAbsence[] {
  return [absence(kamil, shiftDay(today, 1), ola), absence(ewa, today, marta), absence(adam, today, kamil)];
}

const MENTIONABLE: HarnessPerson[] = [kamil, ola, ewa, adam, marta, tomasz];

function mini(person: HarnessPerson): ChatUserMini {
  return { id: person.id, name: person.name, email: person.email, role: person.role };
}

/** Klucze pola „@”: lista osób (`useMentionableUsers`) i ich nieobecności (`useAbsences`). */
export function seedAbsenceMentions(client: QueryClient, today: string): void {
  client.setQueryData(["mentionable-users", "global", false], MENTIONABLE.map(mini));
  const ids = MENTIONABLE.map((person) => person.id).sort((a, b) => a - b).join(",");
  client.setQueryData(leaveKeys.absence(ids, null), { on: today, items: todayAbsences(today) });
}

function recruiter(person: HarnessPerson) {
  return { user_id: person.id, name: person.name, via: "owner" as const, proposed: false, assigned_by_name: null };
}

const JOBS: { id: number; title: string; client: string; row: JobListRowFields; inProcess: number }[] = [
  {
    id: 801,
    title: "Java Developer",
    client: HR_CLIENTS.bank.name,
    row: { recruiters: [recruiter(ola)], delivery_lead_id: kamil.id, delivery_lead_user: { name: kamil.name } },
    inProcess: 7,
  },
  {
    id: 802,
    title: "QA Engineer",
    client: HR_CLIENTS.telecom.name,
    row: { recruiters: [recruiter(ewa)], delivery_lead_id: kamil.id, delivery_lead_user: { name: kamil.name } },
    inProcess: 4,
  },
  {
    id: 803,
    title: "DevOps Engineer",
    client: HR_CLIENTS.clinic.name,
    row: { recruiters: [recruiter(tomasz)], delivery_lead_id: adam.id, delivery_lead_user: { name: adam.name } },
    inProcess: 3,
  },
];

export function AbsenceMentions({ today }: { today: string }) {
  const [note, setNote] = useState("");
  const absences = new Map(todayAbsences(today).map((row) => [row.user_id, row]));
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <section aria-label="Lista rekrutacji — kolumna Rekruter" className="min-w-0 space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Lista rekrutacji: kropka przy nieobecnym</h3>
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border/60">
                <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Rekrutacja</th>
                <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Rekruter</th>
                <th className={`${CALM_HEAD} px-3 py-2 text-right`}>W procesie</th>
              </tr>
            </thead>
            <tbody>
              {JOBS.map((job) => (
                <tr key={job.id} className={CALM_ROW}>
                  <td className="px-3 py-2">
                    <span className="font-medium text-foreground">{job.title}</span>
                    <span className="block text-xs text-muted-foreground">{job.client}</span>
                  </td>
                  <td className="px-3 py-2">
                    <JobRecruiterCell job={job.row} absences={absences} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{job.inProcess}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">
          Kropka nie poszerza kolumny; tekst nieobecności jest w podpowiedzi i dla czytnika ekranu.
        </p>
      </section>
      <section aria-label="Notatka z wzmianką" className="min-w-0 space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Notatka: „@” przy nieobecnej osobie</h3>
        <MentionTextarea
          value={note}
          onChange={setNote}
          scope={{ kind: "global" }}
          ariaLabel="Notatka do karty"
          placeholder="Wpisz „@Kam” i wybierz Kamila — pod polem pojawi się podpowiedź zastępcy."
          rows={3}
        />
      </section>
    </div>
  );
}
