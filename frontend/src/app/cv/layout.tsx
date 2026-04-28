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
    <div
      data-ui="v2"
      data-ui-theme="apply-light"
      className="min-h-screen bg-[hsl(var(--bg-canvas))] text-[hsl(var(--text-body))]"
    >
      {children}
    </div>
  );
}
