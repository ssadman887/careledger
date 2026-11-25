"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth/auth-context";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="text-muted-foreground grid min-h-[60vh] place-items-center text-sm" aria-busy="true">
        Loading…
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
