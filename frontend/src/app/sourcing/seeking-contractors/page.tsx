import { redirect } from "next/navigation";

export default function SeekingContractorsRedirect() {
  redirect("/sourcing/marketplace?tab=snapshot");
}
