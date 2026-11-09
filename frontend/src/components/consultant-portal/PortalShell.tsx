"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** Rama strefy konsultanta: bez powłoki NEXUSA, pod telefon 390 px. */
export function PortalShell({
  name,
  onLogout,
  nav,
  children,
}: {
  name?: string | null;
  onLogout?: () => void;
  /** Menu panelu: po zalogowaniu ekran jest szerszy, bo ma kolumny. */
  nav?: ReactNode;
  children: ReactNode;
}) {
  const width = nav ? "max-w-6xl" : "max-w-3xl";
  return (
    <div className={`min-h-dvh text-foreground ${nav ? "bg-muted" : "bg-background"}`}>
      <header className="border-b bg-card">
        <div className={`mx-auto flex ${width} items-center justify-between gap-3 px-4 py-3`}>
          <span className="text-sm font-semibold">
            B2B.net <span className="font-normal text-muted-foreground">panel konsultanta</span>
          </span>
          {onLogout ? (
            <Button size="sm" variant="ghost" onClick={onLogout}>
              Wyloguj
            </Button>
          ) : null}
        </div>
        {nav ? <div className={`mx-auto ${width} px-2`}>{nav}</div> : null}
      </header>
      <main className={`mx-auto ${width} space-y-4 px-4 py-5`}>
        {name ? <span className="sr-only">Zalogowano: {name}</span> : null}
        {children}
      </main>
    </div>
  );
}

export function PortalNotice({
  title,
  children,
  tone = "neutral",
}: {
  title: string;
  children?: ReactNode;
  tone?: "neutral" | "error";
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={
        tone === "error"
          ? "rounded-xl border border-destructive/20 bg-destructive-muted p-4 text-sm text-destructive-muted-foreground"
          : "rounded-xl border bg-card p-4 text-sm"
      }
    >
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-1 text-muted-foreground">{children}</div> : null}
    </div>
  );
}
