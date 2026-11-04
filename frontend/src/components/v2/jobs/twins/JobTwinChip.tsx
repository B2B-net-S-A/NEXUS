"use client";

/**
 * „⇄ ZOB-2964 · 3 pary” w pasku „Kandydaci do dodania”, obok kafla „Otwarte
 * podobne” (0614, 28.10.2026). W rzędzie tytułu przy 1280 px chip nachodził
 * na „Tablicę”. Numer
 * otwiera bliźniaka; „N pary” (DL tej rekrutacji, HoR, admin) — okno
 * porównania, gdzie poprawia się pary pytań. Bez bliźniaka chip się nie
 * pokazuje: łączy się z kafla „Otwarte podobne”.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftRight } from "lucide-react";

import { twinRef, useJobTwins } from "@/lib/job-twins-api";

import { TwinLinkDialog } from "./TwinLinkDialog";

function pairsLabel(n: number): string {
  if (n === 1) return "1 para";
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? `${n} pary` : `${n} par`;
}

export function JobTwinChip({ jobId }: { jobId: number }) {
  const twins = useJobTwins(jobId);
  const [editing, setEditing] = useState<number | null>(null);
  const data = twins.data;
  if (!data || data.twins.length === 0) return null;

  return (
    <>
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
                onClick={() => setEditing(twin.id)}
                className="font-normal underline-offset-2 hover:underline"
                title="Pary pytań, które w rozmowie zadajesz raz"
              >
                · {pairsLabel(twin.question_pairs.length)}
              </button>
            ) : null}
          </span>
        ))}
      </span>
      {editing != null ? (
        <TwinLinkDialog
          jobId={jobId}
          open
          onOpenChange={(next) => {
            if (!next) setEditing(null);
          }}
          otherJobId={editing}
        />
      ) : null}
    </>
  );
}
