export interface TreeAccount {
  id: number;
  code: string;
  parent_id: number | null;
}

/** Order accounts depth-first under their parents and attach depth for indentation. */
export function flattenTree<T extends TreeAccount>(accounts: readonly T[]): (T & { depth: number })[] {
  const byParent = new Map<number | null, T[]>();
  const ids = new Set(accounts.map((a) => a.id));
  for (const a of accounts) {
    const key = a.parent_id !== null && ids.has(a.parent_id) ? a.parent_id : null;
    byParent.set(key, [...(byParent.get(key) ?? []), a]);
  }
  for (const list of byParent.values()) list.sort((x, y) => x.code.localeCompare(y.code));
  const out: (T & { depth: number })[] = [];
  const walk = (parent: number | null, depth: number, seen: Set<number>) => {
    for (const a of byParent.get(parent) ?? []) {
      if (seen.has(a.id)) continue;
      seen.add(a.id);
      out.push({ ...a, depth });
      walk(a.id, depth + 1, seen);
    }
  };
  walk(null, 0, new Set());
  return out;
}
