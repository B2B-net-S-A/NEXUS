/**
 * Public signing layout — minimal shell (no sidebar/topbar, no auth).
 * Served at /sign/{token} for external consultants. Must stay outside
 * /contracts (which is PROTECTED in middleware.ts).
 */

export default function SignLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">{children}</div>
  );
}
