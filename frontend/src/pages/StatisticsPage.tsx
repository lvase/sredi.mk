import { FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, isNotFoundError } from "../lib/api";
import type { PublicStatisticsPayload } from "../lib/types";
import { formatDate, statusTone } from "../lib/utils";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState, StatStrip } from "../components/shared";
import { NotFoundPage } from "./NotFoundPage";

export function StatisticsPage() {
  const { municipalitySlug = "" } = useParams();
  const [params, setParams] = useSearchParams({ period: "90" });
  const queryString = params.toString();
  const stats = useQuery({ queryKey: ["statistics", municipalitySlug, queryString], queryFn: () => api.get<PublicStatisticsPayload>(`/municipalities/${municipalitySlug}/statistics/?${queryString}`) });
  if (stats.isLoading) return <LoadingState />;
  if (isNotFoundError(stats.error)) return <NotFoundPage />;
  if (stats.isError || !stats.data) return <ErrorState message="Не може да се вчита статистиката." />;
  const data = stats.data;
  const resolvedRate = data.stats.total ? Math.round(data.stats.resolved * 100 / data.stats.total) : 0;

  function applyFilters(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const next = new URLSearchParams(); new FormData(event.currentTarget).forEach((value, key) => { if (value) next.set(key, String(value)); }); setParams(next); }

  return <div className="space-y-12">
    <header className="grid grid-cols-1 gap-8 border-b pb-8 lg:grid-cols-[1fr_auto] lg:items-end">
      <div><p className="eyebrow">Јавна отчетност</p><h1 className="mt-3 text-5xl font-semibold tracking-[-.04em] md:text-6xl">Статистика за {data.municipality.name}</h1><p className="mt-4 max-w-3xl text-lg leading-7 text-muted-foreground">Агрегиран преглед на пријавите, брзината на постапување и најчестите локални проблеми. Лични податоци, точни локации и приватни описи не се објавуваат.</p></div>
      <Button asChild size="lg"><Link to={`/${municipalitySlug}/prijavi`}>Пријави проблем</Link></Button>
    </header>

    <details className="border-y bg-white" open><summary className="cursor-pointer px-4 py-4 font-bold">Филтри за приказот</summary><form onSubmit={applyFilters} className="grid grid-cols-1 gap-4 border-t p-4 sm:grid-cols-2 lg:grid-cols-5"><Filter label="Период"><Select name="period" defaultValue={data.applied_filters.period}><option value="30">Последни 30 дена</option><option value="90">Последни 90 дена</option><option value="365">Последни 365 дена</option><option value="all">Сите периоди</option></Select></Filter><Filter label="Населено место"><Select name="settlement" defaultValue={data.applied_filters.settlement || ""}><option value="">Сите</option>{data.filter_options.settlements.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</Select></Filter><Filter label="Категорија"><Select name="category" defaultValue={data.applied_filters.category || ""}><option value="">Сите</option>{data.filter_options.categories.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</Select></Filter><Filter label="Јавен статус"><Select name="status" defaultValue={data.applied_filters.status || ""}><option value="">Сите</option>{data.filter_options.statuses.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</Select></Filter><div className="flex flex-wrap items-end gap-2"><Button type="submit">Примени</Button><Button type="button" variant="outline" onClick={() => setParams({ period: "90" })}>Исчисти</Button></div></form></details>

    <section aria-labelledby="overview-title"><div className="grid grid-cols-1 gap-7 lg:grid-cols-[.75fr_1.25fr] lg:items-end"><div><p className="text-sm font-bold text-muted-foreground">Решени или затворени</p><p className="mt-1 text-7xl font-semibold tracking-[-.05em] text-primary">{resolvedRate}%</p><p className="mt-2 text-sm text-muted-foreground">{data.stats.resolved} од вкупно {data.stats.total} пријави во избраниот приказ</p></div><StatStrip label="Основни показатели" items={[{ label: "Вкупно", value: data.stats.total }, { label: "Активни", value: data.stats.open, tone: "info" }, { label: "Чекаат проверка", value: data.stats.pending, tone: "warning" }]} /></div></section>

    <section className="grid grid-cols-1 gap-10 lg:grid-cols-[1.6fr_.8fr]">
      <div><div className="mb-5 border-b pb-4"><h2 className="text-2xl font-semibold">Пријави низ времето</h2><p className="mt-1 text-sm text-muted-foreground">Број на поднесени пријави по временски период.</p></div><TrendChart data={data.time_series} /></div>
      <div><h2 className="border-b pb-4 text-2xl font-semibold">Постапување</h2><dl className="divide-y border-b">{[
        ["Време до проверка", formatHours(data.performance.median_review_hours)],
        ["Време до решение", formatHours(data.performance.median_resolution_hours)],
        ["Решени во целниот рок", formatPercent(data.performance.resolved_within_target_percent)]
      ].map(([label, value]) => <div key={label} className="py-5"><dt className="text-sm font-semibold text-muted-foreground">{label}</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd></div>)}</dl></div>
    </section>

    <section className="grid grid-cols-1 gap-10 lg:grid-cols-2"><Breakdown title="По населено место" rows={data.by_settlement} /><Breakdown title="По категорија" rows={data.by_category} /></section>

    <section><div className="mb-4 flex flex-col justify-between gap-2 border-b pb-4 sm:flex-row sm:items-end"><div><h2 className="text-2xl font-semibold">Последни јавни пријави</h2><p className="mt-1 text-sm text-muted-foreground">Само наслови одобрени за јавниот статистички приказ.</p></div><span className="text-sm text-muted-foreground">до 20 записи</span></div>{data.recent_reports.length ? <ol className="divide-y border-b">{data.recent_reports.map((report, index) => <li key={`${report.submitted_at}-${index}`} className="grid grid-cols-1 gap-2 py-4 sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-5"><h3 className="font-bold">{report.title}</h3><time className="text-sm text-muted-foreground" dateTime={report.submitted_at}>{formatDate(report.submitted_at)}</time><Badge className="w-fit" variant={statusTone(report.status)}>{report.status_label}</Badge></li>)}</ol> : <EmptyState title="Нема јавни пријави за периодот" description="Смени ги филтрите или провери повторно подоцна." />}</section>

    <footer className="grid grid-cols-1 gap-8 border-t pt-7 text-sm lg:grid-cols-[1.4fr_1fr]"><div><h2 className="font-semibold">Методологија и приватност</h2><p className="mt-2 max-w-3xl leading-6 text-muted-foreground">{data.suppression.message} Во овој приказ се потиснати {data.suppression.suppressed_category_groups + data.suppression.suppressed_settlement_groups} групи и {data.suppression.suppressed_time_buckets} временски периоди. Празен приказ може да значи дека нема податоци или дека групата е премала за безбедно објавување.</p>{Object.keys(data.definitions).length ? <details className="mt-3"><summary className="cursor-pointer font-bold text-primary">Дефиниции на показателите</summary><dl className="mt-3 space-y-2">{Object.entries(data.definitions).map(([term, definition]) => <div key={term}><dt className="font-semibold">{term}</dt><dd className="text-muted-foreground">{definition}</dd></div>)}</dl></details> : null}</div><div className="lg:text-right"><p className="text-muted-foreground">{data.last_updated ? <>Последно ажурирање: <span data-visual-mask>{formatDate(data.last_updated)}</span></> : "Нема податок за последно ажурирање."}</p><Button asChild variant="outline" className="mt-4"><a href={api.url(`/municipalities/${municipalitySlug}/statistics.csv/?${queryString}`)}><Download className="h-4 w-4" /> Преземи CSV</a></Button></div></footer>
  </div>;
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) { return <label className="text-sm font-semibold">{label}<span className="mt-1 block">{children}</span></label>; }

function TrendChart({ data }: { data: PublicStatisticsPayload["time_series"] }) {
  if (!data.length || !data.some((point) => point.total !== null)) return <EmptyState title="Нема доволно податоци за тренд" description="Временските групи без доволно пријави не се прикажуваат." />;
  const max = Math.max(...data.map((point) => point.total || 0), 1);
  const width = 720; const height = 250; const chartHeight = 190; const gap = 3; const barWidth = Math.max(2, width / data.length - gap);
  return <><svg className="h-auto w-full border-b" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Графикон на бројот на пријави низ времето"><line x1="0" y1={chartHeight} x2={width} y2={chartHeight} stroke="currentColor" opacity=".2" />{data.map((point, index) => { const value = point.total || 0; const barHeight = value * (chartHeight - 10) / max; return point.total === null ? <rect key={point.bucket} x={index * width / data.length} y={chartHeight - 3} width={barWidth} height="3" fill="currentColor" opacity=".15" /> : <rect key={point.bucket} x={index * width / data.length} y={chartHeight - barHeight} width={barWidth} height={barHeight} fill="hsl(var(--primary))"><title>{point.bucket}: {value} пријави</title></rect>; })}{[0, Math.floor((data.length - 1) / 2), data.length - 1].map((index) => <text key={index} x={index * width / data.length} y="225" fontSize="13" fill="currentColor" opacity=".65">{formatBucket(data[index]?.bucket)}</text>)}</svg><ul className="sr-only">{data.map((point) => <li key={point.bucket}>{point.bucket}: {point.total === null ? "потиснато за приватност" : `${point.total} пријави`}</li>)}</ul></>;
}

function Breakdown({ title, rows }: { title: string; rows: Array<{ label: string; total: number }> }) { const max = Math.max(...rows.map((row) => row.total), 1); return <section><h2 className="mb-5 border-b pb-4 text-2xl font-semibold">{title}</h2>{rows.length ? <ol className="space-y-5">{rows.map((row) => <li key={row.label}><div className="mb-1 flex justify-between gap-4 text-sm"><span className="font-semibold">{row.label}</span><strong className="tabular-nums">{row.total}</strong></div><div className="bar-track" aria-hidden="true"><div className="bar-fill" style={{ width: `${row.total * 100 / max}%` }} /></div></li>)}</ol> : <EmptyState title="Нема доволно податоци" description="Групите со помалку од пет пријави не се прикажуваат." />}</section>; }
function formatHours(value: number | null) { if (value === null) return "Нема податок"; if (value < 24) return `${Math.round(value)} ч.`; return `${(value / 24).toFixed(1)} дена`; }
function formatPercent(value: number | null) { return value === null ? "Нема податок" : `${Math.round(value)}%`; }
function formatBucket(value?: string) { if (!value) return ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("mk-MK", { month: "short", year: "2-digit" }); }
