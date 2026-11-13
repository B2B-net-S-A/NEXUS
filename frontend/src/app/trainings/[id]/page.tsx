"use client";

import { useParams } from "next/navigation";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { TrainingDetailScreen } from "@/components/trainings/TrainingDetailScreen";

// Karta szkolenia: zamówienie, wycena A–E, umowa, przekazanie plików, nagranie,
// zapłata, publikacja i obecność.
export default function TrainingPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  return (
    <HrConfigGate>
      {() =>
        Number.isInteger(id) && id > 0 ? (
          <TrainingDetailScreen id={id} />
        ) : (
          <QueryStateNotice state="not_found" />
        )
      }
    </HrConfigGate>
  );
}
