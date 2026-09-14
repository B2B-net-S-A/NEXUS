import { AlertCircle } from "lucide-react";

import type { PublicLinkFailure } from "@/lib/public-link-state";

const COPY: Record<PublicLinkFailure, { heading: string; body: string }> = {
  invalid: {
    heading: "Link nieprawidłowy lub wygasł",
    body: "Skontaktuj się z osobą, która udostępniła Ci ten link, i poproś o nowy.",
  },
  unavailable: {
    heading: "Nie udało się otworzyć linku",
    body: "To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.",
  },
};

/** Strona błędu publicznego linku — bez odsyłania obcej osoby do dashboardu. */
export function PublicLinkUnavailable({ failure }: { failure: PublicLinkFailure }) {
  const copy = COPY[failure];
  return (
    <main className="max-w-xl mx-auto p-6 pt-16">
      <div
        role="alert"
        className="rounded-lg border border-destructive/20 bg-destructive/10 p-6 text-center"
      >
        <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-3" />
        <h1 className="text-lg font-semibold mb-1">{copy.heading}</h1>
        <p className="text-sm text-muted-foreground">{copy.body}</p>
      </div>
    </main>
  );
}
