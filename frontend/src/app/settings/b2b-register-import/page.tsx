import { redirect } from "next/navigation";

// Rejestr umów z Excela jest od 20.10.2026 zakładką System → Importy.
// Adres zostaje dla starych linków i zakładek przeglądarki.
export default function B2BRegisterImportRedirect() {
  redirect("/settings?item=imports&zakladka=excel");
}
