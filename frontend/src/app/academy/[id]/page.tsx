"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { AcademyScreen } from "@/components/academy/AcademyScreen";

/** `/academy/[id]` — nabór jednego programu (edycja, dzwonienie, spotkania). */
export default function AcademyProgramPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  if (!Number.isInteger(id) || id <= 0) {
    return <p className="p-6 text-sm text-muted-foreground">Nie ma takiej akademii.</p>;
  }
  return (
    <div>
      {/* `useSearchParams` wymaga granicy Suspense na prerenderze. */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Wczytuję akademię…</p>}>
        <AcademyScreen programId={id} />
      </Suspense>
    </div>
  );
}
