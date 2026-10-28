"use client";

// „Nowe osoby do ustawienia” w „Czeka na Ciebie” (0612, decyzje Artura
// 28.10.2026) — admin i Head of Recruitment. Konto po pierwszym logowaniu
// przez Microsoft ma „Zdecyduj”, rekruter bez kategorii albo przełożonego —
// „Uzupełnij”. Link z dzwonka i maila (`?nowa-osoba=<id>`, przy „Zostaw jako
// Konsultanta” także `&zostaw=1`) otwiera okno tej osoby; parametry znikają
// z adresu po otwarciu, więc F5 nie otwiera okna drugi raz.

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import type { NewPersonSetupRow } from "@/lib/api/boardTasks";
import { useUrlWriter } from "@/lib/url-selection";
import { hasRole, useAuthStore } from "@/store/auth";

import { BOARD_TASKS_ROWS, Section } from "./BoardTasksSection";
import { NewPersonSetupDialog } from "./NewPersonSetupDialog";

export const NEW_PERSON_PARAM = "nowa-osoba";
export const KEEP_PARAM = "zostaw";

export function newPersonLabel(row: NewPersonSetupRow): string {
  if (row.needs_decision) {
    const day = new Date(row.since).toLocaleDateString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      timeZone: "Europe/Warsaw",
    });
    return `Nowe konto · od ${day}`;
  }
  const categories = row.missing.includes("categories");
  const manager = row.missing.includes("manager");
  if (categories && manager) return "Rekruter bez kategorii i przełożonego";
  return categories ? "Rekruter bez kategorii" : "Rekruter bez przełożonego";
}

export function NewPeopleSection({ rows }: { rows: NewPersonSetupRow[] }) {
  // Bez osób nic nie montujemy — także hooków adresu (panel stoi też
  // w harnessach i kafelku, gdzie routera bywa brak).
  return rows.length > 0 ? <NewPeopleList rows={rows} /> : null;
}

function NewPeopleList({ rows }: { rows: NewPersonSetupRow[] }) {
  const [open, setOpen] = useState<NewPersonSetupRow | null>(null);
  const [presetKeep, setPresetKeep] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const me = useAuthStore((s) => s.user);
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const { showInfo } = useToast();
  const linked = params?.get(NEW_PERSON_PARAM) ?? null;

  useEffect(() => {
    if (!linked) return;
    const row = rows.find((r) => String(r.user_id) === linked);
    if (row) {
      setPresetKeep(params?.get(KEEP_PARAM) === "1" && row.needs_decision);
      setOpen(row);
    } else {
      showInfo("Tę osobę ktoś już ustawił.");
    }
    const next = new URLSearchParams(params?.toString() ?? "");
    next.delete(NEW_PERSON_PARAM);
    next.delete(KEEP_PARAM);
    const query = next.toString();
    replaceUrl(`${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
  }, [linked, rows, params, replaceUrl, showInfo]);

  const shown = expanded ? rows : rows.slice(0, BOARD_TASKS_ROWS);
  return (
    <>
      <Section
        title="Nowe osoby do ustawienia"
        hint="Pierwsze logowanie zakłada konto „Konsultant/Kontraktor”. Zdecyduj, kim jest, i uzupełnij, czego brakuje rekruterowi."
        count={rows.length}
        expanded={expanded}
        onToggle={() => setExpanded((v) => !v)}
      >
        {shown.map((row) => (
          <li key={row.user_id} className="flex items-center gap-2 px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{row.name}</p>
              <p className="truncate text-xs text-muted-foreground">{newPersonLabel(row)}</p>
            </div>
            <Button
              size="sm"
              variant={row.needs_decision ? "primary" : "outline"}
              onClick={() => {
                setPresetKeep(false);
                setOpen(row);
              }}
            >
              {row.needs_decision ? "Zdecyduj" : "Uzupełnij"}
            </Button>
          </li>
        ))}
      </Section>
      <NewPersonSetupDialog
        person={open}
        presetKeep={presetKeep}
        isAdmin={hasRole(me, "admin")}
        onClose={() => setOpen(null)}
      />
    </>
  );
}
