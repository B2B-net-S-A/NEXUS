import { redirect } from "next/navigation";

// Szablony okna „Wyślij e-mail” są od 20.10.2026 zakładką „Do kandydatów”
// w Ustawienia → Rekrutacja → Szablony maili. Adres zostaje dla starych linków.
export default function EmailTemplatesRedirect() {
  redirect("/settings?item=mail");
}
