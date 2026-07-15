import { CandidateSplitPreview } from "@/components/candidates/preview/CandidateSplitPreview"
import { PageHeader } from "@/components/ds"

export default function CandidatesSplitPreviewPage() {
  return (
    <main className="min-h-screen bg-background app-shell-root">
      <div className="mx-auto max-w-[1500px] space-y-5 px-4 py-6 sm:px-6">
        <PageHeader
          density="compact"
          eyebrow="Preview · Kandydaci"
          title="Widok Split (lista + panel)"
          description="Produkcyjny CandidatesSplitView na deterministycznych danych — rozwijane wiersze (1a) + dokowany panel (1b)."
        />
        <CandidateSplitPreview />
      </div>
    </main>
  )
}
