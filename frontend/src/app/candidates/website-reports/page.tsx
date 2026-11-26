import { ReportQueue } from "@/components/competence-reports/ReportQueue";

// „Raporty ze strony” (N6, 25.11.2026). Dostęp jak lista kandydatów
// (middleware `/candidates`); akcje za `CandidateWriteAccess` w API.
export default function WebsiteReportsPage() {
  return <ReportQueue />;
}
