import { redirect } from "next/navigation";

// Dokumenty kontraktów z SharePointa są od 20.10.2026 zakładką System → Importy.
// Adres zostaje dla starych linków i zakładek przeglądarki.
export default function ContractDocsSharePointRedirect() {
  redirect("/settings?item=imports&zakladka=sharepoint");
}
