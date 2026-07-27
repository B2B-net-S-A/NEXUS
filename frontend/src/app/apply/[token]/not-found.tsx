import Link from"next/link";
import { AlertTriangle } from"lucide-react";

export default function ApplyNotFound() {
 return (
 <main className="max-w-md mx-auto px-6 py-24 text-center space-y-4">
 <div className="mx-auto h-14 w-14 rounded-full bg-primary/10 text-primary flex items-center justify-center">
 <AlertTriangle className="h-7 w-7" />
 </div>
 <h1 className="font-semibold text-2xl font-extrabold tracking-heading-tight text-foreground">
 Ten link już nie działa
 </h1>
 <p className="text-sm text-muted-foreground">
 Link mógł wygasnąć lub zostać wycofany. Poproś osobę, która go wysłała, o
 świeży link.
 </p>
 <div className="pt-2">
 <Link
 href="/"
 className="inline-flex items-center text-sm font-semibold text-primary hover:underline"
 >
 ← Strona główna
 </Link>
 </div>
 </main>
 );
}
