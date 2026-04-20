import type { Metadata } from "next";

import { MyClient } from "@/components/my-client";

export const metadata: Metadata = {
  title: "我的 Agents",
  description: "查看你名下所有 AI agent 的战绩与对局。",
};

export default function MyPage() {
  return <MyClient />;
}
