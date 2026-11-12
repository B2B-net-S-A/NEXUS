"use client";

import { Bot, ExternalLink } from "lucide-react";
import { useState, type ReactNode } from "react";

import { safeHref } from "@/components/sales/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { DEFAULT_REJECT_REASONS } from "../signals/SignalActions";

/** Układ jak skrzynka sygnałów: lista po lewej, panel po prawej. */
export const INBOX_LAYOUT = "grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_380px]";

interface RowProps {
  selected: boolean;
  onSelect: () => void;
  title: ReactNode;
  sub: ReactNode;
  right: ReactNode;
}

export function InboxRow({ selected, onSelect, title, sub, right }: RowProps) {
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={cn(
          "grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 px-3 py-2 text-left leading-tight transition-colors hover:bg-muted/40",
          selected && "bg-primary/10 hover:bg-primary/10",
        )}
      >
        <span className="min-w-0">
          <span className="block truncate text-sm text-foreground">{title}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{sub}</span>
        </span>
        <span className="whitespace-nowrap text-right text-xs tabular-nums text-muted-foreground">{right}</span>
      </button>
    </li>
  );
}

/** Linia z ostatnim biegiem bota nad listą. */
export function RunLine({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      <span className="inline-flex h-4 items-center gap-1 rounded bg-primary/10 px-1.5 text-[10px] font-medium uppercase tracking-[0.06em] text-primary">
        <Bot className="size-3" aria-hidden />
        Bot
      </span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}

export function Panel({ children }: { children: ReactNode }) {
  return <Card className="space-y-3 p-3 lg:sticky lg:top-2">{children}</Card>;
}

export function Block({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-0.5">
      <h3 className="text-xs font-medium text-foreground">{label}</h3>
      {children}
    </section>
  );
}

/** Nagłówek bloku z oznaczeniem, że to wniosek bota, a nie fakt ze źródła. */
export function BotConclusion({ children }: { children: ReactNode }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      {children}
      <Badge variant="neutral" size="sm">
        wniosek bota, nie fakt
      </Badge>
    </span>
  );
}

export function SourceLink({ url }: { url: string | null | undefined }) {
  const href = safeHref(url);
  if (!href) return null;
  let host = href;
  try {
    host = new URL(href).hostname.replace(/^www\./, "");
  } catch {
    // zostaje pełny adres
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-0.5 text-xs text-primary hover:underline"
    >
      {host}
      <ExternalLink className="size-3" aria-hidden />
    </a>
  );
}

interface NotNowProps {
  reasons?: readonly string[];
  pending: boolean;
  onReject: (reason: string) => void;
}

/** „Nie teraz” z powodem z listy: powód wraca do bota tylko z tej listy. */
export function NotNow({ reasons = DEFAULT_REJECT_REASONS, pending, onReject }: NotNowProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="outline" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        Nie teraz
      </Button>
      {open && (
        <div className="basis-full space-y-1">
          <p className="text-xs font-medium text-foreground">Dlaczego nie teraz?</p>
          <div className="flex flex-wrap gap-1">
            {reasons.map((reason) => (
              <Button
                key={reason}
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                disabled={pending}
                onClick={() => onReject(reason)}
              >
                {reason}
              </Button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
