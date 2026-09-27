"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { toast } from "sonner";

function Notice() {
  const params = useSearchParams();
  const router = useRouter();
  const status = params.get("tiktok");
  useEffect(() => {
    if (!status) return;
    if (status === "conectado") toast.success("TikTok conectado: ya puedes enviar clips a borradores");
    else toast.error(`TikTok: ${status}`);
    router.replace("/");
  }, [status, router]);
  return null;
}

/** Muestra el resultado de la vuelta de OAuth de TikTok (?tiktok=…). */
export function TikTokNotice() {
  return (
    <Suspense>
      <Notice />
    </Suspense>
  );
}
