import { useCapability } from "@/hooks/useCapability";
import { jobEditScope, type JobEditScope } from "@/lib/job-edit-access";
import { canMutateSection } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

/** Pola rekrutacji (`GET /api/jobs/{id}`), z których liczymy prawa zespołu. */
export interface JobTeamPermissionsSource {
  can_edit?: boolean | null;
  /** Czy bieżąca osoba ustawia priorytet TEJ rekrutacji; brak = capability. */
  can_set_priority?: boolean | null;
}

export interface JobTeamPermissions {
  /** `full` — pełna edycja, `content` — treść (dopisanie osoby), `none` — odczyt. */
  editScope: JobEditScope;
  canSetPriority: boolean;
}

/**
 * Kto redaguje zespół i ustawia priorytet rekrutacji — jedna reguła dla
 * zakładki „Zespół” i nagłówka rekrutacji (14.10.2026). `can_set_priority`
 * z serwera zna zakres Delivery Leada; capability to tylko rola.
 */
export function useJobTeamPermissions(
  job: JobTeamPermissionsSource | null | undefined,
): JobTeamPermissions {
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const canWritePipeline = canMutateSection(authUser, "pipeline", impersonating);
  const canUpdateJob = useCapability("job.update");
  const priorityCapability = useCapability("job.priority.update");
  // Ta sama reguła co w doku: pełna edycja (`job.update`) albo treść (`can_edit`).
  const editScope = jobEditScope(job, {
    canWritePipeline,
    canManageJob: canUpdateJob,
  });
  const canSetPriority =
    canWritePipeline &&
    (typeof job?.can_set_priority === "boolean"
      ? job.can_set_priority
      : priorityCapability);
  return { editScope, canSetPriority };
}
