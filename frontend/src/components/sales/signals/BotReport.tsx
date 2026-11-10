"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { SignalRun } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";

const ITEM = "text-xs leading-snug text-muted-foreground";

const STATUS_TEXT: Record<SignalRun["status"], string> = {
  started: "Bot jeszcze pracuje. Raport przyjdzie w ciągu dwóch godzin.",
  received: "",
  expired: "Bot nie odesłał raportu w dwie godziny. Bieg jest zamknięty bez wyników.",
  failed: "Nie udało się uruchomić bota. Bieg jest zamknięty bez wyników.",
};

export function runSummary(run: SignalRun): string {
  if (run.status !== "received") return STATUS_TEXT[run.status];
  const report = run.report;
  const strong = (report.by_strength?.strong ?? 0) + (report.by_strength?.medium ?? 0);
  const weak = report.by_strength?.weak ?? 0;
  const quiet = report.quiet?.length ?? 0;
  return `${report.checked_firms ?? run.company_count} firm sprawdzonych, ${strong} warte sprawdzenia, ${weak} słabych, ${quiet} bez sygnału`;
}

/** Raport biegu: co bot sprawdził, czego nie znalazł i co NEXUS odrzucił. */
export function BotReport({ run, onClose }: { run: SignalRun; onClose: () => void }) {
  const report = run.report;
  const dropped = report.dropped ?? {};
  const window = dropped.outside_window ?? [];
  const clients = dropped.nexus_clients ?? [];
  return (
    <Card className="space-y-2 overflow-y-auto px-3 py-2.5 lg:sticky lg:top-3 lg:max-h-[calc(100dvh-15.25rem)]">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Raport bota</h2>
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onClose}>
          Zamknij
        </Button>
      </header>
      <p className={ITEM}>
        Bieg z {formatIsoDatePl(run.started_at)} · wysłane firmy: {run.company_count}
        {run.status === "received" ? ` · sygnałów od bota: ${report.signals_in ?? 0}` : ""}
      </p>
      {run.status !== "received" ? (
        <p className="text-xs text-foreground">{STATUS_TEXT[run.status]}</p>
      ) : (
        <>
          <section className="space-y-0.5">
            <h3 className="text-xs font-medium text-foreground">Bez sygnału ({report.quiet?.length ?? 0})</h3>
            <p className={ITEM}>{report.quiet?.length ? report.quiet.join(", ") : "—"}</p>
          </section>
          <h3 className="border-t border-border pt-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Odrzucone przez NEXUS
          </h3>
          <section className="space-y-0.5">
            <h4 className="text-xs font-medium text-foreground">Poza 120 dniami ({window.length})</h4>
            <ul className="space-y-0.5">
              {window.map((item) => (
                <li key={`${item.company}-${item.title}`} className={ITEM}>
                  <span className="text-foreground">{item.company}</span> · {formatIsoDatePl(item.published)} ·{" "}
                  {item.title}
                </li>
              ))}
            </ul>
          </section>
          <section className="space-y-0.5">
            <h4 className="text-xs font-medium text-foreground">
              Klient NEXUSA, sprawa dla Delivery Leada ({clients.length})
            </h4>
            <ul className="space-y-0.5">
              {clients.map((item) => (
                <li key={item.company} className={ITEM}>
                  <span className="text-foreground">{item.company}</span> · {item.client} ·{" "}
                  {item.delivery_lead ?? "bez Delivery Leada, zgłoś do Heada"}
                </li>
              ))}
            </ul>
          </section>
          <p className={ITEM}>
            Firma spoza listy biegu: {dropped.unknown_company ?? 0} · ten sam link drugi raz: {dropped.duplicates ?? 0}
          </p>
        </>
      )}
    </Card>
  );
}
