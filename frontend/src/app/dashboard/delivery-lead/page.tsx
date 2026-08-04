import { redirect } from "next/navigation"

export default function LegacyDeliveryLeadDashboard() {
  redirect("/dashboard?preset=delivery-lead&period=month")
}
