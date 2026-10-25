"use client";

/**
 * „Prowadzi” w nagłówku panelu osoby — kto prowadzi kandydata w tej
 * rekrutacji i przypisanie tej osoby (prośba Olafa 23.10.2026, decyzje Artura
 * 25.10.2026; makiety: https://claude.ai/artifact/RYRUWbkuSfYWnW2NfJ6FUu).
 *
 * Przypisuje admin albo Head of Recruitment; prowadzić może aktywna osoba
 * z rolą rekrutera, także Delivery Lead z tą rolą. Przypisana osoba przejmuje
 * kartę, filtr „Kto dodał”, „Moich ludzi”, dzwonki, Ligę, cele i premię
 * rekrutera. Reguły: docs/claude/rekrutacja-tablica/prowadzi-przypisanie-osoby.md.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserRoundCog } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatDate } from "@/lib/utils";
import { getUserRoles, useAuthStore, type UserRole } from "@/store/auth";

export interface OwnerPerson {
  id: number;
  name: string | null;
  role: string;
  roles?: string[] | null;
  is_active?: boolean;
}

type OwnerItem = Pick<
  KanbanItem,
  | "candidate_id"
  | "owner_user_id"
  | "owner_name"
  | "owner_assigned_by_name"
  | "owner_assigned_at"
  | "owner_previous_name"
  | "verified_by_id"
  | "verified_by_name"
  | "verified_at"
  | "added_to_job_by_id"
  | "added_to_job_by_name"
  | "added_to_job_at"
>;

const ROLE_LABEL: Record<string, string> = {
  recruiter: "Rekruter",
  delivery_lead: "Delivery Lead",
  head_of_recruitment: "Head of Recruitment",
  talent_community_manager: "TCM",
  admin: "Admin",
};

function rolesOf(person: Pick<OwnerPerson, "role" | "roles">): string[] {
  return person.roles?.length ? person.roles : [person.role];
}

/** Prowadzić może aktywna osoba z rolą rekrutera (wycofane sourcer/tac też). */
export function canLead(person: OwnerPerson): boolean {
  if (person.is_active === false) return false;
  return rolesOf(person).some((r) => r === "recruiter" || r === "sourcer" || r === "tac");
}

export function mayAssignOwner(roles: readonly UserRole[]): boolean {
  return roles.includes("admin") || roles.includes("head_of_recruitment");
}

/** Kto prowadzi dziś: przypisany, potem weryfikujący, potem dodający. */
export function currentOwner(item: OwnerItem): {
  id: number | null;
  name: string | null;
  detail: string;
} {
  if (item.owner_name?.trim()) {
    return {
      id: item.owner_user_id ?? null,
      name: item.owner_name.trim(),
      detail: [
        item.owner_assigned_by_name ? `przypisał(a) ${item.owner_assigned_by_name}` : "przypisane",
        item.owner_assigned_at ? formatDate(item.owner_assigned_at) : null,
        item.owner_previous_name ? `było: ${item.owner_previous_name}` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    };
  }
  if (item.verified_by_name?.trim()) {
    return {
      id: item.verified_by_id ?? null,
      name: item.verified_by_name.trim(),
      detail: `zweryfikował(a)${item.verified_at ? ` ${formatDate(item.verified_at)}` : ""}`,
    };
  }
  if (item.added_to_job_by_name?.trim()) {
    return {
      id: item.added_to_job_by_id ?? null,
      name: item.added_to_job_by_name.trim(),
      detail: `dodał(a)${item.added_to_job_at ? ` ${formatDate(item.added_to_job_at)}` : ""}`,
    };
  }
  return { id: null, name: null, detail: "brak danych" };
}

function usePeople(enabled: boolean) {
  return useQuery<OwnerPerson[]>({
    queryKey: ["pair-owner-people"],
    queryFn: async () => {
      const { data } = await api.get<unknown>("/api/users/mentionable", {
        params: { include_inactive: "true" },
      });
      return Array.isArray(data) ? (data as OwnerPerson[]) : [];
    },
    staleTime: 60_000,
    enabled,
  });
}

export function PairOwnerLine({ item, jobId }: { item: OwnerItem; jobId: number }) {
  const user = useAuthStore((s) => s.user);
  const canAssign = mayAssignOwner(getUserRoles(user));
  const [open, setOpen] = useState(false);
  const owner = currentOwner(item);
  const people = usePeople(owner.id != null);
  const inactive =
    owner.id != null && people.data?.some((p) => p.id === owner.id && p.is_active === false);

  return (
    <>
      <div className="min-w-0 text-[11px] text-muted-foreground" data-testid="dock-pair-owner">
        <div className="flex min-w-0 items-center gap-1.5">
          <UserRoundCog className="h-3 w-3 shrink-0" aria-hidden="true" />
          <span className="shrink-0">Prowadzi</span>
          <span className="truncate font-semibold text-foreground">{owner.name ?? "—"}</span>
          {canAssign ? (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="shrink-0 rounded-md px-1 font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:p-2"
            >
              Przypisz
            </button>
          ) : null}
        </div>
        <div className="truncate pl-[18px]">
          {owner.detail}
          {inactive ? " · konto nieaktywne" : ""}
        </div>
      </div>
      {open ? (
        <OwnerDialog
          item={item}
          jobId={jobId}
          currentName={owner.name}
          currentInactive={Boolean(inactive)}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

function OwnerDialog({
  item,
  jobId,
  currentName,
  currentInactive,
  onClose,
}: {
  item: OwnerItem;
  jobId: number;
  currentName: string | null;
  currentInactive: boolean;
  onClose: () => void;
}) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const people = usePeople(true);
  const candidates = (people.data ?? []).filter(canLead);
  const [picked, setPicked] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const pickedPerson = candidates.find((p) => p.id === picked) ?? null;
  const job = useQuery<{ delivery_lead_user?: { id: number; name: string | null } | null }>({
    queryKey: ["pair-owner-job", jobId],
    queryFn: async () => (await api.get(`/api/jobs/${jobId}`)).data,
    staleTime: 60_000,
  });
  const jobDl = job.data?.delivery_lead_user ?? null;

  const assign = useMutation({
    mutationFn: async () =>
      (
        await api.put(`/api/pipeline/jobs/${jobId}/candidates/${item.candidate_id}/owner`, {
          owner_user_id: picked,
          reason: reason.trim(),
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      showSuccess(`Prowadzi teraz ${pickedPerson?.name ?? "wybrana osoba"}.`);
      onClose();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się przypisać osoby.")),
  });

  return (
    <AppModal
      open
      onOpenChange={(next) => (next ? null : onClose())}
      title="Przypisz osobę w tej rekrutacji"
      description={`Teraz: ${currentName ?? "brak danych"}${
        currentInactive ? " (konto nieaktywne)" : ""
      }. Zmiana dotyczy tylko tej rekrutacji.`}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={pickedPerson == null || reason.trim().length < 3 || assign.isPending}
            onClick={() => assign.mutate()}
          >
            {assign.isPending ? "Zapisuję…" : "Przypisz"}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="space-y-1">
          <label className="block text-xs font-medium text-foreground" htmlFor="pair-owner-person">
            Osoba prowadząca
          </label>
          <select
            id="pair-owner-person"
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            value={picked ?? ""}
            onChange={(e) => setPicked(e.target.value ? Number(e.target.value) : null)}
            disabled={people.isLoading}
          >
            <option value="">{people.isLoading ? "Wczytywanie osób…" : "Wybierz osobę…"}</option>
            {candidates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name ?? `Konto nr ${p.id}`} · {rolesOf(p).map((r) => ROLE_LABEL[r] ?? r).join(" + ")}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-muted-foreground">
            {people.isError
              ? apiErrorMessage(people.error, "Nie udało się wczytać listy osób.")
              : "Na liście są osoby z rolą rekrutera, także Delivery Leadzi, którzy rekrutują."}
          </p>
        </div>
        <div className="space-y-1">
          <label className="block text-xs font-medium text-foreground" htmlFor="pair-owner-reason">
            Dlaczego (zostaje w historii)
          </label>
          <textarea
            id="pair-owner-reason"
            className="min-h-[44px] w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Np. kandydata znalazła i prowadzi Marlena, w Traffit wpisana była Zuzia"
          />
        </div>
        <div className="rounded-md border border-border bg-muted/30 p-2.5 text-xs">
          <div className="mb-1 font-semibold text-foreground">Na nową osobę przechodzi</div>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            <li>imię na karcie i w panelu, filtr „Kto dodał”, „Moi ludzie”, dzwonki, kto ma ruch</li>
            <li>Liga Mistrzów i cele za „Zweryfikowany” i dalsze kroki</li>
            <li>premia rekrutera za placement (jeszcze nieprzyznana)</li>
          </ul>
        </div>
        {pickedPerson ? (
          <div
            className="rounded-md border border-border bg-background p-2.5 text-xs"
            data-testid="pair-owner-bonus-preview"
          >
            <div className="mb-1 font-semibold text-foreground">Premie za ten placement po zmianie</div>
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <span className="text-muted-foreground">Rekruter</span>
              <span className="font-medium text-foreground">{pickedPerson.name}</span>
              <span className="text-muted-foreground">Delivery Lead</span>
              <span className="font-medium text-foreground">
                {jobDl?.name ? `${jobDl.name} (DL rekrutacji, bez zmian)` : "DL według reguły premii, bez zmian"}
              </span>
            </div>
            {jobDl?.id === pickedPerson.id ? (
              <p className="mt-1.5 text-muted-foreground">
                {pickedPerson.name} jest też DL-em tej rekrutacji i ma rolę rekrutera, więc dostanie
                obie premie: rekrutera i DL-a.
              </p>
            ) : null}
          </div>
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          Przypisują admin i Head of Recruitment. Historia etapów się nie zmienia.
        </p>
      </div>
    </AppModal>
  );
}
