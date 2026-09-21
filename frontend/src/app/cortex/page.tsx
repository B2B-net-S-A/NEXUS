import { redirect } from "next/navigation";

// Cortex ukryty w UI (decyzja 21.09.2026). Stare linki i zakładki prowadzą na
// Insights; widok `CortexView` zostaje w `components/cortex/` na powrót.
export default function CortexPage() {
  redirect("/insights");
}
