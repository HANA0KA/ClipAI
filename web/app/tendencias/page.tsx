import type { Metadata } from "next";
import { TrendingView } from "@/components/clipai/trending-view";

export const metadata: Metadata = { title: "Tendencias · ClipAI" };

export default function TrendingPage() {
  return <TrendingView />;
}
