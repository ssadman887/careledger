"""PDF invoices, receipts and payslips (ReportLab). All carry the synthetic-data notice."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.billing import Invoice, Payment
from app.models.payroll import PayrollRun, Payslip

DEMO_NOTICE = "DEMO SYSTEM - SYNTHETIC DATA ONLY - NOT A REAL INVOICE"
TEAL = colors.HexColor("#0f6e6a")


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _d(value: date | None) -> str:
    return value.isoformat() if value else "-"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], textColor=TEAL, alignment=0, fontSize=20, spaceAfter=2
        ),
        "notice": ParagraphStyle(
            "notice",
            parent=base["Normal"],
            textColor=colors.HexColor("#8a5a00"),
            backColor=colors.HexColor("#fff4d6"),
            fontSize=8,
            leading=11,
            borderPadding=4,
            spaceAfter=10,
        ),
        "normal": base["Normal"],
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8, textColor=colors.grey),
        "h": ParagraphStyle("h", parent=base["Heading3"], spaceBefore=8, spaceAfter=4),
    }


def _table(
    rows: Sequence[Sequence[str]],
    widths: Sequence[float],
    *,
    header: bool = True,
    right_cols: Sequence[int] = (),
) -> Table:
    table = Table([list(r) for r in rows], colWidths=list(widths), hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef6f5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    for col in right_cols:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    table.setStyle(TableStyle(style))
    return table


def _doc(buffer: BytesIO, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="CareLedger (demo)",
    )


def invoice_pdf(invoice: Invoice, payments: Sequence[Payment]) -> bytes:
    s = _styles()
    buffer = BytesIO()
    story = [
        Paragraph("CareLedger General Hospital", s["title"]),
        Paragraph(DEMO_NOTICE, s["notice"]),
        _table(
            [
                ["Invoice", invoice.invoice_number, "Patient", invoice.patient.full_name],
                ["Status", invoice.status.replace("_", " ").title(), "MRN", invoice.patient.mrn],
                [
                    "Invoice date",
                    _d(invoice.invoice_date),
                    "Visit",
                    invoice.visit.visit_number if invoice.visit else "-",
                ],
                ["Due date", _d(invoice.due_date), "", ""],
            ],
            [28 * mm, 50 * mm, 22 * mm, 70 * mm],
            header=False,
        ),
        Paragraph("Charges", s["h"]),
    ]
    rows = [["#", "Description", "Date", "Qty", "Unit", "Discount", "Tax", "Total"]]
    rows += [
        [
            str(ln.line_no),
            ln.description[:48],
            _d(ln.service_date),
            f"{ln.quantity:g}",
            _money(ln.unit_price),
            _money(ln.discount_amount),
            _money(ln.tax_amount),
            _money(ln.line_total),
        ]
        for ln in invoice.lines
    ]
    story.append(
        _table(
            rows,
            [8 * mm, 58 * mm, 20 * mm, 11 * mm, 20 * mm, 18 * mm, 15 * mm, 22 * mm],
            right_cols=(3, 4, 5, 6, 7),
        )
    )
    story += [
        Spacer(1, 6),
        _table(
            [
                ["Subtotal", _money(invoice.subtotal)],
                ["Discounts", f"-{_money(invoice.discount_total)}"],
                ["Tax", _money(invoice.tax_total)],
                ["Total", _money(invoice.total)],
                ["Paid", _money(invoice.amount_paid)],
                ["Adjustments", f"-{_money(invoice.adjusted_amount)}"],
                ["Pending with insurer", _money(invoice.insurance_pending)],
                ["Patient balance due", _money(invoice.patient_due)],
            ],
            [140 * mm, 32 * mm],
            header=False,
            right_cols=(1,),
        ),
    ]
    if payments:
        story.append(Paragraph("Payments", s["h"]))
        prow = [["Payment", "Date", "Method", "Amount", "Refunded"]]
        prow += [
            [
                p.payment_number,
                _d(p.received_on),
                p.method.replace("_", " "),
                _money(p.amount),
                _money(p.refunded_amount),
            ]
            for p in payments
        ]
        story.append(_table(prow, [35 * mm, 30 * mm, 40 * mm, 32 * mm, 32 * mm], right_cols=(3, 4)))
    story += [Spacer(1, 12), Paragraph(f"Generated by CareLedger. {DEMO_NOTICE}.", s["small"])]
    _doc(buffer, f"Invoice {invoice.invoice_number}").build(story)
    return buffer.getvalue()


def receipt_pdf(payment: Payment, masked_reference: str) -> bytes:
    s = _styles()
    buffer = BytesIO()
    rows = [
        ["Receipt", payment.payment_number],
        ["Date", _d(payment.received_on)],
        ["Patient", f"{payment.patient.full_name} ({payment.patient.mrn})"],
        ["Method", payment.method.replace("_", " ").title()],
        ["Reference", masked_reference or "-"],
        ["For", payment.invoice.invoice_number if payment.invoice else "Deposit on account"],
        ["Amount received", _money(payment.amount)],
    ]
    if payment.refunded_amount > 0:
        rows.append(["Refunded", _money(payment.refunded_amount)])
    if payment.invoice is not None:
        rows.append(["Invoice balance now", _money(payment.invoice.balance_due)])
    story = [
        Paragraph("CareLedger General Hospital", s["title"]),
        Paragraph(DEMO_NOTICE.replace("INVOICE", "RECEIPT"), s["notice"]),
        Paragraph("Payment receipt", s["h"]),
        _table(rows, [45 * mm, 100 * mm], header=False),
        Spacer(1, 12),
        Paragraph("Thank you. Synthetic demo document.", s["small"]),
    ]
    _doc(buffer, f"Receipt {payment.payment_number}").build(story)
    return buffer.getvalue()


def payslip_pdf(run: PayrollRun, slip: Payslip, masked_bank: str) -> bytes:
    s = _styles()
    buffer = BytesIO()
    period = f"{run.period_start.isoformat()} to {run.period_end.isoformat()}"
    story = [
        Paragraph("CareLedger General Hospital - Payslip", s["title"]),
        Paragraph(DEMO_NOTICE.replace("INVOICE", "PAYSLIP"), s["notice"]),
        _table(
            [
                ["Employee", slip.employee_name, "Payroll run", run.run_number],
                ["Employee no.", slip.employee_number, "Period", period],
                ["Position", slip.position, "Pay date", _d(run.pay_date)],
                ["Department", slip.department.name, "Bank account", masked_bank or "-"],
                ["Days worked", f"{slip.days_worked} of {slip.days_in_month}", "", ""],
            ],
            [28 * mm, 55 * mm, 26 * mm, 63 * mm],
            header=False,
        ),
        Paragraph("Earnings", s["h"]),
        _table(
            [
                ["Component", "Amount"],
                ["Basic salary", _money(slip.basic)],
                ["Housing allowance", _money(slip.housing)],
                ["Transport allowance", _money(slip.transport)],
                ["Other allowance", _money(slip.other_allowance)],
                ["Gross pay", _money(slip.gross)],
            ],
            [140 * mm, 32 * mm],
            right_cols=(1,),
        ),
        Paragraph("Deductions", s["h"]),
        _table(
            [
                ["Component", "Amount"],
                ["Pension (employee contribution)", _money(slip.pension)],
                [f"Income tax (taxable pay {_money(slip.taxable)})", _money(slip.income_tax)],
                ["Other deductions", _money(slip.other_deduction)],
                [
                    "Total deductions",
                    _money(slip.pension + slip.income_tax + slip.other_deduction),
                ],
            ],
            [140 * mm, 32 * mm],
            right_cols=(1,),
        ),
        Spacer(1, 8),
        _table([["Net pay", _money(slip.net)]], [140 * mm, 32 * mm], header=False, right_cols=(1,)),
        Spacer(1, 12),
        Paragraph(
            "Income tax is computed on annualised taxable pay using the progressive slabs for "
            f"{run.year}, divided by 12. Generated by CareLedger. {DEMO_NOTICE}.",
            s["small"],
        ),
    ]
    _doc(buffer, f"Payslip {run.run_number} {slip.employee_number}").build(story)
    return buffer.getvalue()
