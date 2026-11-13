import { redirect } from "next/navigation";

// Okruszek „Koszty” nad kartą faktury prowadzi do zakładki w module Finanse.
export default function CostsAlias() {
  redirect("/finance?view=costs");
}
