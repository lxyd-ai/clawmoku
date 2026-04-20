import { SpectateClient } from "@/components/spectate-client";

type Props = { params: { id: string } };

export default function MatchPage({ params }: Props) {
  return <SpectateClient matchId={params.id} />;
}

export const dynamic = "force-dynamic";
