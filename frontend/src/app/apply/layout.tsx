/**
 * Public apply layout — minimal shell (no sidebar/topbar, no auth).
 * Theme: light, cream canvas consistent with v2.
 */

export default function ApplyLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {children}
    </div>
  );
}
