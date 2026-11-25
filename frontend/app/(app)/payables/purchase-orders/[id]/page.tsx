"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, errorMessage, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { can } from "@/lib/permissions";

type PO = Schemas["PurchaseOrderOut"];

export default function PurchaseOrderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { roles } = useAuth();
  const canManage = can(roles, "managePayables");
  const [po, setPo] = useState<PO | null>(null);
  const [billOpen, setBillOpen] = useState(false);
  const [invoiceNo, setInvoiceNo] = useState("");
  const [billDate, setBillDate] = useState(new Date().toISOString().slice(0, 10));

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/purchase-orders/{po_id}", {
      params: { path: { po_id: Number(id) } },
    });
    if (!data) return void toast.error(errorMessage(error, "Purchase order not found"));
    setPo(data);
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!po) return <p className="text-muted-foreground">Loading…</p>;

  const path = { params: { path: { po_id: po.id } } };
  const act = async (action: "issue" | "receive" | "cancel") => {
    const result =
      action === "issue"
        ? await api.POST("/api/v1/purchase-orders/{po_id}/issue", path)
        : action === "receive"
          ? await api.POST("/api/v1/purchase-orders/{po_id}/receive", path)
          : await api.POST("/api/v1/purchase-orders/{po_id}/cancel", path);
    if (!result.data) return void toast.error(errorMessage(result.error, "Action failed"));
    toast.success(`${result.data.po_number} ${result.data.status}`);
    setPo(result.data);
  };
  const createBill = async () => {
    const { data, error } = await api.POST("/api/v1/vendor-bills", {
      body: {
        vendor_id: po.vendor_id,
        vendor_invoice_number: invoiceNo.trim(),
        bill_date: billDate,
        purchase_order_id: po.id,
      },
    });
    if (!data) return void toast.error(errorMessage(error, "Could not create bill"));
    toast.success(`${data.bill_number} created (${data.match_status.replace("_", " ")})`);
    router.push(`/payables/bills/${data.id}`);
  };

  return (
    <>
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link href="/payables?tab=purchase-orders">
          <ArrowLeft /> Purchase orders
        </Link>
      </Button>
      <PageHeader
        title={po.po_number}
        description={`${po.vendor_name} · ordered ${po.order_date}${po.received_on ? ` · received ${po.received_on}` : ""}`}
        actions={
          canManage ? (
            <>
              {po.status === "draft" && <Button onClick={() => void act("issue")}>Issue to vendor</Button>}
              {po.status === "issued" && <Button onClick={() => void act("receive")}>Record receipt</Button>}
              {(po.status === "issued" || po.status === "received") && (
                <Button variant="outline" onClick={() => setBillOpen(true)}>
                  Create bill from PO
                </Button>
              )}
              {(po.status === "draft" || po.status === "issued") && (
                <Button variant="outline" onClick={() => void act("cancel")}>
                  Cancel
                </Button>
              )}
            </>
          ) : undefined
        }
      />
      <Card>
        <CardContent className="overflow-x-auto">
          <div className="mb-4 flex flex-wrap gap-6 text-sm">
            <span>
              Status <StatusBadge status={po.status} />
            </span>
            <span>
              Total <Money value={po.total} className="font-semibold" />
            </span>
            <span>
              Billed <Money value={po.billed} />
            </span>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Ordered</TableHead>
                <TableHead className="text-right">Received</TableHead>
                <TableHead className="text-right">Unit price</TableHead>
                <TableHead className="text-right">Amount</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {po.lines.map((l) => (
                <TableRow key={l.line_no}>
                  <TableCell>{l.line_no}</TableCell>
                  <TableCell>{l.description}</TableCell>
                  <TableCell className="text-right tabular-nums">{String(Number(l.quantity))}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {String(Number(l.received_quantity))}
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={l.unit_price} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={l.amount} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Dialog open={billOpen} onOpenChange={(o) => !o && setBillOpen(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Bill against {po.po_number}</DialogTitle>
            <DialogDescription>
              Lines are copied from the purchase order; the three-way match runs automatically.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="po-bill-no">Vendor invoice number</Label>
              <Input id="po-bill-no" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="po-bill-date">Bill date</Label>
              <Input
                id="po-bill-date"
                type="date"
                value={billDate}
                onChange={(e) => setBillDate(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBillOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void createBill()} disabled={!invoiceNo.trim()}>
              Create bill
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
