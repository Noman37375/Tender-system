"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { tokens } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(tokens.access ? "/dashboard" : "/login");
  }, [router]);
  return null;
}
