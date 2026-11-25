"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage } from "@/lib/api/client";
import { ROLE_LABELS } from "@/lib/roles";
import { createUserSchema, ROLE_OPTIONS, type CreateUserValues } from "@/lib/validation/users";

const FIELDS = [
  { name: "full_name", label: "Full name", type: "text", autoComplete: "name" },
  { name: "username", label: "Username", type: "text", autoComplete: "off" },
  { name: "email", label: "Email", type: "email", autoComplete: "off" },
  { name: "password", label: "Initial password", type: "password", autoComplete: "new-password" },
] as const;

export function CreateUserForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const {
    register,
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<CreateUserValues>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { full_name: "", username: "", email: "", password: "", role: "billing_clerk" },
  });

  const onSubmit = handleSubmit(async ({ role, ...values }) => {
    const { data, error } = await api.POST("/api/v1/users", { body: { ...values, roles: [role] } });
    if (!data) {
      toast.error(errorMessage(error, "Could not create user"));
      return;
    }
    toast.success(`Created ${data.username}`);
    onCreated();
  });

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle className="text-base">New user</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FIELDS.map((f) => (
            <div key={f.name} className="flex flex-col gap-2">
              <Label htmlFor={`new-${f.name}`}>{f.label}</Label>
              <Input
                id={`new-${f.name}`}
                type={f.type}
                autoComplete={f.autoComplete}
                aria-invalid={!!errors[f.name]}
                aria-describedby={errors[f.name] ? `new-${f.name}-error` : undefined}
                {...register(f.name)}
              />
              {errors[f.name] && (
                <p id={`new-${f.name}-error`} className="text-destructive text-sm">
                  {errors[f.name]?.message}
                </p>
              )}
            </div>
          ))}
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-role">Role</Label>
            <Controller
              control={control}
              name="role"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="new-role" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_OPTIONS.map((r) => (
                      <SelectItem key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-3">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating…" : "Create user"}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
