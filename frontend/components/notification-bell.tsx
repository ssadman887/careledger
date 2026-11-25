"use client";

import { Bell, CheckCheck } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api, type Schemas } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const POLL_MS = 60_000;
const DOT: Record<Schemas["NotificationOut"]["level"], string> = {
  info: "bg-sky-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  action: "bg-primary",
};

export function NotificationBell() {
  const router = useRouter();
  const pathname = usePathname();
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Schemas["NotificationOut"][]>([]);

  const refreshCount = useCallback(async () => {
    const { data } = await api.GET("/api/v1/notifications/unread-count");
    setUnread(data?.unread ?? 0);
  }, []);
  useEffect(() => {
    void refreshCount();
    const t = setInterval(() => void refreshCount(), POLL_MS);
    return () => clearInterval(t);
  }, [refreshCount, pathname]);

  const loadItems = async () => {
    const { data } = await api.GET("/api/v1/notifications", { params: { query: { page_size: 10 } } });
    setItems(data?.items ?? []);
  };
  const open = async (n: Schemas["NotificationOut"]) => {
    if (!n.read_at) {
      await api.POST("/api/v1/notifications/{notification_id}/read", {
        params: { path: { notification_id: n.id } },
      });
      void refreshCount();
    }
    if (n.link) router.push(n.link);
  };
  const readAll = async () => {
    await api.POST("/api/v1/notifications/read-all");
    setItems((xs) => xs.map((x) => ({ ...x, read_at: x.read_at ?? new Date().toISOString() })));
    setUnread(0);
  };

  return (
    <DropdownMenu onOpenChange={(o) => o && void loadItems()}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        >
          <Bell />
          {unread > 0 && (
            <span className="bg-destructive absolute -top-0.5 -right-0.5 grid h-4 min-w-4 place-items-center rounded-full px-1 text-[10px] font-semibold text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-96">
        <DropdownMenuLabel className="flex items-center justify-between">
          Notifications
          {unread > 0 && (
            <Button variant="ghost" size="sm" className="h-7" onClick={() => void readAll()}>
              <CheckCheck /> Mark all read
            </Button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 && (
          <p className="text-muted-foreground px-2 py-6 text-center text-sm">You&apos;re all caught up.</p>
        )}
        {items.map((n) => (
          <DropdownMenuItem key={n.id} className="items-start gap-3 py-2" onSelect={() => void open(n)}>
            <span
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                n.read_at ? "bg-transparent" : DOT[n.level],
              )}
            />
            <span className="min-w-0 flex-1">
              <span className={cn("block text-sm", !n.read_at && "font-medium")}>{n.title}</span>
              {n.body && <span className="text-muted-foreground line-clamp-2 block text-xs">{n.body}</span>}
              <span className="text-muted-foreground block text-[11px]">{formatDateTime(n.created_at)}</span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
