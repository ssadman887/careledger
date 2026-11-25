"use client";

import Link from "next/link";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Schemas } from "@/lib/api/client";
import { chartData, formatValue, type ValueFormat } from "@/lib/dashboard";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type Section = Schemas["SectionOut"];
type Chart = Schemas["ChartOut"];

const COLORS = ["var(--color-primary)", "#d97706", "#2563eb", "#7c3aed", "#db2777", "#0891b2", "#65a30d"];
const TONE: Record<Schemas["KpiOut"]["tone"], string> = {
  default: "",
  good: "text-emerald-700 dark:text-emerald-400",
  warning: "text-amber-700 dark:text-amber-400",
  bad: "text-destructive",
};

function axisTick(format: ValueFormat) {
  return (v: number) =>
    format === "money"
      ? formatMoney(String(v)).replace(/\.00$/, "")
      : format === "percent"
        ? `${v}%`
        : String(v);
}

function KpiCard({ kpi }: { kpi: Schemas["KpiOut"] }) {
  const body = (
    <Card className={cn("h-full gap-2", kpi.href && "hover:border-primary/40 transition-colors")}>
      <CardHeader className="pb-0">
        <CardDescription>{kpi.label}</CardDescription>
        <CardTitle className={cn("text-2xl tabular-nums", TONE[kpi.tone])}>
          {formatValue(kpi.value, kpi.format)}
        </CardTitle>
      </CardHeader>
      {kpi.hint && <CardContent className="text-muted-foreground text-xs">{kpi.hint}</CardContent>}
    </Card>
  );
  return kpi.href ? (
    <Link href={kpi.href} aria-label={`${kpi.label}: ${formatValue(kpi.value, kpi.format)}`}>
      {body}
    </Link>
  ) : (
    body
  );
}

function ChartBody({ chart }: { chart: Chart }) {
  const data = chartData(chart);
  const first = chart.keys[0];
  const fmt = (first?.format ?? "money") as ValueFormat;
  const tooltip = (value: unknown, name: unknown) => {
    const key = chart.keys.find((k) => k.label === name || k.key === name);
    return formatValue(String(value), (key?.format ?? fmt) as ValueFormat);
  };
  if (data.length === 0)
    return <p className="text-muted-foreground py-10 text-center text-sm">No data yet.</p>;

  if (chart.kind === "donut") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey={first?.key ?? "value"}
            nameKey="label"
            innerRadius="55%"
            outerRadius="85%"
          >
            {data.map((d, i) => (
              <Cell key={String(d.label)} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v) => formatValue(String(v), fmt)} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    );
  }
  if (chart.kind === "hbar") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tickFormatter={axisTick(fmt)} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="label" width={130} tickLine={false} axisLine={false} />
          <Tooltip formatter={tooltip} />
          {chart.keys.map((k, i) => (
            <Bar
              key={k.key}
              dataKey={k.key}
              name={k.label}
              fill={COLORS[i % COLORS.length]}
              radius={[0, 4, 4, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }
  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey="label" tickLine={false} axisLine={false} />
      <YAxis tickFormatter={axisTick(fmt)} width={84} tickLine={false} axisLine={false} />
      <Tooltip formatter={tooltip} />
      {chart.keys.length > 1 && <Legend />}
    </>
  );
  if (chart.kind === "line") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: 8, right: 8 }}>
          {common}
          {chart.keys.map((k, i) => (
            <Line
              key={k.key}
              dataKey={k.key}
              name={k.label}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (chart.kind === "area") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ left: 8, right: 8 }}>
          {common}
          {chart.keys.map((k, i) => (
            <Area
              key={k.key}
              dataKey={k.key}
              name={k.label}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.15}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  // Mixed-unit bar charts (e.g. counts and money) plot only the first series.
  const keys = chart.keys.filter((k) => k.format === fmt);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ left: 8, right: 8 }}>
        {common}
        {keys.map((k, i) => (
          <Bar
            key={k.key}
            dataKey={k.key}
            name={k.label}
            fill={COLORS[i % COLORS.length]}
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function DashboardSection({ section }: { section: Section }) {
  return (
    <section aria-labelledby={`section-${section.id}`} className="mb-10">
      <div className="mb-3">
        <h2 id={`section-${section.id}`} className="text-lg font-semibold">
          {section.title}
        </h2>
        <p className="text-muted-foreground text-sm">{section.description}</p>
      </div>
      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {section.kpis.map((k) => (
          <KpiCard key={k.key} kpi={k} />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        {section.charts.map((c) => (
          <Card key={c.id}>
            <CardHeader>
              <CardTitle className="text-base">{c.title}</CardTitle>
              {c.description && <CardDescription>{c.description}</CardDescription>}
            </CardHeader>
            <CardContent className={c.kind === "hbar" ? "h-72" : "h-64"}>
              <ChartBody chart={c} />
            </CardContent>
          </Card>
        ))}
        {section.tables.map((t) => (
          <Card key={t.id}>
            <CardHeader>
              <CardTitle className="text-base">{t.title}</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {t.columns.map((col) => (
                      <TableHead key={col.key} className={col.format === "text" ? "" : "text-right"}>
                        {col.label}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {t.rows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={t.columns.length} className="text-muted-foreground text-center">
                        Nothing to show.
                      </TableCell>
                    </TableRow>
                  )}
                  {t.rows.map((row, i) => (
                    <TableRow key={i}>
                      {t.columns.map((col) => (
                        <TableCell
                          key={col.key}
                          className={cn("text-sm", col.format !== "text" && "text-right tabular-nums")}
                        >
                          {formatValue(row[col.key] ?? "", col.format as ValueFormat)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
