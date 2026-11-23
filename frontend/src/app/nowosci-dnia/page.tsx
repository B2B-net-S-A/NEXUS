"use client";

// Poranna porcja nowości (decyzja Artura 18.11.2026). Lista tego, co weszło do
// roli osoby i czego jeszcze nie przeszła. Każda pozycja to przeklikanie na
// Poligonie — prawdziwe ekrany, rekrutacja ćwiczebna, zapisy wyłączone — a po
// ostatnim kroku karta wraca tutaj. Po komplecie NEXUS do jutra niczego nie
// pokazuje. Zatrzymuje `useDailyNoveltyGate`, dane: `GET /api/novelties/daily`.

import { CheckCircle2, Circle, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";

import { startNoveltyPractice } from "@/components/novelties/NoveltyLayer";
import { Button } from "@/components/ui/button";
import { useDailyStatus } from "@/lib/novelties/api";
import { minutesFor, withSteps } from "@/lib/novelties/daily";
import { useAuthStore } from "@/store/auth";

const DAY_FORMAT = new Intl.DateTimeFormat("pl-PL", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Europe/Warsaw",
});

function stepsLabel(count: number): string {
  if (count === 1) return "Pokaż na ekranie";
  return `Przeklikaj · ${count} ${count <= 4 ? "kroki" : "kroków"}`;
}

export default function DailyNoveltiesPage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const status = useDailyStatus(hydrated && Boolean(user));

  if (!status) return null;
  const batch = status.items.map(withSteps);
  const left = batch.filter((n) => !n.done);
  const next = left[0] ?? null;

  return (
    <div className="mx-auto max-w-3xl space-y-5 pb-40">
      <header className="space-y-1">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary">
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          Nowości na dziś
        </p>
        <h1 className="text-2xl font-semibold text-foreground">
          {left.length === 0
            ? "Gotowe na dziś"
            : left.length < batch.length
              ? `Jeszcze ${left.length} z ${batch.length}`
              : `Najpierw ${batch.length === 1 ? "jedna nowość" : `${batch.length} nowości`} w NEXUSIE`}
        </h1>
        <p className="text-sm text-muted-foreground">
          {left.length > 0
            ? `Przeklikujesz na rekrutacji ćwiczebnej — prawdziwe ekrany, nic się nie zapisze. Ok. ${minutesFor(left)} min, potem do jutra nic nie wyskakuje.`
            : batch.length > 0
              ? "Wszystko przeklikane. Do jutra NEXUS nie pokaże Ci żadnej nowości."
              : "Nic nowego w NEXUSIE od ostatniego razu."}
        </p>
      </header>

      {batch.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            {status.done} z {status.total}
          </p>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${(status.done / Math.max(1, status.total)) * 100}%` }}
            />
          </div>
        </div>
      ) : null}

      {batch.length > 0 ? (
        <ol className="divide-y divide-border rounded-lg border border-border bg-card">
          {batch.map((n) => (
            <li key={n.id} className="flex gap-3 px-4 py-3" data-testid="daily-novelty">
              {n.done ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
              ) : (
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <p className="text-sm font-semibold leading-snug">{n.title}</p>
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                    {DAY_FORMAT.format(new Date(`${n.shipped_on}T12:00:00Z`))}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{n.why}</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{n.where}</p>
              </div>
              <div className="shrink-0 self-center">
                {n.done ? (
                  <span className="text-xs font-medium text-success">Przeklikane</span>
                ) : (
                  <Button
                    size="sm"
                    variant={next?.id === n.id ? "primary" : "outline"}
                    onClick={() => startNoveltyPractice(n)}
                  >
                    {stepsLabel(n.steps.length)}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ol>
      ) : null}

      {left.length === 0 ? (
        <Button onClick={() => router.push("/dashboard")}>Dalej do NEXUSA →</Button>
      ) : null}
    </div>
  );
}
