"use client";

import { HrConfigGate } from "@/components/hr/HrConfigGate";
import { MyTimeScreen } from "@/components/hr/MyTimeScreen";

export default function MyTimePage() {
  return <HrConfigGate>{(config) => <MyTimeScreen config={config} />}</HrConfigGate>;
}
