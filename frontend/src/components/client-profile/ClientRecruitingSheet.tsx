"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { phase5Api, type ConflictRegistryParams } from "@/lib/api";
import { useClientPlaybook, type ClientPlaybook } from "@/lib/client-playbooks";
import { conflictKeys } from "@/lib/conflicts";
import { countPl } from "@/lib/plural-pl";
import { CLIENT_CONFLICTS_LIMIT } from "@/components/client-profile/ClientConflictsSection";

/** Ile linii zasad procesu stoi w ściądze; całość jest w „Zasadach rekrutacji”. */
const RULE_LINES = 4;

/**
 * Najważniejsze zasady z karty klienta jako krótkie punkty: liczby, które są
 * ustawione (blokada, SLA, limit CV), i pierwsze linie zasad procesu bez
 * znaczników Markdown. Nic nie dopisujemy — to tylko skrót karty.
 */
export function playbookCheatLines(playbook: ClientPlaybook | undefined): string[] {
  if (!playbook?.exists) return [];
  const lines: string[] = [];
  if (playbook.hold_hours != null) lines.push(`Blokada kandydata: ${playbook.hold_hours} h`);
  if (playbook.sla_business_days != null) {
    lines.push(
      `Pierwszy kandydat w ${countPl(playbook.sla_business_days, "dzień roboczy", "dni robocze", "dni roboczych")}`,
    );
  }
  if (playbook.cv_limit_per_process != null) {
    lines.push(`Limit CV na proces: ${playbook.cv_limit_per_process}`);
  }
  const rules = (playbook.process_rules_md ?? "")
    .split("\n")
    .map((line) => line.replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "").replace(/[*_`#>]/g, "").trim())
    .filter(Boolean)
    .slice(0, RULE_LINES);
  return [...lines, ...rules];
}

/**
 * „Ściąga” obok projektów klienta (makieta 19.11.2026, wariant A ekranu
 * Rekrutacje): zasady z karty klienta i aktywne konflikty, zawsze pod ręką
 * przy liście rekrutacji. Te same zapytania co zakładki „Zasady rekrutacji”
 * i „Konflikty z kandydatami”.
 */
export function ClientRecruitingSheet({ clientId }: { clientId: number }) {
  const playbook = useClientPlaybook(clientId);
  const params: ConflictRegistryParams = {
    client_id: clientId,
    state: "active",
    limit: CLIENT_CONFLICTS_LIMIT,
    offset: 0,
  };
  const conflicts = useQuery({
    queryKey: conflictKeys.registry(params),
    queryFn: () => phase5Api.conflicts.registry(params).then((r) => r.data),
  });
  const lines = playbookCheatLines(playbook.data);
  const conflictCount = conflicts.data?.total ?? null;

  return (
    <aside
      className="space-y-3 rounded-xl border border-border bg-card px-4 py-3 text-[13px] shadow-xs"
      aria-label="Ściąga: zasady i konflikty klienta"
      data-tour="client.recruiting-sheet"
    >
      <div>
        <h3 className="text-sm font-semibold text-foreground">Zasady klienta</h3>
        {playbook.isLoading ? (
          <p className="mt-1 text-muted-foreground">Wczytywanie karty klienta…</p>
        ) : playbook.isError ? (
          <p className="mt-1 text-muted-foreground">Nie udało się wczytać karty klienta.</p>
        ) : lines.length === 0 ? (
          <p className="mt-1 text-muted-foreground">Karta klienta nie ma jeszcze zasad.</p>
        ) : (
          <ul className="mt-1 list-disc space-y-1 pl-4 text-foreground">
            {lines.map((line, index) => (
              <li key={`${index}-${line}`} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        )}
        <Link
          href={`/clients/${clientId}?tab=zasady`}
          className="mt-1.5 inline-block text-xs font-medium text-primary hover:underline"
        >
          Pełne zasady rekrutacji →
        </Link>
      </div>
      <div className="border-t border-border pt-2">
        <h3 className="text-sm font-semibold text-foreground">Konflikty z kandydatami</h3>
        <p className="mt-1 text-muted-foreground">
          {conflicts.isError
            ? "Nie udało się wczytać konfliktów."
            : conflictCount === null
              ? "Wczytywanie…"
              : conflictCount === 0
                ? "Brak aktywnych konfliktów."
                : `${countPl(conflictCount, "aktywny konflikt", "aktywne konflikty", "aktywnych konfliktów")} — kandydat jest widoczny, z plakietką powodu.`}
        </p>
        <Link
          href={`/clients/${clientId}?tab=konflikty`}
          className="mt-1.5 inline-block text-xs font-medium text-primary hover:underline"
        >
          Konflikty →
        </Link>
      </div>
    </aside>
  );
}
