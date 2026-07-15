import { useMemo, useState } from "react";
import { Link, useSearchParams, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Clock3, HelpCircle, Printer, Search } from "lucide-react";
import { api } from "../lib/api";
import type { Municipality, TrackedIssue } from "../lib/types";
import { formatDate, statusTone } from "../lib/utils";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { StatusTimeline, type TimelineStage } from "../components/shared";
import { ErrorState } from "../components/ErrorState";

const NORMAL_STAGE_INDEX: Record<string, number> = { pending_triage: 0, accepted: 1, assigned: 2, in_progress: 3, waiting_citizen: 3, waiting_external: 3, procurement_needed: 3, resolved: 4, closed: 4 };
const EXCEPTION_LABELS: Record<string, string> = { duplicate: "Оваа пријава е означена како дупликат на веќе постоечка пријава.", rejected_spam: "Пријавата е одбиена како неважечка.", not_jurisdiction: "Проблемот не е во надлежност на оваа општина." };
const STAGES = [["submitted", "Примена"], ["verified", "Проверена"], ["assigned", "Доделена"], ["in_progress", "Во тек"], ["resolved", "Решена"]] as const;

export function TrackPage() {
  const { municipalitySlug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [code, setCode] = useState(normalizeCode(params.get("code") || ""));
  const activeCode = normalizeCode(params.get("code") || "");
  const municipality = useQuery({ queryKey: ["municipality", municipalitySlug], queryFn: () => api.get<Municipality>(`/municipalities/${municipalitySlug}/`) });
  const query = useQuery({ queryKey: ["track", municipalitySlug, activeCode], queryFn: () => api.get<TrackedIssue>(`/municipalities/${municipalitySlug}/track/?code=${encodeURIComponent(activeCode)}`), enabled: Boolean(activeCode) });
  const latest = useMemo(() => query.data?.public_updates.at(-1), [query.data]);
  const timeline = query.data ? buildTimeline(query.data) : null;

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <div className="text-center"><p className="eyebrow">{municipality.data?.name || "Среди"}</p><h1 className="mt-2 text-4xl font-extrabold">Следи пријава</h1><p className="mt-2 text-muted-foreground">Кодот не е јавен. Внеси го без разлика на празни места или цртички.</p></div>
      <Card className="mx-auto max-w-2xl"><CardContent className="p-6"><form className="flex flex-col gap-3 sm:flex-row" onSubmit={(event) => { event.preventDefault(); const normalized = normalizeCode(code); setCode(normalized); setParams(normalized ? { code: normalized } : {}); }}><label htmlFor="tracking-code" className="sr-only">Код за следење</label><Input id="tracking-code" value={code} onChange={(event) => setCode(normalizeCode(event.target.value))} placeholder="AB12CD34EF" autoComplete="off" inputMode="text" className="h-14 font-mono text-xl font-bold uppercase tracking-widest" required /><Button size="lg" className="h-14"><Search className="h-5 w-5" /> Провери</Button></form><details className="mt-4 text-sm"><summary className="flex cursor-pointer items-center gap-2 font-bold text-primary"><HelpCircle className="h-4 w-4" /> Каде е мојот код?</summary><p className="mt-2 pl-6 text-muted-foreground">Го доби веднаш по испраќањето. Ако побара потврда по е-пошта, кодот е и во таа порака. Од безбедносни причини не можеме да го пронајдеме без самиот код.</p></details></CardContent></Card>
      {query.isFetching ? <p className="text-center text-sm text-muted-foreground" role="status">Се проверува…</p> : null}
      {query.isError ? <ErrorState message="Не е пронајдена пријава со тој код во избраната општина." /> : null}
      {query.data ? <div className="print-receipt space-y-6"><Card><CardContent className="flex flex-col justify-between gap-5 p-6 md:flex-row"><div><p className="font-mono text-sm font-bold text-muted-foreground">{query.data.tracking_code}</p><h2 className="mt-1 text-2xl font-extrabold">{query.data.title}</h2><p className="mt-2 text-muted-foreground">{query.data.settlement} · {query.data.category}</p></div><div className="md:text-right"><p className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">Тековен статус</p><Badge variant={statusTone(query.data.status)}>{query.data.status_label}</Badge>{latest ? <p className="mt-3 text-xs text-muted-foreground">Последно ажурирање<br /><time dateTime={latest.created_at}>{formatDate(latest.created_at)}</time></p> : null}</div></CardContent></Card><Card><CardContent className="p-6"><h3 className="mb-6 text-lg font-extrabold">Тек на пријавата</h3>{timeline ? <StatusTimeline stages={timeline.stages} exception={timeline.exception} /> : null}</CardContent></Card><Card><CardContent className="p-6"><h3 className="mb-5 text-lg font-extrabold">Јавни ажурирања</h3><div className="space-y-5">{query.data.public_updates.length ? query.data.public_updates.map((update) => <article key={update.id} className="border-l-2 border-primary pl-4"><time className="text-sm text-muted-foreground" dateTime={update.created_at}>{formatDate(update.created_at)}</time><div className="mt-1 flex flex-wrap items-center gap-2"><h4 className="font-bold">{update.title}</h4>{update.kind === "status" && update.status ? <Badge variant={statusTone(update.status)}>{update.status_label}</Badge> : null}</div><p className="mt-1 whitespace-pre-line text-muted-foreground">{update.body}</p></article>) : <div className="flex gap-3 text-muted-foreground"><Clock3 className="h-5 w-5" /><p>Сè уште нема јавно ажурирање од општината.</p></div>}</div></CardContent></Card><div className="no-print flex flex-wrap justify-between gap-3"><Button asChild variant="outline"><Link to={`/${municipalitySlug}/prijavi`}>Нова пријава</Link></Button><Button variant="outline" onClick={() => window.print()}><Printer className="h-4 w-4" /> Печати / зачувај</Button></div></div> : null}
    </section>
  );
}

function normalizeCode(value: string) { return value.toUpperCase().replace(/[\s-]/g, "").slice(0, 16); }
function buildTimeline(issue: TrackedIssue): { stages: TimelineStage[]; exception: string | null } {
  const currentIndex = NORMAL_STAGE_INDEX[issue.status];
  const exceptional = EXCEPTION_LABELS[issue.status] || null;
  let reached = typeof currentIndex === "number" ? currentIndex : 0;
  if (exceptional) issue.public_updates.forEach((update) => { const index = NORMAL_STAGE_INDEX[update.status]; if (typeof index === "number") reached = Math.max(reached, index); });
  return { stages: STAGES.map(([key, label], index) => ({ key, label, state: exceptional ? (index <= reached ? "complete" : "upcoming") : index < currentIndex ? "complete" : index === currentIndex ? "current" : "upcoming" })), exception: exceptional };
}
