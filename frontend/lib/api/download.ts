"use client";

import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api/client";

function openBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank", "noopener");
  if (!win) {
    // Popup blocked: fall back to a download.
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Fetch an authenticated PDF through the typed client and open it. */
export async function openInvoicePdf(invoiceId: number, invoiceNumber: string): Promise<void> {
  const { data, error } = await api.GET("/api/v1/invoices/{invoice_id}/pdf", {
    params: { path: { invoice_id: invoiceId } },
    parseAs: "blob",
  });
  if (!data) return void toast.error(errorMessage(error, "Could not generate the PDF"));
  openBlob(data, `${invoiceNumber}.pdf`);
}

export async function openReceiptPdf(paymentId: number, paymentNumber: string): Promise<void> {
  const { data, error } = await api.GET("/api/v1/payments/{payment_id}/receipt", {
    params: { path: { payment_id: paymentId } },
    parseAs: "blob",
  });
  if (!data) return void toast.error(errorMessage(error, "Could not generate the receipt"));
  openBlob(data, `${paymentNumber}.pdf`);
}

export async function openPayslipPdf(payslipId: number, filename: string): Promise<void> {
  const { data, error } = await api.GET("/api/v1/payroll/payslips/{payslip_id}/pdf", {
    params: { path: { payslip_id: payslipId } },
    parseAs: "blob",
  });
  if (!data) return void toast.error(errorMessage(error, "Could not generate the payslip"));
  openBlob(data, filename);
}
