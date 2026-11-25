"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth/auth-context";
import { loginSchema, type LoginValues } from "@/lib/validation/login";

export default function LoginPage() {
  const router = useRouter();
  const { user, login } = useAuth();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { login: "", password: "" },
  });

  useEffect(() => {
    if (user) router.replace("/dashboard");
  }, [user, router]);

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const error = await login(values.login, values.password);
    if (error) setServerError(error);
    else router.replace("/dashboard");
  });

  return (
    <main className="grid min-h-[calc(100vh-28px)] place-items-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <span className="bg-primary text-primary-foreground grid size-9 place-items-center rounded-lg font-bold">
            C
          </span>
          <span className="text-xl font-semibold">CareLedger</span>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Hospital financial management</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
              {serverError && (
                <Alert variant="destructive">
                  <AlertDescription>{serverError}</AlertDescription>
                </Alert>
              )}
              <div className="flex flex-col gap-2">
                <Label htmlFor="login">Username or email</Label>
                <Input
                  id="login"
                  autoComplete="username"
                  autoFocus
                  aria-invalid={!!errors.login}
                  aria-describedby={errors.login ? "login-error" : undefined}
                  {...register("login")}
                />
                {errors.login && (
                  <p id="login-error" className="text-destructive text-sm">
                    {errors.login.message}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  aria-invalid={!!errors.password}
                  aria-describedby={errors.password ? "password-error" : undefined}
                  {...register("password")}
                />
                {errors.password && (
                  <p id="password-error" className="text-destructive text-sm">
                    {errors.password.message}
                  </p>
                )}
              </div>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="text-muted-foreground mt-4 text-center text-xs">
          Demo accounts are listed in <code>docs/DEMO_USERS.md</code>. All share one password.
        </p>
      </div>
    </main>
  );
}
