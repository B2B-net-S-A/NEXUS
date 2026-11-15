"use client";

/** `/zespoly/{id}` — zespół dla klienta po naszej stronie (`docs/claude/klienci/zespol-dla-klienta.md`). */
import { use } from "react";

import { TeamBoard } from "@/components/v2/team-request/TeamBoard";

export default function TeamPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const teamId = Number(id);
  if (!Number.isInteger(teamId) || teamId <= 0) {
    return <div className="p-6 text-sm text-muted-foreground">Nie ma takiego zespołu.</div>;
  }
  return <TeamBoard teamId={teamId} />;
}
