import { describe, expect, it } from "vitest";

import { render, screen } from "@testing-library/react";

import { DEMO_BANNER_TEXT, DemoBanner } from "@/components/demo-banner";
import { loginSchema } from "@/lib/validation/login";
import { createUserSchema } from "@/lib/validation/users";

describe("DemoBanner", () => {
  it("renders the required synthetic-data notice", () => {
    render(<DemoBanner />);
    expect(screen.getByRole("status")).toHaveTextContent(DEMO_BANNER_TEXT);
    expect(DEMO_BANNER_TEXT).toBe("Demo system. Synthetic data only. Not for real patient data.");
  });
});

describe("validation schemas", () => {
  it("requires login and password", () => {
    expect(loginSchema.safeParse({ login: " ", password: "" }).success).toBe(false);
    expect(loginSchema.safeParse({ login: "admin", password: "x" }).success).toBe(true);
  });

  it("validates new users", () => {
    const ok = {
      full_name: "A B",
      username: "ab_1",
      email: "ab@careledger.example",
      password: "longenough",
      role: "auditor",
    };
    expect(createUserSchema.safeParse(ok).success).toBe(true);
    expect(createUserSchema.safeParse({ ...ok, username: "a" }).success).toBe(false);
    expect(createUserSchema.safeParse({ ...ok, role: "root" }).success).toBe(false);
  });
});
