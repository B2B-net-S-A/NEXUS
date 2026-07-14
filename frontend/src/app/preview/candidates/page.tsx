import { CandidateListPreview } from "@/components/candidates/preview/CandidateListPreview"
import { PageHeader } from "@/components/ds"
import { Button } from "@/components/ui/button"

export default function CandidatesPreviewPage() {
  return (
    <main className="min-h-screen bg-background app-shell-root">
      <div className="mx-auto max-w-[1500px] space-y-6 px-4 py-6 sm:px-6">
        <PageHeader
          density="compact"
          eyebrow="Preview · Kandydaci"
          title="Czytelna lista kandydatów"
          description="Deterministyczny harness bez API: grupowane kolumny, kompaktowy mobile i semantyczne statusy."
          actions={<Button size="sm">Dodaj kandydata</Button>}
        />
        <CandidateListPreview />
      </div>
    </main>
  )
}
