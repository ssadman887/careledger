"use client";

import { useCallback, useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";

export type Account = Schemas["AccountOut"];
export type Department = Schemas["DepartmentOut"];

/** All accounts (the chart is small: one page of 200 covers it). */
export function useAccounts(): { accounts: Account[]; loading: boolean; reload: () => Promise<void> } {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    const { data } = await api.GET("/api/v1/accounts", {
      params: { query: { page_size: 200, sort: "code" } },
    });
    setAccounts(data?.items ?? []);
    setLoading(false);
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { accounts, loading, reload };
}

export function useDepartments(): Department[] {
  const [departments, setDepartments] = useState<Department[]>([]);
  useEffect(() => {
    void api.GET("/api/v1/departments").then(({ data }) => setDepartments(data ?? []));
  }, []);
  return departments;
}
