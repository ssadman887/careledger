"use client";

import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/auth-context";
import { isAvailable, navForRoles } from "@/lib/nav";
import { ROLE_LABELS } from "@/lib/roles";

export default function DashboardPage() {
  const { user, roles } = useAuth();
  const modules = navForRoles(roles)
    .flatMap((s) => s.items)
    .filter((i) => i.href !== "/dashboard");

  return (
    <>
      <PageHeader
        title={`Welcome, ${user?.full_name.split(" ")[0] ?? ""}`}
        description={`Signed in as ${roles.map((r) => ROLE_LABELS[r]).join(", ")}. Financial dashboards arrive in Phase 6.`}
      />
      <h2 className="mb-3 text-sm font-semibold">Your modules</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {modules.map((item) => (
          <Card key={item.href} className={isAvailable(item) ? "" : "opacity-60"}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                {isAvailable(item) ? (
                  <Link href={item.href} className="hover:underline">
                    {item.label}
                  </Link>
                ) : (
                  item.label
                )}
                {!isAvailable(item) && <Badge variant="outline">Phase {item.phase}</Badge>}
              </CardTitle>
              <CardDescription>{isAvailable(item) ? "Available" : "Coming soon"}</CardDescription>
            </CardHeader>
            <CardContent />
          </Card>
        ))}
      </div>
    </>
  );
}
