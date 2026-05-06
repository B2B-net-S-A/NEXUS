/**
 * Public CV layout — token-link landing page (no auth).
 * Same pattern as /engagement i /apply.
 */

export default function CvLayout({
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
