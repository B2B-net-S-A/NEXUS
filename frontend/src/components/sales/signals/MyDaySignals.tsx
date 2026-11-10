import Link from "next/link";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { SIGNAL_STRENGTH_LABELS, type MyDaySignal } from "@/lib/api/sales";
import { cn } from "@/lib/utils";

const LEADS = "/sales/leads";

function SignalRow({ signal }: { signal: MyDaySignal }) {
  const weak = signal.strength === "weak";
  return (
    <li className="flex min-h-11 items-center gap-2 px-3 py-1">
      <div className="min-w-0 flex-1 leading-tight">
        <div className="flex min-w-0 items-baseline gap-2">
          <Link
            href={`/sales/companies/${signal.company.id}`}
            className="min-w-0 truncate text-sm font-medium text-foreground hover:underline"
          >
            {signal.company.name}
          </Link>
          {signal.strength && (
            <span className={cn("ml-auto shrink-0 text-xs", weak ? "text-muted-foreground" : "font-medium text-primary")}>
              {weak ? "Słaby, do wzmianki w rozmowie" : SIGNAL_STRENGTH_LABELS[signal.strength]}
            </span>
          )}
        </div>
        <TruncatedText className="block max-w-full text-xs text-muted-foreground">{signal.title}</TruncatedText>
      </div>
      <Link href={LEADS} className="shrink-0 text-xs text-primary hover:underline">
        Sprawdź
      </Link>
    </li>
  );
}

/** Sekcja nad ofertami (G3): najwyżej trzy nowe sygnały u firm tej osoby. */
export function MyDaySignals({ signals }: { signals: readonly MyDaySignal[] }) {
  if (signals.length === 0) return null;
  return (
    <section>
      <header className="flex items-baseline justify-between gap-3 border-b border-border bg-muted/40 px-3 py-1">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Nowe sygnały</h2>
        <Link href={LEADS} className="text-xs text-primary hover:underline">
          Wszystkie w Leadach
        </Link>
      </header>
      <ul className="divide-y divide-border border-b border-border">
        {signals.map((signal) => (
          <SignalRow key={signal.lead_id} signal={signal} />
        ))}
      </ul>
    </section>
  );
}
