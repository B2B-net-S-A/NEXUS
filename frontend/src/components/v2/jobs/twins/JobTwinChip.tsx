"use client";

/**
 * Bliźniaki na widocznym pasku „Kandydaci do dodania” (0614, 28.10.2026;
 * wyjęte z menu „Szukaj ▾” 10.11.2026, bo Olaf (HoR) nie znalazł, gdzie
 * ręcznie połączyć wybrane rekrutacje).
 *
 * „⇄ ZOB-2964 · 3 pary”: numer otwiera bliźniaka, „N pary” (DL tej
 * rekrutacji, HoR, admin) — okno porównania, gdzie poprawia się pary pytań.
 * „⇄ Połącz bliźniaka” (ci sami, do limitu) otwiera okno bez wskazanej
 * rekrutacji: otwarte podobne albo wyszukiwarka dowolnej otwartej. Rekruter
 * bez bliźniaka nie widzi nic. W rzędzie tytułu chip łamał się przy 1280 px.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftRight, Plus } from "lucide-react";

import { type JobTwinsPayload, twinRef, useJobTwins } from "@/lib/job-twins-api";

import { TwinLinkDialog } from "./TwinLinkDialog";

function pairsLabel(n: number): string {
  if (n === 1) return "1 para";
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? `${n} pary` : `${n} par`;
}

/** Sam wygląd — test i harness bez zapytań. `"new"` = okno z wyborem rekrutacji. */
export function JobTwinChipView({
  data,
  onEdit,
}: {
  data: JobTwinsPayload;
  onEdit: (otherId: number | "new") => void;
}) {
  const canAdd = data.can_manage && data.twins.length < data.max_twins;
  if (data.twins.length === 0 && !canAdd) return null;

  return (
    <span className="inline-flex shrink-0 items-center gap-1.5" data-testid="job-twins-control">
      {data.twins.length > 0 ? (
        <span
          className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/30 bg-primary/10 px-2.5 text-[13px] font-semibold text-primary"
          data-testid="job-twin-chip"
          title="Bliźniak: osobę weryfikujesz raz, w jednej rozmowie, pod obie rekrutacje"
        >
          <ArrowLeftRight className="h-3 w-3" aria-hidden="true" />
          <span className="sr-only">{data.twins.length === 1 ? "Bliźniak:" : "Bliźniaki:"}</span>
          {data.twins.map((twin, index) => (
            <span key={twin.id} className="inline-flex items-center gap-1">
              {index > 0 ? <span aria-hidden="true">·</span> : null}
              <Link href={`/jobs/${twin.id}`} className="font-mono hover:underline">
                {twinRef(twin)}
              </Link>
              {data.can_manage ? (
                <button
                  type="button"
                  onClick={() => onEdit(twin.id)}
                  className="font-normal underline-offset-2 hover:underline"
                  title="Pary pytań, które w rozmowie zadajesz raz"
                >
                  · {pairsLabel(twin.question_pairs.length)}
                </button>
              ) : null}
            </span>
          ))}
        </span>
      ) : null}
      {canAdd ? (
        <button
          type="button"
          onClick={() => onEdit("new")}
          data-testid="job-twin-link"
          data-tour="jobs.twins.link"
          title="Wybierz dowolną otwartą rekrutację o tym samym profilu — osoby weryfikujecie raz, pod obie"
          className="inline-flex h-7 shrink-0 items-center gap-1 whitespace-nowrap rounded-md border border-dashed border-primary/40 bg-card px-2.5 text-[13px] font-semibold text-primary transition-colors hover:border-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
        >
          {data.twins.length > 0 ? (
            <>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Bliźniak
            </>
          ) : (
            <>
              <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden="true" />
              Połącz bliźniaka
            </>
          )}
        </button>
      ) : null}
    </span>
  );
}

export function JobTwinChip({ jobId }: { jobId: number }) {
  const twins = useJobTwins(jobId);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  if (!twins.data) return null;

  return (
    <>
      <JobTwinChipView data={twins.data} onEdit={setEditing} />
      {editing != null ? (
        <TwinLinkDialog
          jobId={jobId}
          open
          onOpenChange={(next) => {
            if (!next) setEditing(null);
          }}
          otherJobId={editing === "new" ? null : editing}
        />
      ) : null}
    </>
  );
}
