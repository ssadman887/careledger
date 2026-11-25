import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Right-aligned, tabular currency. Zero renders muted so tables scan easily. */
export function Money({
  value,
  className,
  hideZero = false,
}: {
  value: string;
  className?: string;
  hideZero?: boolean;
}) {
  const zero = /^-?0+(\.0+)?$/.test(value);
  if (zero && hideZero) return <span className="text-muted-foreground/50">—</span>;
  return (
    <span
      className={cn(
        "tabular-nums",
        zero && "text-muted-foreground",
        value.startsWith("-") && "text-destructive",
        className,
      )}
    >
      {formatMoney(value)}
    </span>
  );
}
