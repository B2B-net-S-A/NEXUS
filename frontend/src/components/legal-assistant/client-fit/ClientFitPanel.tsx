"use client";

// Panel „Sprawdzone z umową ramową <klient> i przepisami” (asystent prawny,
// część G, 25.11.2026) w kreatorze aneksu i w „Nowej umowie” Generatora.
// Sprawdzenie biegnie w tle po wgraniu umowy ramowej albo aneksu klienta;
// panel tylko czyta wynik. Każdy cytat sprawdził kod z tekstem źródła
// (ustalenie bez pokrycia odpada po stronie serwera). Bez podglądu kwot
// u klienta (403) panelu nie ma — treść umowy ramowej niesie stawki.

import { useState } from "react";
import { Check, ChevronDown, Loader2, Plus, Scale } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientFit, type ClientFitFinding } from "@/lib/api/legalClientFit";
import {
  affectedLabel,
  clientFitTitle,
  decideLabel,
  findingsCountLabel,
  gapsLabel,
  hasResult,
  panelFindings,
} from "@/lib/legal-client-fit";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

import { ClientFitDialog } from "./ClientFitDialog";
import { ClientFitStaleNote, ClientFitStatusNote } from "./ClientFitStatus";
import { LawyerBadge, QuoteText, RefChip, STATE_ICON, STATE_TONE } from "./parts";

export interface ClientFitPanelProps {
  clientId: number | null | undefined;
  /** Kreator aneksu „inna zmiana”: dopisuje zdanie do listy zmian. */
  onAddToAnnex?: (text: string) => void;
  /** Czy zdanie już stoi w treści aneksu (przycisk zmienia się w „Dodane”). */
  isAdded?: (text: string) => boolean;
  /** Zdanie zamiast przycisku, gdy treści nie da się dopisać w tym dokumencie. */
  addHint?: string;
  defaultOpen?: boolean;
  /** Harness bez sieci: bez odpytywania biegu w toku. */
  poll?: boolean;
}

export function ClientFitPanel({
  clientId,
  onAddToAnnex,
  isAdded,
  addHint,
  defaultOpen = true,
  poll = true,
}: ClientFitPanelProps) {
  const query = useClientFit(clientId, { poll });
  const [open, setOpen] = useState(defaultOpen);
  const [details, setDetails] = useState(false);

  if (!clientId) return null;
  if (query.isError && isForbiddenError(query.error)) return null;
  if (query.isError) {
    return (
      <Alert
        variant="error"
        title="Nie udało się wczytać sprawdzenia z umową ramową klienta"
        description={apiErrorMessage(query.error, "Spróbuj ponownie za chwilę.")}
      >
        <Button size="sm" variant="outline" className="mt-2" onClick={() => void query.refetch()}>
          Ponów
        </Button>
      </Alert>
    );
  }
  if (!query.isSuccess) {
    return (
      <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        Wczytuję sprawdzenie z umową ramową klienta…
      </p>
    );
  }

  const data = query.data;
  const done = hasResult(data);
  const items = done ? panelFindings(data.findings) : [];
  const subtitle = [
    data.sources.map((s) => s.name).join(" + ") || null,
    data.template_label || null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      aria-label="Sprawdzenie z umową ramową klienta"
      className="overflow-hidden rounded-xl border border-border bg-card shadow-xs"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="relative flex w-full items-center gap-3 py-2.5 pl-4 pr-3 text-left"
      >
        <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
        <Scale className="size-4 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold leading-5">{clientFitTitle(data.client_name)}</p>
          {subtitle ? (
            <p className="truncate text-[12.5px] leading-5 text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        {done && data.counts.gap > 0 ? (
          <Badge variant="danger" size="sm">
            {gapsLabel(data.counts.gap)}
          </Badge>
        ) : null}
        {done && data.counts.decide > 0 ? (
          <Badge variant="warning" size="sm">
            {decideLabel(data.counts.decide)}
          </Badge>
        ) : null}
        <ChevronDown
          className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open ? (
        <div className="border-t border-border">
          {!done ? (
            <div className="px-4 py-2.5">
              <ClientFitStatusNote data={data} />
            </div>
          ) : (
            <>
              {data.stale ? (
                <div className="px-4 pt-2.5">
                  <ClientFitStaleNote data={data} />
                </div>
              ) : null}
              {items.length ? (
                <ul className="divide-y divide-border/70">
                  {items.map((finding) => (
                    <FindingRow
                      key={finding.id}
                      finding={finding}
                      onAddToAnnex={onAddToAnnex}
                      added={finding.annex_text ? (isAdded?.(finding.annex_text) ?? false) : false}
                    />
                  ))}
                </ul>
              ) : (
                <p className="px-4 py-2.5 text-[12.5px] text-muted-foreground">
                  Sprawdzenie nie znalazło w umowie ramowej wymogów, które dałoby się porównać z naszym wzorem.
                </p>
              )}
              {addHint && !onAddToAnnex && data.counts.gap > 0 ? (
                <p className="border-t border-border/70 px-4 py-2 text-[12px] text-muted-foreground">{addHint}</p>
              ) : null}
            </>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border/70 px-4 py-2">
            <p className="mr-auto text-[11.5px] text-muted-foreground">
              {data.disclaimer || "Asystent nie jest poradą prawną."}
            </p>
            {done && data.findings.length ? (
              <Button
                size="sm"
                variant="tertiary"
                className="h-7 px-0 text-[12px]"
                onClick={() => setDetails(true)}
              >
                Szczegóły ({findingsCountLabel(data.findings.length)})
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
      {details ? (
        <ClientFitDialog clientId={data.client_id} open={details} onOpenChange={setDetails} />
      ) : null}
    </section>
  );
}

function FindingRow({
  finding,
  onAddToAnnex,
  added,
}: {
  finding: ClientFitFinding;
  onAddToAnnex?: (text: string) => void;
  added: boolean;
}) {
  const Icon = STATE_ICON[finding.state];
  const annexText = finding.annex_text;
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1.5 px-4 py-2.5" data-state={finding.state}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", STATE_TONE[finding.state])} aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-[13px] font-medium leading-5">
          {finding.topic_label}
          {finding.summary ? (
            <span className="font-normal text-muted-foreground"> — {finding.summary}</span>
          ) : null}
        </p>
        <div className="space-y-0.5">
          <QuoteText text={finding.client_quote} clamp />
          <div className="flex flex-wrap items-center gap-1">
            <RefChip kind="client" label={finding.client_ref} />
            {finding.our_ref ? (
              <RefChip kind="ours" label={`nasza umowa ${finding.our_ref}`} />
            ) : (
              <span className="text-[11.5px] font-medium text-destructive">brak w naszej umowie</span>
            )}
            <LawyerBadge reasons={finding.lawyer_review} />
          </div>
        </div>
        {finding.state !== "ok" ? (
          <p className="text-[12px] text-muted-foreground">
            {finding.next_step ? `${finding.next_step} · ` : ""}
            {affectedLabel(finding.affected_contracts)}
          </p>
        ) : null}
      </div>
      {onAddToAnnex && annexText && finding.state !== "ok" ? (
        <Button
          size="sm"
          variant="outline"
          className="h-7 shrink-0 text-[12px]"
          disabled={added}
          onClick={() => onAddToAnnex(annexText)}
        >
          {added ? (
            <>
              <Check className="h-3 w-3" aria-hidden /> Dodane do aneksu
            </>
          ) : (
            <>
              <Plus className="h-3 w-3" aria-hidden /> Dodaj do treści aneksu
            </>
          )}
        </Button>
      ) : null}
    </li>
  );
}
