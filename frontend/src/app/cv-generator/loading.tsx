import { Loader2 } from 'lucide-react'

export default function CvGeneratorLoading() {
    return (
        <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-8 text-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Ładowanie generatora CV…</p>
        </div>
    )
}
