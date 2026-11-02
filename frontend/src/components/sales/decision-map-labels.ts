/** Podpisy pól mapy decyzyjnej: wspólne dla listy osób i okna poprawki. */
export const DECISION_LEVELS = ["Zarząd / C-level", "Dyrektorzy", "Kierownicy", "Zespół"];

export const OUR_ROLE_LABELS: Record<string, string> = {
  decision_maker: "Decydent",
  economic_buyer: "Budżet",
  champion: "Champion",
  influencer: "Wpływa",
  blocker: "Hamuje",
  end_user: "Użytkownik",
};

export const CONTACT_STATUS: Record<
  string,
  { label: string; variant: "neutral" | "info" | "success" | "warning" }
> = {
  not_contacted: { label: "bez kontaktu", variant: "warning" },
  in_progress: { label: "w toku", variant: "info" },
  first_contact: { label: "pierwszy kontakt", variant: "info" },
  regular_dialog: { label: "stały dialog", variant: "success" },
};
