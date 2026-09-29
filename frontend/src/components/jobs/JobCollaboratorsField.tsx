"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import api from "@/lib/api";
import { COLLABORATOR_ROLES } from "@/lib/job-collaborators";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";

interface DirectoryUser {
  id: number;
  name: string;
}

/**
 * „Współpracownicy” rekrutacji — osoby, które pracują nad nią obok
 * prowadzącego. Pole w oknie edycji i na `/jobs/new`; zapis robi wołający
 * (`saveCollaboratorChanges`), bo rekrutacja na `/jobs/new` jeszcze nie istnieje.
 */
export function JobCollaboratorsField({
  value,
  onChange,
  primaryOwnerId,
  knownUsers,
}: {
  value: number[];
  onChange: (ids: number[]) => void;
  /** Prowadzący — nie da się go wybrać (serwer odpowiada 409). */
  primaryOwnerId?: number | null;
  /** Nazwiska już znane (np. `job.collaborators`) — zanim wczyta się katalog. */
  knownUsers?: ReadonlyArray<{ id: number; name?: string | null }>;
}) {
  // Ten sam katalog i klucz co `UserMultiSelect` — bez drugiego zapytania.
  const { data } = useQuery<DirectoryUser[]>({
    queryKey: ["users-directory"],
    queryFn: () => api.get("/api/users").then((r) => r.data),
    staleTime: 60_000,
  });
  const names = new Map<number, string>();
  for (const u of knownUsers ?? []) if (u.name) names.set(u.id, u.name);
  for (const u of data ?? []) names.set(u.id, u.name);
  const selected = value.filter((id) => id !== primaryOwnerId);

  return (
    <div className="space-y-2">
      <UserMultiSelect
        value={selected}
        onChange={onChange}
        placeholder="— brak —"
        searchPlaceholder="Szukaj osoby…"
        triggerWidthClass="w-full"
        onlyRoles={COLLABORATOR_ROLES}
        excludeIds={primaryOwnerId != null ? [primaryOwnerId] : undefined}
        ariaLabel="Współpracownicy"
      />
      {selected.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Wybrani współpracownicy">
          {selected.map((id) => {
            const name = names.get(id) ?? `#${id}`;
            return (
              <li
                key={id}
                className="inline-flex h-6 items-center gap-1 rounded-full border border-border bg-card pl-2 pr-1 text-xs"
              >
                {name}
                <button
                  type="button"
                  aria-label={`Usuń ${name} ze współpracowników`}
                  className="rounded-full p-0.5 text-muted-foreground hover:text-foreground"
                  onClick={() => onChange(selected.filter((other) => other !== id))}
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
