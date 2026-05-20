import { redirect } from "next/navigation";

/**
 * URL-parytet z InfraReporter `/board`. Pełny widok Rady Nadzorczej jest pod
 * `/dynareporter/board-dashboard` (sidebar linkuje tam). Redirect, żeby
 * porównanie po ścieżce z oryginałem nie trafiało w 404.
 */
export default function BoardRedirect() {
  redirect("/dynareporter/board-dashboard");
}
