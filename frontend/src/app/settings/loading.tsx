import { Loader2 } from 'lucide-react'

export default function SettingsLoading() {
    return (
        <div className="max-w-4xl mx-auto space-y-6 p-4">
            <div>
                <div className="h-8 w-32 rounded bg-muted animate-pulse" />
                <div className="h-4 w-64 mt-2 rounded bg-muted animate-pulse" />
            </div>
            <div className="flex items-center justify-center min-h-[40vh]">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
        </div>
    )
}
