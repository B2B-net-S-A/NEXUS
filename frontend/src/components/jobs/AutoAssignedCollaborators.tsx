"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles, Users } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

interface CcRecruiter {
  user_id: number;
  name: string;
  email: string;
  role: string | null;
  is_primary: boolean;
  priority: number | null;
}

interface Props {
  competenceCategoryId: number | null;
  /** user_ids that should appear as checked (unchecked = user de-selected). */
  selectedUserIds: number[];
  onChange: (ids: number[]) => void;
}

/**
 * AutoAssignedCollaborators – lista rekruterów przypisanych do wybranej CC.
 *
 * Domyślnie zaznaczamy wszystkich z priority=1 + primary DL (te są auto-add
 * przez backend). Priority=2 sourcerzy pokazują się niezaznaczeni jako backup.
 * Checkboxy dają DL-owi kontrolę: odznaczenie przed zapisem projektu wyłączy
 * ich z listy auto_cc collaborators (backend robi delete po tworzeniu).
 */
export function AutoAssignedCollaborators({
  competenceCategoryId,
  selectedUserIds,
  onChange,
}: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["cc-recruiters", competenceCategoryId],
    queryFn: async () => {
      if (!competenceCategoryId) return [] as CcRecruiter[];
      const { data } = await api.get<CcRecruiter[]>(
        `/api/competence-categories/${competenceCategoryId}/recruiters`,
      );
      return data;
    },
    enabled: Boolean(competenceCategoryId),
    staleTime: 5 * 60 * 1000,
  });

  const recruiters = data ?? [];

  if (!competenceCategoryId) return null;
  if (isLoading)
    return (
      <div className="text-[11px] text-muted-foreground italic">
        Ładuję zespół CC…
      </div>
    );
  if (recruiters.length === 0)
    return (
      <div className="text-[11px] text-amber-700 bg-amber-50 rounded px-2 py-1.5 flex items-center gap-1">
        <Users className="w-3 h-3" />W wybranej CC nie ma przypisanych
        rekruterów – dodaj w "Struktura zespołu".
      </div>
    );

  const primaryAndFirst = recruiters.filter(
    (r) => r.is_primary || r.priority === 1,
  );
  const backup = recruiters.filter(
    (r) => !r.is_primary && r.priority === 2,
  );

  const toggle = (id: number) => {
    if (selectedUserIds.includes(id)) {
      onChange(selectedUserIds.filter((x) => x !== id));
    } else {
      onChange([...selectedUserIds, id]);
    }
  };

  const labelFor = (r: CcRecruiter) =>
    r.is_primary ? "primary" : r.priority === 1 ? "1st priority" : "backup";
  const badgeVariant = (r: CcRecruiter): "burgundy" | "success" | "info" =>
    r.is_primary ? "burgundy" : r.priority === 1 ? "success" : "info";

  return (
    <div className="space-y-2 rounded-lg border border-primary/15 dark:border-primary/40 bg-primary/10 dark:bg-primary/10 px-3 py-2">
      <div className="flex items-center gap-2 text-[11px] font-medium text-primary dark:text-primary">
        <Sparkles className="w-3.5 h-3.5" />
        AI auto-podpina zespół CC (możesz odznaczyć)
      </div>
      <ul className="space-y-1">
        {primaryAndFirst.map((r) => (
          <li key={r.user_id} className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={selectedUserIds.includes(r.user_id)}
              onChange={() => toggle(r.user_id)}
              className="w-3.5 h-3.5 rounded border-border"
            />
            <span className="flex-1 text-foreground dark:text-muted-foreground">
              {r.name}
              <span className="text-muted-foreground"> · {r.email}</span>
            </span>
            <Badge size="sm" variant={badgeVariant(r)}>
              {labelFor(r)}
            </Badge>
          </li>
        ))}
        {backup.length > 0 && (
          <>
            <li className="text-[10px] uppercase tracking-wider text-muted-foreground pt-1">
              Dostępni dodatkowo
            </li>
            {backup.map((r) => (
              <li
                key={r.user_id}
                className="flex items-center gap-2 text-xs opacity-70"
              >
                <input
                  type="checkbox"
                  checked={selectedUserIds.includes(r.user_id)}
                  onChange={() => toggle(r.user_id)}
                  className="w-3.5 h-3.5 rounded border-border"
                />
                <span className="flex-1 text-foreground dark:text-muted-foreground">
                  {r.name}
                  <span className="text-muted-foreground"> · {r.email}</span>
                </span>
                <Badge size="sm" variant="info">
                  2nd priority
                </Badge>
              </li>
            ))}
          </>
        )}
      </ul>
    </div>
  );
}
