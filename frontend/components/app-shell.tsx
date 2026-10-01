"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  Activity,
  FileText,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Settings,
  X,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/providers", label: "Providers", icon: KeyRound },
  { href: "/telemetry", label: "Telemetry", icon: Activity },
  { href: "/evaluations", label: "Evaluations", icon: FlaskConical },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
              active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function UserFooter() {
  const { state, logout } = useAuth();
  if (state.status !== "signed-in") return null;
  return (
    <div className="flex items-center justify-between gap-2 border-t pt-3">
      <span className="truncate text-sm text-muted-foreground" title={state.user.username}>
        {state.user.username}
      </span>
      <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out" title="Sign out">
        <LogOut />
      </Button>
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 px-2.5 text-base font-semibold tracking-tight">
      <span className="grid size-6 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">R</span>
      RAGForge
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-56 shrink-0 flex-col gap-5 border-r bg-sidebar p-3 md:flex">
        <Brand />
        <div className="flex-1">
          <Nav />
        </div>
        <UserFooter />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col gap-5 border-r bg-sidebar p-3">
            <div className="flex items-center justify-between">
              <Brand />
              <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close menu">
                <X />
              </Button>
            </div>
            <div className="flex-1">
              <Nav onNavigate={() => setOpen(false)} />
            </div>
            <UserFooter />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b px-3 py-2 md:hidden">
          <Button variant="ghost" size="icon" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu />
          </Button>
          <Brand />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 md:px-8", className)}>{children}</div>;
}
