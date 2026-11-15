"use client";

// „Kto zna NEXUS” (Artur, 16.11.2026): rekruterzy × ważne funkcje, użycie
// w pracy z ostatnich 60 dni (`GET /api/novelties/poligon/luki`). Luki osoby
// to jej ćwiczenia na Poligonie; przycisk wysyła poligon z lukami z terminem.

import { useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { lukiKey, sendPoligonLuki, startKey, usePoligonLuki } from "@/lib/novelties/api";
import { formatLukiDue, type LukiMatrix } from "@/lib/novelties/logic";
import { cn } from "@/lib/utils";

function shortName(name: string): string {
  const [first, ...rest] = name.split(/\s+/).filter(Boolean);
  return [first, ...rest.map((r) => `${r[0]}.`)].join(" ");
}

export function KtoZnaNexus() {
  const query = usePoligonLuki();
  if (query.isError) {
    return (
      <p role="alert" className="rounded-lg border border-border bg-card p-4 text-sm text-destructive-text">
        {apiErrorMessage(query.error, "Nie udało się wczytać, kto zna NEXUS.")}
      </p>
    );
  }
  if (!query.isSuccess) {
    return <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">Liczę, kto zna NEXUS…</p>;
  }
  return <KtoZnaNexusView data={query.data} />;
}

export function KtoZnaNexusView({ data }: { data: LukiMatrix }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [sending, setSending] = useState(false);
  const groups = [...new Set(data.features.map((f) => f.group))];
  const total = data.people.length;
  const weakest = [...data.features].sort((a, b) => a.users - b.users).slice(0, 5);
  const withGaps = data.people.filter((p) => p.gaps > 0).length;

  const send = async () => {
    const ok = await askConfirm({
      title: `Wysłać poligon z lukami do ${withGaps} osób?`,
      description:
        "Każdy dostanie ćwiczenia z funkcji, których nie używa w pracy; resztę zaliczy mu praca z ostatnich 60 dni. Masz tydzień — po terminie NEXUS poprosi o nie przy wejściu (wyłącznik blokady Poligonu działa też tutaj).",
      confirmLabel: "Wyślij",
    });
    if (!ok) return;
    setSending(true);
    try {
      const sent = await sendPoligonLuki();
      showSuccess(`Wysłane do ${sent.people} osób, termin ${formatLukiDue(sent.due)}.`);
      await queryClient.invalidateQueries({ queryKey: lukiKey });
      await queryClient.invalidateQueries({ queryKey: startKey });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać poligonu z lukami."));
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label="Kto zna NEXUS">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">Kto zna NEXUS — praca z ostatnich {data.window_days} dni</p>
          <p className="text-xs text-muted-foreground">
            Kropka = osoba użyła funkcji w pracy ({total} rekruterów). Najsłabiej:{" "}
            {weakest.map((f) => `${f.label} (${f.users})`).join(", ")}.
            {data.campaign && <> Poligon z lukami wysłany, termin {formatLukiDue(data.campaign.due)}.</>}
          </p>
        </div>
        <Button size="sm" disabled={sending || withGaps === 0} onClick={() => void send()}>
          <Send className="h-3.5 w-3.5" aria-hidden="true" />
          {data.campaign ? "Wyślij ponownie" : "Wyślij poligon z lukami"} ({withGaps} osób)
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="sticky left-0 bg-card px-2 py-1 text-left font-medium">Osoba</th>
              {groups.map((g) => (
                <th
                  key={g}
                  colSpan={data.features.filter((f) => f.group === g).length}
                  className="border-l border-border px-1 py-1 text-left font-medium"
                >
                  {g}
                </th>
              ))}
              <th className="border-l border-border px-2 py-1 text-right font-medium">Luki</th>
              {data.campaign && <th className="px-2 py-1 text-right font-medium">Poligon</th>}
            </tr>
            <tr>
              <th className="sticky left-0 bg-card" />
              {groups.flatMap((g) =>
                data.features
                  .filter((f) => f.group === g)
                  .map((f, i) => (
                    <th
                      key={f.key}
                      title={f.label}
                      className={cn(
                        "h-36 w-6 overflow-hidden align-bottom font-normal text-muted-foreground",
                        i === 0 && "border-l border-border",
                      )}
                    >
                      <span className="inline-block max-h-36 rotate-180 overflow-hidden whitespace-nowrap [writing-mode:vertical-rl]">
                        {f.label}
                      </span>
                    </th>
                  )),
              )}
              <th className="border-l border-border" />
              {data.campaign && <th />}
            </tr>
          </thead>
          <tbody>
            {data.people.map((p) => (
              <tr key={p.id} className="border-t border-border/70">
                <td className="sticky left-0 whitespace-nowrap bg-card px-2 py-1">{shortName(p.name)}</td>
                {groups.flatMap((g) =>
                  data.features
                    .filter((f) => f.group === g)
                    .map((f, i) => (
                      <td key={f.key} className={cn("text-center", i === 0 && "border-l border-border")}>
                        {p.used.includes(f.key) ? (
                          <i className="inline-block h-2.5 w-2.5 rounded-full bg-success" aria-label={`${f.label}: używa`} />
                        ) : (
                          <i
                            className="inline-block h-2.5 w-2.5 rounded-full border border-destructive/60"
                            aria-label={`${f.label}: nie używa`}
                          />
                        )}
                      </td>
                    )),
                )}
                <td
                  className={cn(
                    "border-l border-border px-2 text-right tabular-nums",
                    p.gaps >= 8 && "font-semibold text-destructive-text",
                  )}
                >
                  {p.gaps}
                </td>
                {data.campaign && (
                  <td className="whitespace-nowrap px-2 text-right tabular-nums text-muted-foreground">
                    {p.poligon ? `${p.poligon.done} z ${p.poligon.total}` : "—"}
                  </td>
                )}
              </tr>
            ))}
            <tr className="border-t border-border text-muted-foreground">
              <td className="sticky left-0 bg-card px-2 py-1">Używa</td>
              {groups.flatMap((g) =>
                data.features
                  .filter((f) => f.group === g)
                  .map((f, i) => (
                    <td key={f.key} className={cn("text-center tabular-nums", i === 0 && "border-l border-border")}>
                      {f.users}
                    </td>
                  )),
              )}
              <td className="border-l border-border" />
              {data.campaign && <td />}
            </tr>
          </tbody>
        </table>
      </div>
      {confirmDialog}
    </section>
  );
}
