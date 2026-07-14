import { redirect } from "next/navigation"

export default function LegacyRootDashboardRedirect() {
  redirect("/dashboard")
}
