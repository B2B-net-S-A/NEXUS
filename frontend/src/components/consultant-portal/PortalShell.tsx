"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** Rama strefy konsultanta: bez powłoki NEXUSA, pod telefon 390 px. */
export function PortalShell({
  name,
  onLogout,
  children,
}: {
  name?: string | null;
  onLogout?: () => void;
  children: ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3">
          <span className="text-sm font-semibold">
            B2B.net <span className="font-normal text-muted-foreground">· strefa konsultanta</span>
          </span>
          {onLogout ? (
            <Button size="sm" variant="ghost" onClick={onLogout}>
              Wyloguj
            </Button>
          ) : null}
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
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
