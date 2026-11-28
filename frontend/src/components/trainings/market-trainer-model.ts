import type { MarketTrainerApplication, MarketTrainerStatus } from "@/lib/api/trainings";

/** Kolejność filtrów i etykiety statusów (decyzja Artura 28.11.2026). */
export const MARKET_STATUSES: readonly MarketTrainerStatus[] = [
  "new",
  "interview",
  "accepted",
  "rejected",
];

export const MARKET_STATUS_LABEL: Record<MarketTrainerStatus, string> = {
  new: "Nowe",
  interview: "Rozmowa",
  accepted: "W bazie trenerów",
  rejected: "Odrzucone",
};

export interface MarketAction {
  to: MarketTrainerStatus;
  label: string;
  /** Tytuł okna z notatką, które pyta przed zmianą. */
  confirmTitle: string;
  destructive: boolean;
}

/** Te same przejścia co `TRANSITIONS` w `services/website_trainer_applications.py`. */
const ACTIONS: Record<MarketTrainerStatus, readonly MarketAction[]> = {
  new: [
    { to: "interview", label: "Umów rozmowę", confirmTitle: "Przenieść do rozmowy?", destructive: false },
    { to: "rejected", label: "Odrzuć", confirmTitle: "Odrzucić zgłoszenie?", destructive: true },
  ],
  interview: [
    {
      to: "accepted",
      label: "Do bazy trenerów",
      confirmTitle: "Dodać do bazy trenerów?",
      destructive: false,
    },
    { to: "rejected", label: "Odrzuć", confirmTitle: "Odrzucić po rozmowie?", destructive: true },
  ],
  accepted: [
    {
      to: "rejected",
      label: "Wycofaj z bazy",
      confirmTitle: "Wycofać z bazy trenerów?",
      destructive: true,
    },
  ],
  rejected: [
    { to: "new", label: "Przywróć", confirmTitle: "Przywrócić do nowych?", destructive: false },
  ],
};

export function actionsFor(status: MarketTrainerStatus): readonly MarketAction[] {
  return ACTIONS[status];
}

/** Tematy z listy i własny temat na końcu, jak w zgłoszeniu ze strony. */
export function topicsLine(application: MarketTrainerApplication): string {
  const topics = application.other_topic
    ? [...application.topics, application.other_topic]
    : application.topics;
  return topics.join(", ");
}

export function countByStatus(
  applications: readonly MarketTrainerApplication[],
): Record<MarketTrainerStatus, number> {
  const counts: Record<MarketTrainerStatus, number> = {
    new: 0,
    interview: 0,
    accepted: 0,
    rejected: 0,
  };
  for (const application of applications) counts[application.status] += 1;
  return counts;
}
