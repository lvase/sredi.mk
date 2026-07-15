import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Globe2, MessageSquare } from "lucide-react";
import { api, apiErrorMessage, ensureCsrf } from "../../lib/api";
import type { StaffChoices, StaffIssueDetail } from "../../lib/types";
import { formatDate, priorityTone, statusTone } from "../../lib/utils";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import { LoadingState } from "../../components/LoadingState";
import { ErrorState } from "../../components/ErrorState";
import { ActionNotice, type ActionFeedback } from "../../components/ActionNotice";
import { StatusTimeline, type TimelineStage } from "../../components/shared";

export function StaffIssueDetailPage() {
  const { issueId = "" } = useParams();
  const queryClient = useQueryClient();
  const [updateFeedback, setUpdateFeedback] = useState<ActionFeedback | null>(null);
  const [statusFeedback, setStatusFeedback] = useState<ActionFeedback | null>(null);
  const [commentFeedback, setCommentFeedback] = useState<ActionFeedback | null>(null);
  const [moderationFeedback, setModerationFeedback] = useState<ActionFeedback | null>(null);
  const issue = useQuery({
    queryKey: ["staff-issue", issueId],
    queryFn: () => api.get<StaffIssueDetail>(`/staff/issues/${issueId}/`)
  });
  const choices = useQuery({
    queryKey: ["staff-choices"],
    queryFn: () => api.get<StaffChoices>("/staff/choices/")
  });
  const updateIssue = useMutation({
    mutationFn: async (payload: Record<string, string>) => {
      await ensureCsrf();
      return api.patch<StaffIssueDetail>(`/staff/issues/${issueId}/`, payload);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["staff-issue", issueId], data);
      queryClient.invalidateQueries({ queryKey: ["staff-issues"] });
      setUpdateFeedback({ tone: "success", message: "Промените се зачувани." });
    },
    onError: (error) => setUpdateFeedback({
      tone: "error",
      message: apiErrorMessage(error, "Промените не се зачувани. Обиди се повторно.")
    })
  });
  const statusIssue = useMutation({
    mutationFn: async (payload: Record<string, string>) => {
      await ensureCsrf();
      return api.post<StaffIssueDetail>(`/staff/issues/${issueId}/status/`, payload);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["staff-issue", issueId], data);
      queryClient.invalidateQueries({ queryKey: ["staff-issues"] });
      setStatusFeedback({ tone: "success", message: "Статусот е зачуван." });
    },
    onError: (error) => setStatusFeedback({
      tone: "error",
      message: apiErrorMessage(error, "Статусот не е зачуван. Обиди се повторно.")
    })
  });
  const commentIssue = useMutation({
    mutationFn: async (payload: Record<string, string | boolean>) => {
      await ensureCsrf();
      return api.post<StaffIssueDetail>(`/staff/issues/${issueId}/comments/`, payload);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["staff-issue", issueId], data);
      setCommentFeedback({ tone: "success", message: "Коментарот е додаден." });
    },
    onError: (error) => setCommentFeedback({
      tone: "error",
      message: apiErrorMessage(error, "Коментарот не е додаден. Обиди се повторно.")
    })
  });
  const moderateTitle = useMutation({
    mutationFn: async ({ action, publicTitle }: { action: "approve" | "revoke"; publicTitle?: string }) => {
      await ensureCsrf();
      return api.post<StaffIssueDetail>(`/staff/issues/${issueId}/public-title/${action}/`, publicTitle ? { public_title: publicTitle } : {});
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["staff-issue", issueId], data);
      queryClient.invalidateQueries({ queryKey: ["statistics"] });
      setModerationFeedback({ tone: "success", message: data.public_title_approved_at ? "Јавниот наслов е одобрен." : "Јавниот наслов е повлечен." });
    },
    onError: (error) => setModerationFeedback({ tone: "error", message: apiErrorMessage(error, "Јавниот наслов не е променет.") })
  });

  if (issue.isLoading || choices.isLoading) return <LoadingState />;
  if (issue.isError || choices.isError || !issue.data || !choices.data) return <ErrorState />;

  const issueDepartments = choices.data.departments.filter(
    (department) => department.municipality?.id === issue.data.municipality_id
  );
  const issueAssignees = choices.data.assignees.filter(
    (user) => user.municipality?.id === issue.data.municipality_id
  );

  function submitUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (updateIssue.isPending) return;
    setUpdateFeedback(null);
    const data = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>;
    updateIssue.mutate(data);
  }

  function submitStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (statusIssue.isPending) return;
    setStatusFeedback(null);
    const data = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>;
    statusIssue.mutate(data);
  }

  function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (commentIssue.isPending) return;
    setCommentFeedback(null);
    const form = event.currentTarget;
    const data = new FormData(form);
    commentIssue.mutate(
      {
        body: String(data.get("body") || ""),
        is_internal: Boolean(data.get("is_internal"))
      },
      { onSuccess: () => form.reset() }
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <Link to="/staff" className="inline-flex items-center gap-1 text-sm text-muted-foreground">
            <ArrowLeft className="h-4 w-4" /> Назад кон работна табла
          </Link>
          <p className="eyebrow mt-4">{issue.data.tracking_code}</p>
          <h1 className="mt-2 text-4xl font-black">{issue.data.title}</h1>
          <p className="mt-2 text-muted-foreground">{issue.data.municipality} · {issue.data.settlement} · {issue.data.category}</p>
        </div>
        <div className="flex gap-2">
          <Badge variant={statusTone(issue.data.status)}>{issue.data.status_label}</Badge>
          <Badge variant={priorityTone(issue.data.priority)}>{issue.data.priority_label}</Badge>
        </div>
      </div>
      <section className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-start gap-3"><Globe2 className="mt-0.5 h-6 w-6 text-primary" /><div><h2 className="text-xl font-black">Јавен наслов</h2><p className="mt-1 text-sm text-muted-foreground">Само одобрениот текст се појавува во јавната статистика. Приватниот наслов погоре останува за службена работа.</p></div></div>
              <div className="mt-4"><ActionNotice feedback={moderationFeedback} /></div>
              {issue.data.permissions.can_moderate_public_title ? <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); const value = String(new FormData(event.currentTarget).get("public_title") || ""); moderateTitle.mutate({ action: "approve", publicTitle: value }); }}>
                <Field label="Текст за јавно објавување"><Textarea name="public_title" aria-label="Текст за јавно објавување" maxLength={180} required defaultValue={issue.data.public_title || issue.data.title} /></Field>
                <div className="flex flex-wrap gap-2"><Button disabled={moderateTitle.isPending}>{issue.data.public_title_approved_at ? "Зачувај измена" : "Одобри за објавување"}</Button>{issue.data.public_title_approved_at ? <Button type="button" variant="destructive" disabled={moderateTitle.isPending} onClick={() => moderateTitle.mutate({ action: "revoke" })}>Повлечи од јавност</Button> : null}</div>
              </form> : <p className="mt-4 font-semibold">{issue.data.public_title_approved_at ? issue.data.public_title : "Насловот сè уште не е одобрен."}</p>}
              {issue.data.public_title_approved_at ? <p data-visual-mask className="mt-3 text-xs text-muted-foreground">Одобрено {formatDate(issue.data.public_title_approved_at)} од {issue.data.public_title_approved_by || "службено лице"}.</p> : <p className="mt-3 text-xs text-amber-700">Не е видлив во листата „Последни 20 пријави“.</p>}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <h2 className="mb-5 text-xl font-black">Тек на пријавата</h2>
              <StatusTimeline stages={staffTimeline(issue.data.status)} exception={staffException(issue.data.status)} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <h2 className="mb-4 text-xl font-black">Опис на пријавата</h2>
              <p className="whitespace-pre-line">{issue.data.description}</p>
              <div className="mt-5 grid gap-3 md:grid-cols-3">
                <Info label="Локација" value={issue.data.location_text} />
                <Info label="Поднесено" value={formatDate(issue.data.submitted_at)} mask />
                <Info label="Сомнителност" value={`${issue.data.suspicious_score}/100`} />
              </div>
              {issue.data.suspicious_reasons.length ? (
                <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-4">
                  <h3 className="font-black text-amber-900">Причини за означување</h3>
                  <ul className="mt-2 space-y-2 text-sm text-amber-900">
                    {issue.data.suspicious_reasons.map((reason) => (
                      <li key={reason.code} className="flex justify-between gap-4">
                        <span>{reason.label}</span>
                        <strong>+{reason.points}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="mt-4 text-sm text-muted-foreground">Нема автоматски откриени сигнали за сомнителност.</p>
              )}
              {issue.data.attachments.length ? (
                <div className="mt-6 border-t pt-5">
                  <h3 className="mb-3 font-black">Фотографии</h3>
                  <div className="flex flex-wrap gap-3">
                    {issue.data.attachments.map((attachment) => (
                      <a key={attachment.id} href={attachment.url}>
                        <img src={attachment.url} alt="Фотографија" className="h-28 w-40 rounded-md border object-cover" />
                      </a>
                    ))}
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>
          {issue.data.permissions.can_comment ? (
            <Card>
              <CardContent className="p-6">
                <h2 className="mb-4 text-xl font-black">Коментари</h2>
                <form onSubmit={submitComment} className="mb-6 space-y-3">
                  <ActionNotice feedback={commentFeedback} />
                  <Textarea name="body" aria-label="Службен коментар" required placeholder="Додај службен коментар..." />
                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-sm"><input name="is_internal" type="checkbox" defaultChecked /> Само за службеници (интерен)</label>
                    <Button disabled={commentIssue.isPending}>
                      <MessageSquare className="h-4 w-4" />
                      {commentIssue.isPending ? "Се додава..." : "Додај коментар"}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">Исклучи ја опцијата за коментарот да се прикаже во „Јавни ажурирања“.</p>
                </form>
                <div className="space-y-4 border-t pt-5">
                  {issue.data.comments.length ? issue.data.comments.map((comment) => (
                    <div key={comment.id} className="border-l-4 border-primary pl-4">
                      <p className="text-sm text-muted-foreground">{formatDate(comment.created_at)} · {comment.author} · {comment.is_internal ? "Интерно" : "Јавно"}</p>
                      <p className="mt-1 whitespace-pre-line">{comment.body}</p>
                    </div>
                  )) : <p className="text-muted-foreground">Нема коментари.</p>}
                </div>
              </CardContent>
            </Card>
          ) : null}
          <Card>
            <CardContent className="p-6">
              <h2 className="mb-4 text-xl font-black">Историја</h2>
              <div className="space-y-4">
                {issue.data.status_events.length ? issue.data.status_events.map((event) => (
                  <div key={event.id} className="border-l-4 border-primary pl-4">
                    <p className="text-sm text-muted-foreground">{formatDate(event.created_at)}</p>
                    <p>{event.from_status || "-"} → <strong>{event.to_status_label}</strong></p>
                    {event.note ? <p className="text-muted-foreground">{event.note}</p> : null}
                  </div>
                )) : <p className="text-muted-foreground">Нема историја.</p>}
              </div>
            </CardContent>
          </Card>
        </div>
        <aside className="space-y-6">
          <Card><CardContent className="p-5"><h2 className="mb-3 font-black">Задолжување</h2><Info label="Одделение" value={issue.data.assigned_department || "Не е доделено"} /><Info label="Вработен" value={issue.data.assigned_to || "Не е доделен"} /></CardContent></Card>
          <Card><CardContent className="p-5"><h2 className="mb-3 font-black">Контакт</h2>{issue.data.is_anonymous ? <p className="text-muted-foreground">Анонимна пријава.</p> : <><Info label="Име" value={issue.data.citizen_name || "-"} /><Info label="Е-пошта" value={issue.data.citizen_email || "-"} /><Info label="Телефон" value={issue.data.citizen_phone || "-"} /></>}</CardContent></Card>
          {issue.data.permissions.can_update ? (
            <Card>
              <CardContent className="p-5">
                <h2 className="mb-4 font-black">Ажурирај</h2>
                <form onSubmit={submitUpdate} className="space-y-3">
                  <ActionNotice feedback={updateFeedback} />
                  <Field label="Приоритет"><Select name="priority" aria-label="Приоритет" defaultValue={issue.data.priority}>{choices.data.priority_choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</Select></Field>
                  <Field label="Одделение"><Select name="assigned_department" aria-label="Одделение" defaultValue={issue.data.assigned_department_id ? String(issue.data.assigned_department_id) : ""}><option value="">Не е доделено</option>{issueDepartments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</Select></Field>
                  <Field label="Вработен"><Select name="assigned_to" aria-label="Вработен" defaultValue={issue.data.assigned_to_id ? String(issue.data.assigned_to_id) : ""}><option value="">Не е доделен</option>{issueAssignees.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}</Select></Field>
                  <Field label="Интерна белешка"><Textarea name="internal_note" aria-label="Интерна белешка" defaultValue={issue.data.internal_note} /></Field>
                  <Field label="Јавна белешка"><Textarea name="public_resolution_note" aria-label="Јавна белешка" defaultValue={issue.data.public_resolution_note} /></Field>
                  <Button disabled={updateIssue.isPending}>{updateIssue.isPending ? "Се зачувува..." : "Зачувај промени"}</Button>
                </form>
              </CardContent>
            </Card>
          ) : null}
          {issue.data.permissions.can_change_status ? (
            <Card>
              <CardContent className="p-5">
                <h2 className="mb-4 font-black">Промени статус</h2>
                <form onSubmit={submitStatus} className="space-y-3">
                  <ActionNotice feedback={statusFeedback} />
                  <Field label="Нов статус"><Select name="status" aria-label="Нов статус" defaultValue={issue.data.status}>{choices.data.status_choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</Select></Field>
                  <Field label="Белешка"><Textarea name="note" aria-label="Белешка за статус" placeholder="Внеси кратка службена белешка..." /></Field>
                  <Button disabled={statusIssue.isPending}>{statusIssue.isPending ? "Се зачувува..." : "Зачувај статус"}</Button>
                </form>
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </section>
    </div>
  );
}

function staffTimeline(status: string): TimelineStage[] {
  const index: Record<string, number> = { pending_triage: 0, accepted: 1, assigned: 2, in_progress: 3, waiting_citizen: 3, waiting_external: 3, procurement_needed: 3, resolved: 4, closed: 4 };
  const current = index[status] ?? 0;
  return [["submitted", "Примена"], ["verified", "Проверена"], ["assigned", "Доделена"], ["in_progress", "Во тек"], ["resolved", "Решена"]].map(([key, label], stage) => ({ key, label, state: stage < current ? "complete" : stage === current ? "current" : "upcoming" }));
}

function staffException(status: string) {
  return ({ duplicate: "Дупликат", rejected_spam: "Одбиена / спам", not_jurisdiction: "Не е во надлежност" } as Record<string, string>)[status] || null;
}

function Info({ label, value, mask = false }: { label: string; value: string; mask?: boolean }) {
  return (
    <div className="rounded-md bg-muted p-3" data-visual-mask={mask || undefined}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-semibold">{value}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <Label className="mb-2 block">{label}</Label>
      {children}
    </div>
  );
}
