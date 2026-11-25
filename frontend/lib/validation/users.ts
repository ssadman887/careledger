import { z } from "zod";

import type { RoleName } from "@/lib/roles";

export const ROLE_OPTIONS: readonly RoleName[] = [
  "admin",
  "billing_clerk",
  "insurance_officer",
  "accountant",
  "finance_manager",
  "auditor",
];

export const createUserSchema = z.object({
  full_name: z.string().trim().min(1, "Full name is required").max(200),
  username: z
    .string()
    .trim()
    .regex(/^[a-zA-Z0-9_.-]{3,64}$/, "3–64 characters: letters, digits, _ . -"),
  email: z
    .string()
    .trim()
    .regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, "Enter a valid email"),
  password: z.string().min(8, "At least 8 characters"),
  role: z.enum(ROLE_OPTIONS as [RoleName, ...RoleName[]]),
});

export type CreateUserValues = z.infer<typeof createUserSchema>;
