import { CandidateListHybridPreview } from "@/components/candidates/preview/CandidateListHybridPreview"

export default function CandidatesPreviewPage() {
  return (
    <main className="min-h-screen overflow-x-hidden bg-background app-shell-root">
      <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
        <CandidateListHybridPreview />
      </div>
    </main>
  )
}
