"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage, type Schemas } from "@/lib/api/client";

type Invoice = Schemas["InvoiceOut"];
type Service = Schemas["ServiceOut"];

interface DraftLine {
  key: string;
  service_id: string;
  quantity: string;
  discount_percent: string;
  /** Discount already saved on the server (kept unless a percent is entered). */
  saved_discount: string | null;
  service_date: string;
}

const QTY = /^\d{1,8}(\.\d{1,2})?$/;
const PCT = /^(100(\.0{1,2})?|\d{1,2}(\.\d{1,2})?)$/;
let counter = 0;
const keyOf = () => `l${++counter}`;

function fromInvoice(invoice: Invoice): DraftLine[] {
  return invoice.lines
    .filter((l) => l.service_id !== null)
    .map((l) => ({
      key: keyOf(),
      service_id: String(l.service_id),
      quantity: String(Number(l.quantity)),
      discount_percent: "",
      saved_discount: /^0+(\.0+)?$/.test(l.discount_amount) ? null : l.discount_amount,
      service_date: l.service_date,
    }));
}

/**
 * Charge capture for a draft invoice. Pricing, discounts, tax and totals are computed by the
 * server (price list effective on the service date); this editor only collects the inputs.
 */
export function LineEditor({ invoice, onSaved }: { invoice: Invoice; onSaved: (inv: Invoice) => void }) {
  const [services, setServices] = useState<Service[]>([]);
  const [lines, setLines] = useState<DraftLine[]>(() => fromInvoice(invoice));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const defaultDate = invoice.lines[0]?.service_date ?? new Date().toISOString().slice(0, 10);

  useEffect(() => {
    void api
      .GET("/api/v1/services", { params: { query: { page_size: 200, sort: "code" } } })
      .then(({ data }) => setServices(data?.items ?? []));
  }, []);

  const update = (key: string, patch: Partial<DraftLine>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const save = async () => {
    for (const [i, l] of lines.entries()) {
      if (!l.service_id) return setError(`Line ${i + 1}: choose a service`);
      if (!QTY.test(l.quantity) || Number(l.quantity) <= 0)
        return setError(`Line ${i + 1}: invalid quantity`);
      if (l.discount_percent && !PCT.test(l.discount_percent))
        return setError(`Line ${i + 1}: discount must be 0–100%`);
    }
    setError(null);
    setBusy(true);
    const { data, error: apiError } = await api.PATCH("/api/v1/invoices/{invoice_id}", {
      params: { path: { invoice_id: invoice.id } },
      body: {
        lines: lines.map((l) => ({
          service_id: Number(l.service_id),
          quantity: l.quantity,
          service_date: l.service_date || null,
          discount_percent: l.discount_percent || null,
          discount_amount: !l.discount_percent && l.saved_discount ? l.saved_discount : null,
        })),
      },
    });
    setBusy(false);
    if (!data) return setError(errorMessage(apiError, "Could not save charges"));
    toast.success("Charges saved");
    setLines(fromInvoice(data));
    onSaved(data);
  };

  const priced = new Map(invoice.lines.map((l) => [l.line_no, l]));

  return (
    <div className="flex flex-col gap-3">
      <div className="text-muted-foreground hidden grid-cols-[2.5fr_0.7fr_0.8fr_1fr_1fr_40px] gap-2 text-xs font-medium lg:grid">
        <span>Service</span>
        <span>Qty</span>
        <span>Discount %</span>
        <span>Service date</span>
        <span className="text-right">Saved line total</span>
        <span className="sr-only">Remove</span>
      </div>
      {lines.length === 0 && (
        <p className="text-muted-foreground text-sm">No charges yet. Add a service below.</p>
      )}
      {lines.map((l, i) => (
        <fieldset
          key={l.key}
          className="grid gap-2 rounded-md border p-3 lg:grid-cols-[2.5fr_0.7fr_0.8fr_1fr_1fr_40px] lg:border-0 lg:p-0"
        >
          <legend className="sr-only">Charge {i + 1}</legend>
          <div>
            <Label htmlFor={`svc-${l.key}`} className="sr-only">
              Service, line {i + 1}
            </Label>
            <Select value={l.service_id} onValueChange={(v) => update(l.key, { service_id: v })}>
              <SelectTrigger id={`svc-${l.key}`} className="w-full">
                <SelectValue placeholder="Choose service" />
              </SelectTrigger>
              <SelectContent>
                {services.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.code} · {s.name}
                    {s.current_price ? ` · ${s.current_price}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Input
            aria-label={`Quantity, line ${i + 1}`}
            inputMode="decimal"
            value={l.quantity}
            onChange={(e) => update(l.key, { quantity: e.target.value })}
          />
          <Input
            aria-label={`Discount percent, line ${i + 1}`}
            inputMode="decimal"
            placeholder={l.saved_discount ? `-${l.saved_discount}` : "0"}
            title={
              l.saved_discount
                ? `Saved discount ${l.saved_discount}; enter a percent to replace it`
                : undefined
            }
            value={l.discount_percent}
            onChange={(e) => update(l.key, { discount_percent: e.target.value })}
          />
          <Input
            aria-label={`Service date, line ${i + 1}`}
            type="date"
            value={l.service_date}
            onChange={(e) => update(l.key, { service_date: e.target.value })}
          />
          <span className="self-center text-right text-sm">
            {priced.get(i + 1) ? (
              <Money value={priced.get(i + 1)?.line_total ?? "0"} />
            ) : (
              <span className="text-muted-foreground">unsaved</span>
            )}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove line ${i + 1}`}
            onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
          >
            <Trash2 />
          </Button>
        </fieldset>
      ))}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2 border-t pt-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            setLines((ls) => [
              ...ls,
              {
                key: keyOf(),
                service_id: "",
                quantity: "1",
                discount_percent: "",
                saved_discount: null,
                service_date: defaultDate,
              },
            ])
          }
        >
          <Plus /> Add charge
        </Button>
        <Button type="button" size="sm" onClick={() => void save()} disabled={busy}>
          {busy ? "Saving…" : "Save charges"}
        </Button>
      </div>
    </div>
  );
}
