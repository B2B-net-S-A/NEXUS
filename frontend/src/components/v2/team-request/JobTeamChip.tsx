"use client";

/**
 * Zespół na pasku rekrutacji (`docs/claude/klienci/zespol-dla-klienta.md`),
 * obok bliźniaków. Rekrutacja w zespole: „Zespół: <nazwa>” prowadzi do ekranu
 * zespołu. Bez zespołu osoba, która zakłada rekrutacje (`job.create`), widzi
 * „Utwórz zespół” — nazwa w okienku, potem ekran zespołu. Reszta nie widzi nic.
 */

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Users } from "lucide-react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { createTeam, fetchTeamOfJob, jobTeamKeys } from "@/lib/api/jobTeams";
import { hasCapability } from "@/lib/capabilities";
import { useAuthStore } from "@/store/auth";

const CHIP =
  "inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-xs font-medium hover:bg-muted";

/** Tworzenie zespołu: osobny komponent, bo potrzebuje toastów i okna potwierdzenia. */
function CreateTeamButton({ jobId }: { jobId: number }) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const { askReason, confirmDialog } = useConfirmV2();
  const create = useMutation({
    mutationFn: (name: string) => createTeam({ name, job_ids: [jobId] }),
    onSuccess: (team) => {
      queryClient.setQueryData(jobTeamKeys.detail(team.id), team);
      void queryClient.invalidateQueries({
        queryKey: jobTeamKeys.byJob(jobId),
      });
      // Bez `useRouter`: pasek źródeł bywa renderowany poza routerem aplikacji (testy, harness).
      window.location.assign(`/zespoly/${team.id}`);
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się utworzyć zespołu.")),
  });
  const start = async () => {
    const name = await askReason({
      title: "Utworzyć zespół z tą rekrutacją?",
      description:
        "Zespół zbiera kilka rekrutacji jednego klienta pod jednym zapytaniem i jednym linkiem dla klienta. Kolejne stanowiska dodasz na ekranie zespołu.",
      confirmLabel: "Utwórz zespół",
      field: {
        label: "Nazwa zespołu (widzi ją klient)",
        placeholder: "np. Zespół danych i raportowania",
        minLength: 2,
        maxLength: 160,
      },
    });
    if (name) create.mutate(name);
  };
  return (
    <>
      {confirmDialog}
      <button
        type="button"
        className={CHIP}
        data-tour="jobs.board.team"
        data-help="jobs.board.team"
        disabled={create.isPending}
        onClick={() => void start()}
      >
        <Plus className="h-3.5 w-3.5 text-muted-foreground" />
        Utwórz zespół
      </button>
    </>
  );
}

export function JobTeamChip({ jobId }: { jobId: number }) {
  const user = useAuthStore((s) => s.user);
  const canCreate = !!user && hasCapability(user, "job.create");
  const query = useQuery({
    queryKey: jobTeamKeys.byJob(jobId),
    queryFn: () => fetchTeamOfJob(jobId),
  });

  // Awaria odczytu nie zasłania paska: bez plakietki, bez fałszywego „Utwórz”.
  if (!query.isSuccess) return null;
  const team = query.data.team;
  if (team) {
    return (
      <Link
        href={`/zespoly/${team.id}`}
        className={CHIP}
        data-testid="job-team-chip"
        data-tour="jobs.board.team"
        data-help="jobs.board.team"
      >
        <Users className="h-3.5 w-3.5 text-muted-foreground" />
        Zespół: {team.name}
      </Link>
    );
  }
  return canCreate ? <CreateTeamButton jobId={jobId} /> : null;
}
