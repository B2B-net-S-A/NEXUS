import type { M365ConnectionStatus } from "@/lib/api";

export interface M365SyncErrorMessage {
  variant: "warning" | "error";
  title: string;
  description: string;
}

/**
 * Błąd synchronizacji M365 po polsku, z następnym krokiem (UAT B61).
 *
 * Karta pokazywała `GraphRequestError("Graph 503: 'retry_after cap exceeded
 * (4x)'")` — nazwę klasy wyjątku i szczegół mechanizmu ponowień, bez
 * informacji, czy czekać, połączyć konto ponownie, czy zgłosić problem.
 * Surowy tekst zostaje w rozwijanych szczegółach.
 */
export function m365SyncErrorMessage(
  code: M365ConnectionStatus["last_error_code"],
): M365SyncErrorMessage {
  switch (code) {
    case "graph_throttled":
      return {
        variant: "warning",
        title: "Microsoft chwilowo ogranicza ruch",
        description:
          "To przejściowy błąd po stronie Microsoft 365. Synchronizacja ponowi się automatycznie za około 30 minut — nic nie musisz robić.",
      };
    case "timeout":
      return {
        variant: "warning",
        title: "Synchronizacja trwała za długo",
        description: "Ponowimy ją automatycznie przy kolejnym przebiegu.",
      };
    case "import_errors":
      return {
        variant: "warning",
        title: "Części wiadomości nie udało się zaimportować",
        description:
          "Ponowimy import przy kolejnym przebiegu. Jeśli komunikat się utrzymuje, zgłoś go administratorowi.",
      };
    case "reauth_required":
      return {
        variant: "error",
        title: "Połącz konto Microsoft 365 ponownie",
        description: "Microsoft nie przyjmuje już zapisanej autoryzacji. Rozłącz konto i połącz je jeszcze raz.",
      };
    case "delta_reset":
      return {
        variant: "error",
        title: "Synchronizacja zatrzymana",
        description:
          "Microsoft kilka razy unieważnił postęp synchronizacji. Rozłącz konto i połącz je ponownie; jeśli to nie pomoże, zgłoś administratorowi.",
      };
    default:
      return {
        variant: "error",
        title: "Błąd synchronizacji",
        description:
          "Spróbujemy ponownie automatycznie. Jeśli komunikat się utrzymuje, zgłoś go administratorowi (szczegóły poniżej).",
      };
  }
}
