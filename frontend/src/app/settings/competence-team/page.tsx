import { redirect } from "next/navigation"

// „Kategorie kompetencji” są od 20.10.2026 zakładką ekranu Ustawienia → Zespół
// i dostęp → Zespół rekrutacji. Adres zostaje dla starych linków i zakładek.
export default function CompetenceTeamRedirect() {
  redirect("/settings/team-structure?zakladka=kategorie")
}
