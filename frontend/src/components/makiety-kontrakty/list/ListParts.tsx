"use client";
// Wspólne kawałki makiet listy: nagłówek strony, pigułki zbiorów, adresy.
import Link from "next/link";
import { Download, LineChart, Mail, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useMkQuickCounts } from "../shared/data";

export type ListView = "aktywne" | "konczace";

export function listHref(w: "a" | "b", view: ListView, contract?: number | null): string {
  const p = new URLSearchParams({ w, widok: view });
  if (contract) p.set("contract", String(contract));
  return `/contracts/makieta-lista?${p.toString()}`;
}

export function PageTitleRow({ stats }: { stats: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="text-[22px] font-semibold tracking-tight text-foreground">Kontrakty</h1>
        <p className="truncate text-[13px] text-muted-foreground">{stats}</p>
      </div>
      <div className="flex items-center gap-1.5">
        <Button type="button" variant="ghost" size="sm">
          <LineChart className="mr-1.5 size-3.5" aria-hidden />
          Analityka
        </Button>
        <Button type="button" variant="ghost" size="sm">
          <Download className="mr-1.5 size-3.5" aria-hidden />
          Eksport
        </Button>
        <Button type="button" variant="primary" size="sm">
          <Plus className="mr-1 size-3.5" aria-hidden />
          Nowy kontrakt
        </Button>
      </div>
    </div>
  );
}

export function MailButton() {
  return (
    <Button type="button" variant="outline" size="sm" title="Zamówienia z maila do weryfikacji">
      <Mail className="mr-1.5 size-3.5" aria-hidden />
      Zamówienia z maila
      <span className="ml-1.5 rounded-full bg-primary px-1.5 text-[11px] font-semibold text-primary-foreground">4</span>
    </Button>
  );
}

/** Pigułki zbiorów — kolejność: najczęstszy zbiór pierwszy. */
export function QuickPills({ w, view, compact = false }: { w: "a" | "b"; view: ListView; compact?: boolean }) {
  const counts = useMkQuickCounts();
  const pills: { key: string; label: string; count: number | null; href?: string; active: boolean }[] = [
    { key: "aktywne", label: "Aktywne", count: counts.active, href: listHref(w, "aktywne"), active: view === "aktywne" },
    { key: "konczace", label: "Kończące się", count: counts.ending, href: listHref(w, "konczace"), active: view === "konczace" },
    { key: "drafts", label: "Do uzupełnienia", count: counts.drafts, active: false },
    { key: "rate-doc", label: "Stawka z dokumentu", count: 0, active: false },
    { key: "all", label: "Wszystkie", count: counts.all, active: false },
  ];
  if (compact) {
    return (
      <div role="tablist" aria-label="Zbiór kontraktów" className="inline-flex shrink-0 rounded-lg border border-border bg-muted/50 p-0.5">
        {pills
          .filter((p) => p.key !== "rate-doc")
          .map((p) => {
            const body = (
              <>
                {p.label}
                <span className={cn("ml-1 tabular-nums", p.active ? "text-muted-foreground" : "text-muted-foreground/70")}>{p.count ?? "…"}</span>
              </>
            );
            const cls = cn(
              "rounded-md px-2.5 py-1 text-[12.5px] font-medium whitespace-nowrap",
              p.active ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
            );
            return p.href ? (
              <Link key={p.key} href={p.href} role="tab" aria-selected={p.active} className={cls}>
                {body}
              </Link>
            ) : (
              <span key={p.key} role="tab" aria-selected={false} className={cls}>
                {body}
              </span>
            );
          })}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {pills.map((p) => {
        const body = (
          <>
            {p.label}
            <span
              className={cn(
                "rounded-full px-1.5 text-[11px] tabular-nums",
                p.active ? "bg-primary text-primary-foreground" : p.count === 0 ? "text-muted-foreground/60" : "bg-muted text-muted-foreground",
              )}
            >
              {p.count ?? "…"}
            </span>
          </>
        );
        const cls = cn(
          "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] font-medium",
          p.active ? "border-primary/40 bg-primary/8 text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
        );
        return p.href ? (
          <Link key={p.key} href={p.href} className={cls} aria-current={p.active ? "page" : undefined}>
            {body}
          </Link>
        ) : (
          <span key={p.key} className={cls}>
            {body}
          </span>
        );
      })}
    </div>
  );
}
