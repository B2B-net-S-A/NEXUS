import { redirect } from "next/navigation"

export default function LegacyRecruiterDashboard() {
  redirect("/dashboard?preset=my-work&period=day")
}
