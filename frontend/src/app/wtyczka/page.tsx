// „Wtyczka LinkedIn” — ZIP i instrukcja instalacji (za logowaniem).
import type { Metadata } from "next";

import { ExtensionInstallView } from "@/components/extension/ExtensionInstallView";

export const metadata: Metadata = {
  title: "Wtyczka LinkedIn | NEXUS",
};

export default function ExtensionInstallPage() {
  return <ExtensionInstallView />;
}
