"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { UserPlus, UserRoundPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { usePeople, type HrConfig } from "@/lib/api/hr";

import { AddPersonDialog } from "./AddPersonDialog";
import { PeopleTidyUp } from "./PeopleTidyUp";

/**
 * Akcje nagłówka „Ludzi” (22.10.2026): „Porządki · N”, „Wejście nowej osoby”
 * i „Dodaj osobę”. Wcześniej dwa ostatnie stały nad katalogiem.
 */
export function PeopleHeaderActions({ config }: { config: HrConfig }) {
  const canAdd = config.me.people_admin;
  const people = usePeople();
  const [adding, setAdding] = useState(false);
  const managers = useMemo(
    () => (people.data?.items ?? []).map((row) => ({ user_id: row.user_id, name: row.name })),
    [people.data],
  );
  return (
    <>
      <PeopleTidyUp config={config} />
      {canAdd ? (
        <>
          {/* Wejście nowej osoby = kreator z zadaniami (moduł wejścia/odejścia). */}
          {config.open_modules.lifecycle ? (
            <Button variant="outline" asChild>
              <Link href="/people/new">
                <UserRoundPlus className="h-4 w-4" aria-hidden />
                Wejście nowej osoby
              </Link>
            </Button>
          ) : null}
          <Button onClick={() => setAdding(true)}>
            <UserPlus className="h-4 w-4" aria-hidden />
            Dodaj osobę
          </Button>
          <AddPersonDialog open={adding} onOpenChange={setAdding} managers={managers} />
        </>
      ) : null}
    </>
  );
}
