"use client";

import Link from "next/link";
import { RequireRole } from "@/components/RequireRole";
import { readUiFlagClient, setUiFlagClient } from "@/lib/ui-flag";
import { useEffect, useState } from "react";

/**
 * V2 UI Showcase — admin-gated single-page render of every v2 primitive and
 * page fragment. Grows across phases; each phase appends its section here so
 * Playwright can snapshot regressions in one place.
 *
 * Phase 0: placeholder — verifies tokens, fonts, cookie flag flip.
 * Phase 1: will add Buttons/Inputs/Forms/Cards/Badges/Tables/Modals/Sheets/Command.
 * Phase 2+: will add shell fragments, dashboard, lists.
 */
export default function V2ShowcasePage() {
  const [ui, setUi] = useState<"v1" | "v2" | "loading">("loading");

  useEffect(() => {
    setUi(readUiFlagClient());
  }, []);

  const flipTo = (next: "v1" | "v2") => {
    setUiFlagClient(next);
    window.location.reload();
  };

  return (
    <RequireRole
      minRole="admin"
      fallback={<div className="p-6 text-sm text-gray-500">Widok tylko dla admin.</div>}
    >
      <div className="mx-auto max-w-6xl p-8 space-y-10">
        <header className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
            Dynaminds · Nexus v2
          </p>
          <h1 className="text-3xl font-extrabold tracking-[-0.02em] text-[hsl(var(--text-title))] font-[var(--font-poppins)]">
            UI Showcase
          </h1>
          <p className="text-sm text-[hsl(var(--text-body))] max-w-2xl">
            Single-scroll render of every primitive and page fragment in the v2
            redesign. Growing across phases. Current phase: <strong>0 — Foundation</strong>.
          </p>

          <div className="mt-4 flex items-center gap-3 text-sm">
            <span className="inline-flex items-center rounded-full border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] px-3 py-1 font-medium">
              Active flag: <code className="ml-1 font-mono">{ui}</code>
            </span>
            {ui !== "loading" && (
              <button
                type="button"
                onClick={() => flipTo(ui === "v2" ? "v1" : "v2")}
                className="inline-flex items-center rounded-lg bg-[hsl(var(--accent))] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[hsl(var(--accent-strong))] transition-colors"
              >
                Flip to {ui === "v2" ? "v1" : "v2"}
              </button>
            )}
            <Link
              href="/settings"
              className="text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))]"
            >
              ← Ustawienia
            </Link>
          </div>
        </header>

        {/* ── 1. Colors ─────────────────────────────────────────────────── */}
        <section className="space-y-4">
          <h2 className="text-xl font-bold text-[hsl(var(--text-title))] font-[var(--font-poppins)]">
            1. Colors &amp; tokens
          </h2>

          <div className="space-y-6">
            <SwatchGroup
              title="Deep Plum (chrome — sidebar, topbar, headings)"
              swatches={[
                ["plum-50", "#F7F5F6"],
                ["plum-100", "#EAE6E9"],
                ["plum-200", "#CEC6CD"],
                ["plum-300", "#B1A5AF"],
                ["plum-400", "#87778C"],
                ["plum-500", "#5A4B5A"],
                ["plum-600", "#433644"],
                ["plum-700", "#2E1A2B"],
                ["plum-800", "#1F1220"],
                ["plum-900", "#15090E"],
                ["plum-950", "#0A0407"],
              ]}
            />
            <SwatchGroup
              title="Burgundy (accent — CTAs, active states, alerts)"
              swatches={[
                ["burgundy-50", "#FBF2F3"],
                ["burgundy-100", "#F4DDE0"],
                ["burgundy-200", "#E9B9BF"],
                ["burgundy-300", "#DB939B"],
                ["burgundy-400", "#C16F7B"],
                ["burgundy-500", "#A63A4A"],
                ["burgundy-600", "#8B1A2B"],
                ["burgundy-700", "#6B1120"],
                ["burgundy-800", "#4D0A16"],
                ["burgundy-900", "#310711"],
                ["burgundy-950", "#1A0308"],
              ]}
            />
            <SwatchGroup
              title="Warm Cream (canvas — body bg)"
              swatches={[
                ["cream-50", "#FBF9F6"],
                ["cream-100", "#F8F5EF"],
                ["cream-200", "#F0EBE3"],
                ["cream-300", "#E8E4DE"],
                ["cream-400", "#D8CFBF"],
                ["cream-500", "#B5AA9A"],
                ["cream-600", "#92897B"],
                ["cream-700", "#6F685E"],
                ["cream-800", "#4C4841"],
                ["cream-900", "#2A2824"],
                ["cream-950", "#15130F"],
              ]}
            />
          </div>

          <div className="pt-2">
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[hsl(var(--text-muted))] mb-3">
              Semantic aliases
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <SemanticSwatch name="canvas" varName="--bg-canvas" />
              <SemanticSwatch name="surface" varName="--bg-surface" />
              <SemanticSwatch name="chrome" varName="--bg-chrome" />
              <SemanticSwatch name="accent" varName="--accent" />
              <SemanticSwatch name="accent-strong" varName="--accent-strong" />
              <SemanticSwatch name="accent-soft" varName="--accent-soft" />
              <SemanticSwatch name="subtle (border)" varName="--border-subtle" />
              <SemanticSwatch name="muted (text)" varName="--text-muted" />
            </div>
          </div>
        </section>

        {/* ── 2. Typography ───────────────────────────────────────────── */}
        <section className="space-y-4">
          <h2 className="text-xl font-bold text-[hsl(var(--text-title))] font-[var(--font-poppins)]">
            2. Typography
          </h2>
          <div className="space-y-3 bg-[hsl(var(--bg-surface))] p-6 rounded-[1rem] border border-[hsl(var(--border-subtle))]">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
              Eyebrow · Poppins 600 · tracking 0.22em
            </p>
            <h1
              className="font-[var(--font-poppins)] font-extrabold text-[hsl(var(--text-title))]"
              style={{ fontSize: "clamp(2.88rem, 4.49vw, 7.58rem)", lineHeight: 1.02, letterSpacing: "-0.025em" }}
            >
              Define tomorrow.
            </h1>
            <h2 className="font-[var(--font-poppins)] font-extrabold text-3xl text-[hsl(var(--text-title))] tracking-[-0.02em]">
              Heading 2 — the trinity
            </h2>
            <h3 className="font-[var(--font-poppins)] font-bold text-2xl text-[hsl(var(--text-title))]">
              Heading 3 — chamber tint
            </h3>
            <h4 className="font-[var(--font-poppins)] font-semibold text-xl text-[hsl(var(--text-title))]">
              Heading 4 — subsection
            </h4>
            <p className="font-[var(--font-inter)] text-base text-[hsl(var(--text-body))]">
              Body · Inter 400 · Pasywna obrona to za mało. Dostarczamy proaktywny Offensive &amp;
              Intel. Nie czekamy, aż ktoś nas złamie — działamy pierwsi.
            </p>
            <p className="font-[var(--font-inter)] text-sm text-[hsl(var(--text-muted))]">
              Muted body · Inter 400 · We don&apos;t do standard. We set the standard.
            </p>
          </div>
        </section>

        {/* ── Phase roadmap placeholder ────────────────────────────── */}
        <section className="space-y-3 border-t border-[hsl(var(--border-subtle))] pt-6">
          <h2 className="text-xl font-bold text-[hsl(var(--text-title))] font-[var(--font-poppins)]">
            Roadmap — sekcje dodawane w kolejnych fazach
          </h2>
          <ul className="text-sm text-[hsl(var(--text-body))] space-y-1 list-disc pl-5">
            <li>Phase 1 — Buttons · Inputs · Forms · Cards · Badges · Tables · Modals · Sheets · Command</li>
            <li>Phase 2 — AppShellV2 · SidebarV2 · TopbarV2 · Breadcrumb · Command palette</li>
            <li>Phase 3 — DashboardV2 layout fragment</li>
            <li>Phase 4 — CandidatesListV2 virtualized table + side sheet</li>
            <li>Phase 5 — CandidateDetailV2 tabs + widgets</li>
            <li>Phase 6+ — Clients · Jobs · Contracts · Kanban · Forms · Share portal</li>
          </ul>
        </section>
      </div>
    </RequireRole>
  );
}

// ── helpers ────────────────────────────────────────────────────────────

function SwatchGroup({
  title,
  swatches,
}: {
  title: string;
  swatches: [string, string][];
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[hsl(var(--text-muted))] mb-2">
        {title}
      </h3>
      <div className="grid grid-cols-6 md:grid-cols-11 gap-1.5">
        {swatches.map(([name, hex]) => (
          <div key={name} className="space-y-1">
            <div
              className="aspect-square rounded-md border border-[hsl(var(--border-subtle))]"
              style={{ background: hex }}
              title={`${name} · ${hex}`}
            />
            <div className="text-[10px] font-mono text-[hsl(var(--text-muted))] truncate">
              {name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SemanticSwatch({ name, varName }: { name: string; varName: string }) {
  return (
    <div className="rounded-lg border border-[hsl(var(--border-subtle))] overflow-hidden">
      <div
        className="h-12"
        style={{ background: `hsl(var(${varName}))` }}
        aria-label={name}
      />
      <div className="px-3 py-2">
        <div className="text-xs font-semibold text-[hsl(var(--text-title))]">{name}</div>
        <code className="text-[10px] font-mono text-[hsl(var(--text-muted))]">
          hsl(var({varName}))
        </code>
      </div>
    </div>
  );
}
