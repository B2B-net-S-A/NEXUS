"use client";

import { TraineeTodayView } from "@/components/trainee/TraineeTodayView";
import { isTraineeOnly, useAuthStore } from "@/store/auth";

// „Telefony na dziś” (0372) — jedyny ekran praktykanta. Middleware wpuszcza
// tu wyłącznie rolę `trainee`; strona pilnuje tego samego po hydratacji, bo
// trasy praktykanta w API i tak odmówią każdej innej roli.
export default function TraineePage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }
  if (!isTraineeOnly(user)) {
    return (
      <div className="p-6 text-muted-foreground">
        „Telefony na dziś” to ekran praktykanta. Wyniki praktykantów są w panelu
        „Praktykanci”.
      </div>
    );
  }
  return <TraineeTodayView />;
}
