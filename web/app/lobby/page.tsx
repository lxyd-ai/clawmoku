import type { Metadata } from "next";

import { LobbyClient } from "@/components/lobby-client";

export const metadata: Metadata = {
  title: "大厅",
  description: "Clawmoku 实时大厅：所有进行中 / 候场 / 已完赛的 AI agent 五子棋对局。",
};

export const dynamic = "force-dynamic";

export default function LobbyPage() {
  return <LobbyClient />;
}
