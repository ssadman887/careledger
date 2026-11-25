"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Money } from "@/components/money";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Schemas } from "@/lib/api/client";

export function BalancedBadge({ balanced }: { balanced: boolean }) {
  return balanced ? (
    <Badge variant="outline" className="border-emerald-600 text-emerald-700">
      Balanced
    </Badge>
  ) : (
    <Badge variant="destructive">Out of balance</Badge>
  );
}

export function TrialBalanceTable({ data }: { data: Schemas["TrialBalanceOut"] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Code</TableHead>
          <TableHead>Account</TableHead>
          <TableHead className="text-right">Debits</TableHead>
          <TableHead className="text-right">Credits</TableHead>
          <TableHead className="text-right">Balance Dr</TableHead>
          <TableHead className="text-right">Balance Cr</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.rows.length === 0 && (
          <TableRow>
            <TableCell colSpan={6} className="text-muted-foreground h-20 text-center">
              No postings in this range.
            </TableCell>
          </TableRow>
        )}
        {data.rows.map((r) => (
          <TableRow key={r.account_id}>
            <TableCell className="font-mono text-sm">{r.code}</TableCell>
            <TableCell>
              <Link href={`/reports?tab=ledger&account=${r.account_id}`} className="hover:underline">
                {r.name}
              </Link>
            </TableCell>
            <TableCell className="text-right">
              <Money value={r.debit} hideZero />
            </TableCell>
            <TableCell className="text-right">
              <Money value={r.credit} hideZero />
            </TableCell>
            <TableCell className="text-right">
              <Money value={r.balance_debit} hideZero />
            </TableCell>
            <TableCell className="text-right">
              <Money value={r.balance_credit} hideZero />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
      <TableFooter>
        <TableRow>
          <TableCell colSpan={2}>
            Totals <BalancedBadge balanced={data.balanced} />
          </TableCell>
          <TableCell className="text-right">
            <Money value={data.total_debit} />
          </TableCell>
          <TableCell className="text-right">
            <Money value={data.total_credit} />
          </TableCell>
          <TableCell className="text-right">
            <Money value={data.total_balance_debit} />
          </TableCell>
          <TableCell className="text-right">
            <Money value={data.total_balance_credit} />
          </TableCell>
        </TableRow>
      </TableFooter>
    </Table>
  );
}

function Section({ section }: { section: Schemas["StatementSectionOut"] }) {
  return (
    <>
      <TableRow className="bg-muted/40 hover:bg-muted/40">
        <TableCell colSpan={3} className="font-semibold">
          {section.title}
        </TableCell>
      </TableRow>
      {section.lines.map((l) => (
        <TableRow key={`${section.title}-${l.code}-${l.name}`}>
          <TableCell className="text-muted-foreground w-24 pl-6 font-mono text-sm">{l.code}</TableCell>
          <TableCell>{l.name}</TableCell>
          <TableCell className="text-right">
            <Money value={l.amount} />
          </TableCell>
        </TableRow>
      ))}
      <TableRow>
        <TableCell />
        <TableCell className="font-medium">Total {section.title.toLowerCase()}</TableCell>
        <TableCell className="text-right font-medium">
          <Money value={section.total} />
        </TableCell>
      </TableRow>
    </>
  );
}

function Statement({ children, footer }: { children: ReactNode; footer: ReactNode }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-24">Code</TableHead>
          <TableHead>Account</TableHead>
          <TableHead className="text-right">Amount</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>{children}</TableBody>
      <TableFooter>{footer}</TableFooter>
    </Table>
  );
}

export function IncomeStatementView({ data }: { data: Schemas["IncomeStatementOut"] }) {
  return (
    <Statement
      footer={
        <TableRow>
          <TableCell colSpan={2}>Net income</TableCell>
          <TableCell className="text-right">
            <Money value={data.net_income} />
          </TableCell>
        </TableRow>
      }
    >
      <Section section={data.revenue} />
      <Section section={data.expenses} />
    </Statement>
  );
}

export function BalanceSheetView({ data }: { data: Schemas["BalanceSheetOut"] }) {
  return (
    <Statement
      footer={
        <>
          <TableRow>
            <TableCell colSpan={2}>Total assets</TableCell>
            <TableCell className="text-right">
              <Money value={data.total_assets} />
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell colSpan={2}>
              Total liabilities and equity <BalancedBadge balanced={data.balanced} />
            </TableCell>
            <TableCell className="text-right">
              <Money value={data.total_liabilities_and_equity} />
            </TableCell>
          </TableRow>
        </>
      }
    >
      <Section section={data.assets} />
      <Section section={data.liabilities} />
      <Section section={data.equity} />
    </Statement>
  );
}

export function AccountLedgerView({ data }: { data: Schemas["AccountLedgerOut"] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Entry</TableHead>
          <TableHead>Memo</TableHead>
          <TableHead className="text-right">Debit</TableHead>
          <TableHead className="text-right">Credit</TableHead>
          <TableHead className="text-right">Balance</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow className="bg-muted/40 hover:bg-muted/40">
          <TableCell colSpan={5} className="font-medium">
            Opening balance
          </TableCell>
          <TableCell className="text-right font-medium">
            <Money value={data.opening_balance} />
          </TableCell>
        </TableRow>
        {data.rows.map((r, i) => (
          <TableRow key={`${r.entry_id}-${i}`}>
            <TableCell>{r.entry_date}</TableCell>
            <TableCell>
              <Link href={`/journal/${r.entry_id}`} className="font-mono text-sm hover:underline">
                {r.entry_number}
              </Link>
            </TableCell>
            <TableCell className="max-w-sm truncate">{r.line_description || r.memo}</TableCell>
            <TableCell className="text-right">
              <Money value={r.debit} hideZero />
            </TableCell>
            <TableCell className="text-right">
              <Money value={r.credit} hideZero />
            </TableCell>
            <TableCell className="text-right">
              <Money value={r.running_balance} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
      <TableFooter>
        <TableRow>
          <TableCell colSpan={5}>Closing balance ({data.normal_balance}-normal account)</TableCell>
          <TableCell className="text-right">
            <Money value={data.closing_balance} />
          </TableCell>
        </TableRow>
      </TableFooter>
    </Table>
  );
}
