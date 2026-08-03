import { redirect } from "next/navigation"

export default function LegacyHeadOfRecruitmentDashboard() {
  redirect("/dashboard?preset=head-of-recruitment&period=week")
}
