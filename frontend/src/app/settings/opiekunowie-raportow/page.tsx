"use client";

// Ustawienia → Zespół i dostęp → „Opiekunowie raportów”. Dostęp: admin
// (middleware `/settings/opiekunowie-raportow` + `AdminUser` w
// `backend/app/api/competence_reports.py`).
import { ReportOwnersSettings } from "@/components/competence-reports/ReportOwnersSettings";

export default function ReportOwnersPage() {
  return <ReportOwnersSettings />;
}
