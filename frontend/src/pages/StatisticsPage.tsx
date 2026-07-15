import { FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Download, Info, PlusCircle } from "lucide-react";
import { api } from "../lib/api";
import type { PublicStatisticsPayload } from "../lib/types";
import { formatDate, statusTone } from "../lib/utils";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState, MetricCard, PageHeader } from "../components/shared";

export function StatisticsPage() {
  const { municipalitySlug = "" } = useParams();
  const [params, setParams] = useSearchParams({ period: "90" });
  const queryString = params.toString();
  const stats = useQuery({ queryKey: ["statistics", municipalitySlug, queryString], queryFn: () => api.get<PublicStatisticsPayload>(`/municipalities/${municipalitySlug}/statistics/?${queryString}`) });
  if (stats.isLoading) return <LoadingState />;
  if (stats.isError || !stats.data) return <ErrorState message="Не може да се вчита статистиката." />;
  const data = stats.data;

  function applyFilters(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const next = new URLSearchParams(); new FormData(event.currentTarget).forEach((value, key) => { if (value) next.set(key, String(value)); }); setParams(next); }

  return <div className="space-y-8">
    <PageHeader eyebrow="Јавна отчетност" title={`Статистика · ${data.municipality.name}`} description="Преглед на пријавите и најновите наслови, без описи, точни локации, фотографии, кодови или контакт податоци." actions={<Button asChild size="lg"><Link to={`/${municipalitySlug}/prijavi`}><PlusCircle className="h-5 w-5" /> Пријави проблем</Link></Button>} />
    <Card><CardContent className="p-5"><form onSubmit={applyFilters} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><label className="text-sm font-semibold">Период<Select name="period" className="mt-1" defaultValue={data.applied_filters.period}><option value="30">Последни 30 дена</option><option value="90">Последни 90 дена</option><option value="365">Последни 365 дена</option><option value="all">Сите периоди</option></Select></label><label className="text-sm font-semibold">Населено место<Select name="settlement" className="mt-1" defaultValue={data.applied_filters.settlement || ""}><option value="">Сите</option>{data.filter_options.settlements.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</Select></label><label className="text-sm font-semibold">Категорија<Select name="category" className="mt-1" defaultValue={data.applied_filters.category || ""}><option value="">Сите</option>{data.filter_options.categories.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</Select></label><label className="text-sm font-semibold">Јавен статус<Select name="status" className="mt-1" defaultValue={data.applied_filters.status || ""}><option value="">Сите</option>{data.filter_options.statuses.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</Select></label><div className="flex items-end gap-2"><Button type="submit">Примени</Button><Button type="button" variant="outline" onClick={() => setParams({ period: "90" })}>Исчисти</Button></div></form></CardContent></Card>
    <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Основни показатели"><MetricCard label="Вкупно пријави" value={data.stats.total} /><MetricCard label="Активни" value={data.stats.open} tone="info" /><MetricCard label="Решени / затворени" value={data.stats.resolved} tone="success" /><MetricCard label="Чекаат проверка" value={data.stats.pending} tone="warning" /></section>
    <Card><CardContent className="p-0"><div className="flex items-center gap-3 border-b p-6"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-100 text-primary"><ClipboardList className="h-5 w-5" /></span><div><h2 className="text-xl font-extrabold">Последни 20 пријави</h2><p className="mt-1 text-sm text-muted-foreground">Најновите пријави што одговараат на избраните филтри.</p></div></div>{data.recent_reports.length ? <ol className="divide-y">{data.recent_reports.map((report, index) => <li key={`${report.submitted_at}-${index}`} className="flex flex-col justify-between gap-3 p-5 sm:flex-row sm:items-center"><div className="min-w-0"><h3 className="font-bold text-foreground">{report.title}</h3><time className="mt-1 block text-xs text-muted-foreground" dateTime={report.submitted_at}>{formatDate(report.submitted_at)}</time></div><Badge className="w-fit shrink-0" variant={statusTone(report.status)}>{report.status_label}</Badge></li>)}</ol> : <div className="p-6"><EmptyState icon={<ClipboardList />} title="Нема пријави за периодот" description="Смени ги филтрите или провери повторно подоцна." /></div>}</CardContent></Card>
    <section className="grid gap-4 lg:grid-cols-2"><Breakdown title="По населено место" rows={data.by_settlement} /><Breakdown title="По категорија" rows={data.by_category} /></section>
    <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950"><div className="flex gap-3"><Info className="mt-0.5 h-5 w-5 shrink-0" /><div><strong>Заштита на мали групи</strong><p className="mt-1">{data.suppression.message} Потиснати се {data.suppression.suppressed_category_groups + data.suppression.suppressed_settlement_groups} групи во овој приказ.</p></div></div></div>
    <Card><CardContent className="flex flex-col justify-between gap-5 p-6 md:flex-row md:items-center"><div><h2 className="font-extrabold">Преземи агрегирани податоци</h2><p className="mt-1 text-sm text-muted-foreground">CSV-датотеката ги користи тековните филтри и ги означува потиснатите групи со „&lt;5“.</p>{data.last_updated ? <p data-visual-mask className="mt-2 text-xs text-muted-foreground">Последно ажурирање: {formatDate(data.last_updated)}</p> : null}</div><Button asChild variant="outline"><a href={api.url(`/municipalities/${municipalitySlug}/statistics.csv/?${queryString}`)}><Download className="h-4 w-4" /> Преземи CSV</a></Button></CardContent></Card>
  </div>;
}

function Breakdown({ title, rows }: { title: string; rows: Array<{ label: string; total: number }> }) { const max = Math.max(...rows.map((row) => row.total), 1); return <Card><CardContent className="p-6"><h2 className="mb-5 text-xl font-extrabold">{title}</h2>{rows.length ? <ul className="space-y-4">{rows.map((row) => <li key={row.label}><div className="mb-1 flex justify-between gap-4 text-sm"><span>{row.label}</span><strong>{row.total}</strong></div><div className="bar-track" aria-hidden="true"><div className="bar-fill" style={{ width: `${row.total * 100 / max}%` }} /></div></li>)}</ul> : <EmptyState title="Нема доволно податоци" description="Групите со помалку од пет пријави не се прикажуваат." />}</CardContent></Card>; }
