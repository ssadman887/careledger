"use client";

import { LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth/auth-context";
import { isAvailable, navForRoles } from "@/lib/nav";
import { ROLE_LABELS } from "@/lib/roles";
import { cn } from "@/lib/utils";

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { roles } = useAuth();
  const sections = navForRoles(roles);

  return (
    <nav aria-label="Main" className="flex flex-col gap-6 p-4">
      {sections.map((section) => (
        <div key={section.title}>
          <p className="text-muted-foreground mb-2 px-2 text-[11px] font-semibold tracking-wider uppercase">
            {section.title}
          </p>
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              if (!isAvailable(item)) {
                return (
                  <li key={item.href}>
                    <span
                      aria-disabled="true"
                      className="text-muted-foreground/70 flex items-center justify-between rounded-md px-2 py-1.5 text-sm"
                    >
                      {item.label}
                      <Badge variant="outline" className="text-[10px] font-normal">
                        Phase {item.phase}
                      </Badge>
                    </span>
                  </li>
                );
              }
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "hover:bg-sidebar-accent focus-visible:ring-ring block rounded-md px-2 py-1.5 text-sm outline-none focus-visible:ring-2",
                      active && "bg-sidebar-accent text-accent-foreground font-medium",
                    )}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const roleLabel = user?.roles.map((r) => ROLE_LABELS[r as keyof typeof ROLE_LABELS] ?? r).join(", ");

  return (
    <div className="flex min-h-[calc(100vh-28px)]">
      <aside className="bg-sidebar border-sidebar-border hidden w-60 shrink-0 border-r lg:block">
        <div className="flex h-14 items-center gap-2 border-b px-6">
          <span className="bg-primary text-primary-foreground grid size-7 place-items-center rounded-md text-sm font-bold">
            C
          </span>
          <span className="font-semibold">CareLedger</span>
        </div>
        <Sidebar />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
          />
          <aside className="bg-sidebar relative h-full w-64 overflow-y-auto shadow-xl">
            <div className="flex h-14 items-center justify-between border-b px-4">
              <span className="font-semibold">CareLedger</span>
              <Button variant="ghost" size="icon" aria-label="Close menu" onClick={() => setOpen(false)}>
                <X />
              </Button>
            </div>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-card flex h-14 items-center justify-between gap-4 border-b px-4 lg:px-8">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label="Open menu"
            onClick={() => setOpen(true)}
          >
            <Menu />
          </Button>
          <div className="flex-1" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-auto gap-3 py-1.5">
                <span className="bg-accent text-accent-foreground grid size-8 place-items-center rounded-full text-xs font-semibold">
                  {user?.full_name
                    .split(" ")
                    .map((p) => p[0])
                    .join("")
                    .slice(0, 2)}
                </span>
                <span className="hidden text-left sm:block">
                  <span className="block text-sm leading-tight font-medium">{user?.full_name}</span>
                  <span className="text-muted-foreground block text-xs leading-tight">{roleLabel}</span>
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel className="font-normal">
                <span className="block text-sm font-medium">{user?.username}</span>
                <span className="text-muted-foreground block text-xs">{user?.email}</span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => void logout()}>
                <LogOut /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main className="flex-1 p-4 lg:p-8">{children}</main>
      </div>
    </div>
  );
}
