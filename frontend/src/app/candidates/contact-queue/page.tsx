"use client";

import { ContactQueueWorkspace } from "@/components/candidate-contact/ContactQueueWorkspace";
import { Card } from "@/components/ui/card";
import { hasRole, useAuthStore } from "@/store/auth";

export default function CandidateContactQueuePage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }

  const canUseQueue = hasRole(
    user,
    "tac",
    "recruiter",
    "sourcer",
  );

  if (!canUseQueue) {
    return (
      <div className="p-6">
        <Card className="p-6">
          <h1 className="text-lg font-semibold text-foreground">Brak dostępu</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Kolejka kontaktu jest dostępna dla zespołu rekrutacji.
          </p>
        </Card>
      </div>
    );
  }

  return <ContactQueueWorkspace />;
}
