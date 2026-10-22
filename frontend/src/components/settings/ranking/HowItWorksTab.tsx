"use client";

import type { RankingPanelState } from "@/lib/api";
import { cn } from "@/lib/utils";

import { BASE_LAYERS } from "./rankingMath";
import { LAYER_COLORS, LAYER_HINTS, LAYER_LABELS } from "./rankingCopy";

const STEPS = [
  {
    title: "Bramki — kogo ukrywamy",
    items: [
      "brak umiejętności krytycznej (0–3 wybiera DL) — nigdzie w profilu, CV ani notatkach",
      "brak jakichkolwiek danych: bez CV, umiejętności i notatek",
      "„tylko umowa o pracę” z notatek",
      "„tylko zdalnie” albo inne miasto — tylko gdy ≥ 4 dni w biurze",
    ],
    note: "Wszystko inne to plakietka, nie ukrycie.",
  },
  {
    title: "Ocena „Dop.” — tu działają wagi",
    text: "Każdy dostaje punkty z kilku składników (niżej). Suma to procent w kolumnie „Dop.”.",
    note: "Bez modelu językowego — ocena jest liczona wzorem, AI pisze tylko uzasadnienie.",
    accent: true,
  },
  {
    title: "Kolejność",
    items: [
      "od najwyższego „Dop.”",
      "osoby z brakującymi danymi na końcu",
      "osoby już w tej rekrutacji znikają z listy",
    ],
  },
] as const;

const WHERE: { place: string; on: "tak" | "nie" | "—"; note: string }[] = [
  { place: "„Szukaj w bazie” i „Szukaj ręcznie” w rekrutacji", on: "tak", note: "kolumna „Dop.” i kolejność" },
  {
    place: "„Przeszukaj całą bazę (AI)” i Talent Radar",
    on: "tak",
    note: "otwarte wyniki trzeba przeliczyć po zmianie",
  },
  { place: "Nocne „Propozycje z bazy”", on: "tak", note: "od następnej nocy" },
  {
    place: "Propozycje przy nowym CV albo nowej rekrutacji",
    on: "tak",
    note: "od 21.10.2026 liczone jak „Dop.”, z własnym progiem",
  },
  {
    place: "Lista „Kandydaci” bez rekrutacji",
    on: "—",
    note: "bez oceny; najpierw „Mile widziane”, potem podobieństwo",
  },
];

export function HowItWorksTab({ state }: { state: RankingPanelState }) {
  const shares = state.published.shares;
  const threshold = state.published.weights.threshold;
  return (
    <div className="space-y-5">
      <section
        aria-labelledby="ranking-flow"
        className="space-y-4 rounded-xl border border-border bg-card p-5"
      >
        <h2 id="ranking-flow" className="text-base font-semibold text-foreground">
          Co się dzieje po kliknięciu „Szukaj w bazie”
        </h2>
        <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-3.5",
                "accent" in step && step.accent ? "border-2 border-primary" : "border-border",
              )}
            >
              <StepNumber value={index + 1} strong={"accent" in step && step.accent} />
              <h3 className="text-sm font-semibold text-foreground">{step.title}</h3>
              {"items" in step && (
                <ul className="list-disc space-y-1 pl-4 text-sm text-muted-foreground">
                  {step.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
              {"text" in step && <p className="text-sm text-muted-foreground">{step.text}</p>}
              {"note" in step && step.note && (
                <p className="text-xs text-muted-foreground">{step.note}</p>
              )}
            </li>
          ))}
          <li className="flex flex-col gap-2 rounded-lg border border-border p-3.5">
            <StepNumber value={4} />
            <h3 className="text-sm font-semibold text-foreground">Nocne propozycje</h3>
            <ul className="list-disc space-y-1 pl-4 text-sm text-muted-foreground">
              <li>
                „Dop.” ≥ <b className="text-foreground">{threshold}%</b>
              </li>
              <li>i co najmniej jedna wymagana umiejętność</li>
            </ul>
            <p className="text-xs text-muted-foreground">
              Zmiana wag zmienia też, ile osób przekroczy próg.
            </p>
          </li>
        </ol>
      </section>

      <section
        aria-labelledby="ranking-layers"
        className="space-y-3.5 rounded-xl border border-border bg-card p-5"
      >
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 id="ranking-layers" className="flex-1 text-base font-semibold text-foreground">
            Z czego składa się „Dop.” — stan na dziś
          </h2>
          <span className="text-xs text-muted-foreground">udział w ocenie po przeliczeniu</span>
        </div>
        <ShareBar shares={shares} />
        <ul className="space-y-3">
          {BASE_LAYERS.map((layer) => (
            <li
              key={layer}
              className="grid grid-cols-[minmax(0,15rem)_3.5rem] gap-x-4 gap-y-0.5 md:grid-cols-[minmax(0,15rem)_3.5rem_minmax(0,1fr)]"
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", LAYER_COLORS[layer])} aria-hidden />
                {LAYER_LABELS[layer]}
              </span>
              <span
                className={cn(
                  "text-sm font-semibold tabular-nums",
                  layer === "salary" || layer === "availability"
                    ? "text-muted-foreground"
                    : "text-foreground",
                )}
              >
                {Math.round(shares[layer])}%
              </span>
              <span className="col-span-2 text-sm text-muted-foreground md:col-span-1">
                {LAYER_HINTS[layer]}
              </span>
            </li>
          ))}
        </ul>
        <p className="rounded-lg bg-muted px-3 py-2.5 text-sm text-muted-foreground">
          Do tego kara za za mało lat doświadczenia względem Championa: −8% oceny za każdy
          brakujący rok ponad 1, najwyżej −32%.
        </p>
      </section>

      <section
        aria-labelledby="ranking-where"
        className="space-y-3 rounded-xl border border-border bg-card p-5"
      >
        <h2 id="ranking-where" className="text-base font-semibold text-foreground">
          Gdzie działają wagi z tego ekranu
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Miejsce</th>
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Wagi</th>
                <th scope="col" className="border-b border-border px-2.5 py-2 font-semibold">Uwagi</th>
              </tr>
            </thead>
            <tbody>
              {WHERE.map((row) => (
                <tr key={row.place} className="border-b border-border last:border-0">
                  <td className="px-2.5 py-2 text-foreground">{row.place}</td>
                  <td
                    className={cn(
                      "px-2.5 py-2 font-semibold",
                      row.on === "tak"
                        ? "text-success"
                        : row.on === "nie"
                          ? "text-warning-muted-foreground"
                          : "text-muted-foreground",
                    )}
                  >
                    {row.on}
                  </td>
                  <td className="px-2.5 py-2 text-muted-foreground">{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {state.scoped_profiles.length > 0 && (
          <p className="rounded-lg border border-warning/30 bg-warning-muted px-3 py-2.5 text-sm text-warning-muted-foreground">
            Wagi ogólne nie działają tam, gdzie administrator ustawił profil klienta albo osoby:{" "}
            {state.scoped_profiles.map((p) => p.name).join(", ")}.
          </p>
        )}
      </section>
    </div>
  );
}

function StepNumber({ value, strong = false }: { value: number; strong?: boolean }) {
  return (
    <span
      className={cn(
        "flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold",
        strong ? "bg-primary text-primary-foreground" : "bg-primary/10 text-primary",
      )}
      aria-hidden
    >
      {value}
    </span>
  );
}

export function ShareBar({ shares }: { shares: Record<string, number> }) {
  return (
    <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden>
      {(["semantic", "skills", "location", "salary"] as const).map((layer) => (
        <div
          key={layer}
          className={cn("h-full transition-[width] duration-200", LAYER_COLORS[layer])}
          style={{ width: `${shares[layer] ?? 0}%` }}
        />
      ))}
    </div>
  );
}
