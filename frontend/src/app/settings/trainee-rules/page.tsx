"use client";

import { ListChecks } from "lucide-react";

import { TraineeRulesForm } from "@/components/trainee/TraineeRulesForm";
import { hasRole, useAuthStore } from "@/store/auth";

// Ustawienia → Rekrutacja → Lista telefonów praktykantów (0371). Bramka jest
// lustrem `/api/trainee/rules` — admin i Head of Recruitment.
export default function TraineeRulesPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  if (!hasRole(user, "admin", "head_of_recruitment")) {
    return (
      <div className="p-6 text-muted-foreground">
        Reguły listy telefonów zmienia administrator albo Head of Recruitment.
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <ListChecks className="h-5 w-5 text-primary" aria-hidden />
          Lista telefonów praktykantów
        </h1>
        <p className="text-sm text-muted-foreground">
          Kto trafia na codzienną listę telefonów. System układa listy co noc; wyżej
          idą osoby pasujące do większej liczby rekrutacji, a najwyżej — do otwartych teraz.
        </p>
      </div>
      <TraineeRulesForm />
    </div>
  );
}
