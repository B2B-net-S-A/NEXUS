import { redirect } from "next/navigation";

/**
 * URL-parytet z InfraReporter `/admin`. Pełny panel admina DR jest pod
 * `/dynareporter/admin-dashboard` (sidebar linkuje tam). Redirect, żeby
 * porównanie po ścieżce z oryginałem nie trafiało w 404.
 */
export default function AdminRedirect() {
  redirect("/dynareporter/admin-dashboard");
}
