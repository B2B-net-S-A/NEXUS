"use client";

// Karta osoby w raporcie klienta (plan Nordei N1.5): przedziały T4T × NIDS ze
// statusami, faktura kontraktora z KSeF, historia statusu w kolejnych wersjach
// i kartoteka (numer osoby, NIDS).
import { ArrowLeft } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useTimeReportPerson, type TimeReportHistoryEntry, type WeekCell } from "@/lib/api/client-time-reports";
import { cn } from "@/lib/utils";

import { pln } from "./format";
import { T4T_STATUS, dateText, hoursText, periodLabel } from "./time-report-format";

interface TimeReportPersonCardProps {
  clientId: number;
  month: string;
  personKey: string;
  versionId: number | null;
  onBack: () => void;
}

const CONTRACT_STATUS: Record<string, string> = {
  active: "aktywny",
  ending: "kończy się",
  ended: "zakończony",
};
const ID_SOURCE: Record<string, string> = {
  ksef_item: "z faktury do klienta w KSeF",
  report_name: "po imieniu i nazwisku z raportu",
  manual: "wpisany ręcznie",
};

function Cell({ cell }: { cell: WeekCell }) {
  const approved = Number(cell[0]);
  const submitted = Number(cell[1]);
  if (!approved && !submitted) return <span className="text-muted-foreground">–</span>;
  return (
    <>
      {approved ? <span>{approved.toLocaleString("pl-PL")}</span> : null}
      {submitted ? <span className="ml-1 rounded bg-warning-muted px-1 text-warning-muted-foreground">{submitted.toLocaleString("pl-PL")} złoż.</span> : null}
    </>
  );
}

export function TimeReportPersonCard({ clientId, month, personKey, versionId, onBack }: TimeReportPersonCardProps) {
  const query = useTimeReportPerson(clientId, month, personKey, versionId);

  if (query.isError) {
    return (
      <div className="space-y-2">
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ArrowLeft aria-hidden className="size-3.5" /> Wróć do listy
        </Button>
        <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać karty osoby.")} onRetry={() => query.refetch()} />
      </div>
    );
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const p = query.data;
  const s = p.selected;
  const labels = p.periods.map(periodLabel);
  const personNumbers = p.ids.filter((i) => i.kind === "client_person_no" && i.state !== "rejected");
  const projectNumbers = p.ids.filter((i) => i.kind === "project_no" && i.state === "confirmed");

  return (
    <div className="space-y-2.5">
      <Button size="sm" variant="ghost" onClick={onBack}>
        <ArrowLeft aria-hidden className="size-3.5" /> Wróć do listy
      </Button>
      <div className="grid min-w-0 gap-2.5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-w-0 space-y-2.5 rounded-xl border bg-card p-3">
          <header className="flex flex-wrap items-start gap-x-3 gap-y-1">
            <div className="min-w-0">
              <h2 className="text-base font-semibold">{p.name}</h2>
              <p className="text-[11px] tabular-nums text-muted-foreground">
                numer osoby {p.person_no ?? "–"}
                {p.report_name && p.report_name !== p.name ? ` · w raporcie „${p.report_name}”` : ""} · kontrakt{" "}
                {p.contract ? (CONTRACT_STATUS[p.contract.status] ?? p.contract.status) : "nieprzypisany"}
              </p>
            </div>
            {s?.status ? (
              <StatusDot tone={T4T_STATUS[s.status].tone} className="ml-auto">
                {T4T_STATUS[s.status].label}
              </StatusDot>
            ) : null}
          </header>
          {s?.notes.length ? (
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {s.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          {s && s.projects.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead className="border-b text-left text-[11px] text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-2 font-medium">NIDS</th>
                    {labels.map((l) => (
                      <th key={l} className="px-1 py-1 text-right font-medium">
                        {l}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {s.projects.map((pr) => (
                    <tr key={pr.project_no ?? "bez"}>
                      <td className="py-1.5 pr-2">
                        <span className="block tabular-nums">{pr.project_no ?? "bez NIDS"}</span>
                        {pr.project_name ? <span className="block max-w-56 truncate text-[11px] text-muted-foreground">{pr.project_name}</span> : null}
                      </td>
                      {pr.weeks.map((c, j) => (
                        <td key={labels[j] ?? j} className="px-1 py-1.5 text-right tabular-nums">
                          <Cell cell={c} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
                <tfoot className="border-t text-[12px]">
                  <tr>
                    <td className="py-1.5 pr-2 font-medium">Zatwierdzone (2)</td>
                    {s.weeks.map((c, j) => (
                      <td key={labels[j] ?? j} className="px-1 py-1.5 text-right tabular-nums">
                        {Number(c[0]) ? Number(c[0]).toLocaleString("pl-PL") : "–"}
                      </td>
                    ))}
                  </tr>
                  <tr className="text-warning-muted-foreground">
                    <td className="py-1 pr-2 font-medium">Złożone (1)</td>
                    {s.weeks.map((c, j) => (
                      <td key={labels[j] ?? j} className="px-1 py-1 text-right tabular-nums">
                        {Number(c[1]) ? Number(c[1]).toLocaleString("pl-PL") : "–"}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Tej osoby nie ma w wybranej wersji raportu.</p>
          )}
          <div className="grid gap-2 sm:grid-cols-3">
            <Tile
              title="Faktura kontraktora (KSeF)"
              value={hoursText(p.invoice?.hours)}
              hint={p.invoice?.note ?? (p.invoice ? "netto ÷ stawka z kontraktu" : "nie ma faktury za ten miesiąc")}
            />
            <Tile
              title="Zatwierdzone w T4T"
              value={hoursText(s?.approved)}
              hint={Number(s?.submitted ?? 0) > 0 ? `+ ${hoursText(s?.submitted)} w statusie 1` : "nic w statusie 1"}
            />
            <Tile
              title="Różnica faktura − zatwierdzone"
              value={hoursText(s?.difference)}
              hint={s?.difference == null ? "bez faktury nie ma różnicy" : Number(s.difference) === 0 ? "zgadza się" : "do wyjaśnienia"}
              alert={s?.difference != null && Math.abs(Number(s.difference)) > 0.01}
            />
          </div>
          {p.invoice?.invoices.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-xs">
                <thead className="text-left text-[11px] text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-2 font-medium">Faktura</th>
                    <th className="py-1 pr-2 font-medium">Wystawiona</th>
                    <th className="py-1 pr-2 font-medium">Numer KSeF</th>
                    {p.can_see_amounts ? <th className="py-1 text-right font-medium">Netto</th> : null}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {p.invoice.invoices.map((i) => (
                    <tr key={i.id}>
                      <td className="py-1 pr-2">{i.invoice_number ?? "–"}</td>
                      <td className="py-1 pr-2 tabular-nums">{dateText(i.issue_date)}</td>
                      <td className="max-w-48 truncate py-1 pr-2 tabular-nums text-muted-foreground">{i.ksef_number}</td>
                      {p.can_see_amounts ? <td className="py-1 text-right tabular-nums">{pln(i.net_amount)}</td> : null}
                    </tr>
                  ))}
                </tbody>
              </table>
              {p.can_see_amounts && p.invoice.rate ? (
                <p className="mt-1 text-[11px] text-muted-foreground">Stawka z kontraktu: {pln(p.invoice.rate)} / h</p>
              ) : null}
            </div>
          ) : null}
        </section>
        <aside className="space-y-2.5">
          <section className="rounded-xl border bg-card p-3">
            <h3 className="text-[13px] font-semibold">Historia wersji raportu</h3>
            <ol className="mt-1.5 space-y-1">
              {p.history.map((h) => (
                <HistoryItem key={h.id} entry={h} current={h.id === p.version_id} />
              ))}
            </ol>
          </section>
          <section className="rounded-xl border bg-card p-3 text-xs">
            <h3 className="text-[13px] font-semibold">Kartoteka</h3>
            <ul className="mt-1 space-y-0.5 text-muted-foreground">
              {personNumbers.length ? (
                personNumbers.map((i) => (
                  <li key={i.id}>
                    Numer osoby <span className="tabular-nums text-foreground">{i.value}</span> · {ID_SOURCE[i.source]}
                    {i.state === "suggested" ? " · czeka na zatwierdzenie" : ""}
                  </li>
                ))
              ) : (
                <li>Brak numeru osoby: przypisz go w podzakładce „Kartoteka”.</li>
              )}
              {projectNumbers.length ? (
                <li>
                  NIDS z faktur: <span className="tabular-nums text-foreground">{projectNumbers.map((i) => i.value).join(", ")}</span>
                </li>
              ) : null}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}

function Tile({ title, value, hint, alert }: { title: string; value: string; hint: string; alert?: boolean }) {
  return (
    <div className="rounded-lg bg-muted/50 px-2.5 py-2">
      <p className="text-[11px] text-muted-foreground">{title}</p>
      <p className={cn("font-display text-lg font-semibold tabular-nums", alert && "text-destructive")}>{value}</p>
      <p className="text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}

function HistoryItem({ entry, current }: { entry: TimeReportHistoryEntry; current: boolean }) {
  return (
    <li className={cn("flex items-center gap-2 text-xs", current && "font-medium")}>
      <span className="w-20 shrink-0 tabular-nums text-muted-foreground">
        v{entry.version_no} · {dateText(entry.received_on).slice(0, 5)}
      </span>
      {entry.status ? (
        <StatusDot tone={T4T_STATUS[entry.status].tone}>{T4T_STATUS[entry.status].label}</StatusDot>
      ) : (
        <span className="text-muted-foreground">–</span>
      )}
      <span className="ml-auto tabular-nums text-muted-foreground">
        {entry.approved != null ? hoursText(entry.approved) : ""}
        {Number(entry.submitted ?? 0) > 0 ? ` + ${hoursText(entry.submitted)}` : ""}
      </span>
    </li>
  );
}
