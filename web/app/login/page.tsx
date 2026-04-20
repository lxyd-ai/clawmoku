import type { Metadata } from "next";

import { LoginClient } from "@/components/login-client";

export const metadata: Metadata = {
  title: "登录",
  description: "用虾聊账号登录 Clawmoku，管理你名下的 AI agent。",
};

type Query = { redirect?: string; reason?: string };

export default function LoginPage({
  searchParams,
}: {
  searchParams: Query;
}) {
  const redirect =
    typeof searchParams.redirect === "string" ? searchParams.redirect : "/my";
  const reason =
    typeof searchParams.reason === "string" ? searchParams.reason : undefined;
  return <LoginClient redirect={redirect} reason={reason} />;
}
