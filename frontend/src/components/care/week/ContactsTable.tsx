"use client";

import { Button } from "@/components/ui/button";
import type { WeekContact } from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { formatDayMonthPl } from "@/lib/date-pl";

import { frontOfficeText, lastContactText, reasonText } from "./week-format";

interface ContactsTableProps {
  rows: WeekContact[];
  today: string;
  canEdit: boolean;
  showOwner: boolean;
  selectedId: number | null;
  onOpen: (row: WeekContact) => void;
  onTalk: (row: WeekContact) => void;
}

/** „Rozmowa z konsultantem” — jedna pozycja na kontrakt, powód i ostatni kontakt. */
export function ContactsTable({
  rows,
  today,
  canEdit,
  showOwner,
  selectedId,
  onOpen,
  onTalk,
}: ContactsTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm" aria-label="Rozmowy z konsultantami">
        <thead>
          <tr className={CALM_ROW}>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Powód</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Ostatnio</th>
            {showOwner ? (
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th>
            ) : null}
            {canEdit ? <th className="w-0 px-3 py-2" aria-label="Akcje" /> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const [primary, ...rest] = row.reasons;
            const last = lastContactText(row);
            const place = [
              row.client_name,
              row.manager
                ? `${row.manager.area ? `${row.manager.area.name} · ` : ""}menedżer: ${row.manager.name}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <tr
                key={row.contract_id}
                className={cn(CALM_ROW, selectedId === row.contract_id && "bg-muted/60")}
              >
                <td className="px-3 py-1.5 align-top">
                  <button
                    type="button"
                    className="text-left font-medium hover:underline"
                    aria-label={`Oś konsultanta: ${row.candidate_name ?? "konsultant"}`}
                    onClick={() => onOpen(row)}
                  >
                    {row.candidate_name ?? "Konsultant"}
                  </button>
                  <span className={CALM_SUBLINE}>{place}</span>
                </td>
                <td className="px-3 py-1.5 align-top">
                  <span className={cn(primary.overdue && "text-destructive")}>
                    {reasonText(primary, today)}
                  </span>
                  {rest.length ? (
                    <span className={CALM_SUBLINE}>
                      {rest.map((reason) => reasonText(reason, today)).join(" · ")}
                    </span>
                  ) : null}
                  {row.front_office.reasons.length ? (
                    <span className={CALM_SUBLINE}>
                      {row.front_office.handed_off_on
                        ? `przekazany do front office ${formatDayMonthPl(row.front_office.handed_off_on)}`
                        : `do front office: ${frontOfficeText(row.front_office.reasons)}`}
                    </span>
                  ) : null}
                </td>
                <td className="max-w-80 px-3 py-1.5 align-top">
                  {row.last_conversation ? (
                    <>
                      <span className="tabular-nums">
                        {formatDayMonthPl(row.last_conversation.occurred_on)}
                        {row.last_conversation.satisfaction
                          ? ` · ${row.last_conversation.satisfaction}/5`
                          : ""}
                      </span>
                      {last ? <span className={cn(CALM_SUBLINE, "line-clamp-2")}>{last}</span> : null}
                    </>
                  ) : last ? (
                    <span className="text-muted-foreground">{last}</span>
                  ) : (
                    <span className={CALM_EMPTY}>bez rozmów</span>
                  )}
                </td>
                {showOwner ? (
                  <td className="px-3 py-1.5 align-top">
                    {row.owner?.name ?? <span className={CALM_EMPTY}>—</span>}
                  </td>
                ) : null}
                {canEdit ? (
                  <td className="px-3 py-1.5 text-right align-top">
                    <Button size="sm" variant="outline" onClick={() => onTalk(row)}>
                      Zapisz rozmowę
                    </Button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
