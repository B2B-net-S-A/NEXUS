// Ścieżka Poligonu zalogowanej osoby (15.11.2026): ćwiczenia jej ról i treści
// mówiące z perspektywy jej roli. Ta sama reguła co serwer
// (`PoligonPlan.exercises_for`). Gdy poligon jest wymagany, serwer podaje
// listę wymaganych ćwiczeń (`poligon.exercise_ids`, od nadania roli — po
// zmianie roli tylko niezaliczone ćwiczenia nowej roli) i to ją przechodzi
// mapa i okno ćwiczenia, tak jak liczy blokada.

import { useEffect, useMemo, useState } from "react";

import type { PoligonStatus } from "@/lib/novelties/logic";
import { getUserRoles, useAuthStore } from "@/store/auth";

import { exercisesFor, primaryRole, type Exercise, type ExerciseContext } from "./exercises";
import meta from "./meta.json";

const FIRST_NEW: ExerciseContext["firstNew"] = meta.people[0]
  ? { candidateId: meta.people[0].candidate_id, fullName: `${meta.people[0].name} ${meta.people[0].lastname}` }
  : null;

/** Ścieżka do przejścia: wymagane ćwiczenia z serwera albo ćwiczenia ról osoby. */
export function poligonPath(roles: readonly string[], status: PoligonStatus | null | undefined): readonly Exercise[] {
  const path = exercisesFor(roles);
  if (!status?.required || !status.exercise_ids) return path;
  const wanted = new Set(status.exercise_ids.map((id) => id.replace(/^poligon-/, "")));
  return path.filter((e) => wanted.has(e.id));
}

export function usePoligonPath(status: PoligonStatus | null | undefined): {
  path: readonly Exercise[];
  context: ExerciseContext;
} {
  const user = useAuthStore((s) => s.user);
  // Profil osoby jest tylko w przeglądarce — przed zamontowaniem ścieżka jest
  // pusta i po stronie serwera, i w pierwszym renderze klienta (inaczej mapa
  // `/poligon` rozjeżdża się przy hydratacji, React #418).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const key = status?.required ? (status.exercise_ids ?? []).join(",") : "";
  return useMemo(() => {
    const roles = mounted ? getUserRoles(user) : [];
    return { path: poligonPath(roles, status), context: { firstNew: FIRST_NEW, role: primaryRole(roles) } };
    // `key` niesie listę wymaganych ćwiczeń — nowy obiekt statusu z tą samą listą nie przelicza ścieżki.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, key, mounted]);
}
