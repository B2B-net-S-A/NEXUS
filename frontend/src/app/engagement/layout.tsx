/**
 * Public engagement-declaration layout — magic-link landing page.
 * Bez auth, bez sidebar — same shell jak /apply.
 */

export default function EngagementLayout({
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
