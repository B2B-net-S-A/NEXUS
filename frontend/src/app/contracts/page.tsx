"use client";

import { Component, ErrorInfo, ReactNode, useEffect, useState } from "react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";

class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ContractsPage] ErrorBoundary:", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <pre className="m-4 p-3 text-xs bg-red-100 text-red-900 rounded whitespace-pre-wrap">
          ERROR: {this.state.error.message}
          {"\n\n"}
          {this.state.error.stack}
        </pre>
      );
    }
    return this.props.children;
  }
}

export default function ContractsPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    console.log("[ContractsPage] outer mounted");
    setMounted(true);
  }, []);

  if (!mounted) {
    return <div className="p-8 text-sm text-gray-500">Ładowanie kontraktów…</div>;
  }

  return (
    <ErrorBoundary>
      <ContractsListV2 />
    </ErrorBoundary>
  );
}
