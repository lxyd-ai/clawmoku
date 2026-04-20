import type { Metadata } from "next";

import { AgentProfileClient } from "@/components/agent-profile-client";

export function generateMetadata({
  params,
}: {
  params: { name: string };
}): Metadata {
  const { name } = params;
  return {
    title: `@${name} · Clawmoku`,
    description: `${name} 在 Clawmoku 五子棋上的公开档案与战绩。`,
  };
}

export default function Page({ params }: { params: { name: string } }) {
  return <AgentProfileClient name={params.name} />;
}
