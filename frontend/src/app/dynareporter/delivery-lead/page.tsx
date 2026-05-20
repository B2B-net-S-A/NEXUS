import { redirect } from "next/navigation";

/**
 * Legacy ścieżka `/dynareporter/delivery-lead` (wczesna wersja B.2.3, prosta).
 * Skonsolidowana w `/dynareporter/delivery-lead-dashboard` (pełny widok zespołu
 * Hit Ratio + ranking, parytet z InfraReporter `/delivery-lead`). Sidebar
 * linkuje już do `-dashboard`; redirect zachowuje URL-parytet dla porównań
 * po ścieżce z oryginałem.
 */
export default function DeliveryLeadRedirect() {
  redirect("/dynareporter/delivery-lead-dashboard");
}
