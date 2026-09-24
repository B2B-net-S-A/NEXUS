"use client";

import { AcademyProgramsList } from "@/components/academy/AcademyProgramsList";

/** `/academy` — lista programów naboru (Akademia Rekrutera i kolejne). */
export default function AcademyPage() {
  return (
    <div className="mx-auto max-w-7xl">
      <AcademyProgramsList />
    </div>
  );
}
