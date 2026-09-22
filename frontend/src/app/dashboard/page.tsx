import { CustomDashboard } from "@/components/v2/dashboard/custom/CustomDashboard"

// Bez <Suspense>: pulpit nie czyta `useSearchParams`, a strumieniowana granica
// podmienia „Ładowanie…" na treść skryptem czekającym na klatkę animacji —
// w karcie w tle (i na starcie przeglądarki) pulpit wisiał na „Ładowanie…".
export default function DashboardPage() {
  return <CustomDashboard />
}
