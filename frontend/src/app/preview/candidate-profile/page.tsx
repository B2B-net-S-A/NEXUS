import { CandidateProfilePreview } from "@/components/candidates/preview/CandidateProfilePreview"
import { PageHeader } from "@/components/ds"

export default function CandidateProfilePreviewPage() {
  return (
    <main className="min-h-screen bg-background app-shell-root">
      <div className="mx-auto max-w-[1440px] space-y-6 px-4 py-6 sm:px-6">
        <PageHeader
          density="compact"
          eyebrow="Preview · Profil kandydata"
          title="Quick view i pełny profil"
          description="Harness stanów prezentacyjnych bez logowania i bez requestów do backendu."
        />
        <CandidateProfilePreview />
      </div>
    </main>
  )
}
