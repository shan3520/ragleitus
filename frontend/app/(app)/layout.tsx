"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export default function SignedInLayout({ children }: { children: React.ReactNode }) {
  const { state, retry, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (state.status === "signed-out") router.replace("/login");
  }, [state.status, router]);

  if (state.status === "unverified") {
    return (
      <div className="grid h-dvh place-items-center px-4">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <p className="font-medium">Could not reach ragleitus</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <div className="flex gap-2">
            <Button onClick={retry}>Try again</Button>
            <Button variant="outline" onClick={logout}>
              Sign out
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (state.status !== "signed-in") {
    return (
      <div className="grid h-dvh place-items-center text-sm text-muted-foreground" aria-busy="true">
        Loading…
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
