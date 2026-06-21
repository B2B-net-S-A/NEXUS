"use client"

import { SidebarV2 } from "@/components/v2/shell/SidebarV2"

// Harness do wizualnej weryfikacji reskinu app-shella (Wave 1). Renderuje
// prawdziwy SidebarV2; stany active/hover najlepiej widać w realnej aplikacji
// po zalogowaniu (tu pathname = /preview/shell, więc żaden item nie jest aktywny).
export default function ShellPreview() {
  return (
    <div className="flex h-screen bg-background app-shell-root">
      <SidebarV2 />
      <main className="flex-1 overflow-auto p-10">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Podgląd app-shella</h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Sidebar zreskinowany na estetykę Tailwind Plus: stany nawigacji na tokenie{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">--sidebar-accent</code>, aktywny item jako
          indygo-pill (<code className="rounded bg-muted px-1 py-0.5 text-xs">bg-primary/10 text-primary</code>),
          focus-ring na <code className="rounded bg-muted px-1 py-0.5 text-xs">--sidebar-ring</code>. Cała logika
          (collapse/pin, role-gating, badge counts, mobile, kids) zachowana.
        </p>
      </main>
    </div>
  )
}
