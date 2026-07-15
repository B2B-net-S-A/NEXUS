"use client"

// Foundation verification harness: renders every design token as a swatch and
// lets you flip palette / dark / soft / kids to confirm nothing is broken or
// empty across the theme matrix. Sets html attributes directly (raw CSS test).

const SEMANTIC = [
  "background", "foreground", "card", "card-foreground", "popover", "popover-foreground",
  "primary", "primary-foreground", "secondary", "secondary-foreground",
  "muted", "muted-foreground", "accent", "accent-foreground",
  "destructive", "destructive-foreground", "border", "input", "ring",
  "success", "success-foreground", "success-muted", "success-muted-foreground",
  "warning", "warning-foreground", "warning-muted", "warning-muted-foreground",
  "destructive-muted", "destructive-muted-foreground",
  "info", "info-foreground", "info-muted", "info-muted-foreground",
]
const BRAND = ["brand-linkedin", "brand-linkedin-foreground"]
const SIDEBAR = [
  "sidebar", "sidebar-foreground", "sidebar-muted", "sidebar-border",
  "sidebar-accent", "sidebar-accent-foreground", "sidebar-ring",
]
const CHART = ["chart-1", "chart-2", "chart-3", "chart-4", "chart-5"]
const PALETTES = ["indigo", "violet", "blue", "green", "orange", "rose", "graphite"]

function set(attr: "theme" | "dark" | "soft" | "kids", value?: string) {
  const el = document.documentElement
  if (attr === "theme") el.dataset.theme = value
  if (attr === "dark") el.classList.toggle("dark")
  if (attr === "soft") el.dataset.soft = el.dataset.soft === "true" ? "false" : "true"
  if (attr === "kids") el.dataset.kids = el.dataset.kids === "true" ? "false" : "true"
}

function Swatch({ token }: { token: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="h-12 w-full rounded-md border border-border"
        style={{ background: `hsl(var(--${token}))` }}
      />
      <code className="text-[11px] text-muted-foreground">--{token}</code>
    </div>
  )
}

function Group({ title, tokens }: { title: string; tokens: string[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {tokens.map((t) => (
          <Swatch key={t} token={t} />
        ))}
      </div>
    </section>
  )
}

export default function TokensPreview() {
  return (
    <div className="min-h-screen bg-background app-shell-root">
      <div className="mx-auto max-w-[1100px] space-y-8 px-6 py-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Design tokens</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Harness weryfikacji fundamentu — przełącz tryby i sprawdź, że żaden swatch nie jest pusty.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3">
          <span className="text-xs font-medium text-muted-foreground">Paleta:</span>
          {PALETTES.map((p) => (
            <button
              key={p}
              onClick={() => set("theme", p)}
              className="rounded-md border border-border px-2.5 py-1 text-xs capitalize hover:bg-accent"
            >
              {p}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-border" />
          {(["dark", "soft", "kids"] as const).map((m) => (
            <button
              key={m}
              onClick={() => set(m)}
              className="rounded-md border border-border px-2.5 py-1 text-xs capitalize hover:bg-accent"
            >
              toggle {m}
            </button>
          ))}
        </div>

        <Group title="Semantyczne" tokens={SEMANTIC} />
        <Group title="Marka" tokens={BRAND} />
        <Group title="Sidebar" tokens={SIDEBAR} />
        <Group title="Chart" tokens={CHART} />
      </div>
    </div>
  )
}
