import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck, Trash2 } from "lucide-react";
import { useSession } from "../../hooks/useSession";
import { api, apiErrorMessage, ensureCsrf } from "../../lib/api";
import type { SecurityStatus } from "../../lib/types";
import { ActionNotice, type ActionFeedback } from "../../components/ActionNotice";
import { LoadingState } from "../../components/LoadingState";
import { ErrorState } from "../../components/ErrorState";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";

type SetupPayload = { secret: string; configuration_url: string; qr_code: string };

export function SecurityPage() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [setup, setSetup] = useState<SetupPayload | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<ActionFeedback | null>(null);
  const status = useQuery({ queryKey: ["security-status"], queryFn: () => api.get<SecurityStatus>("/auth/security/") });
  const action = useMutation({
    mutationFn: async ({ path, body }: { path: string; body: Record<string, unknown> }) => {
      await ensureCsrf();
      return api.post<Record<string, unknown>>(path, body);
    },
    onError: (error) => setFeedback({ tone: "error", message: apiErrorMessage(error, "Промената не успеа.") })
  });
  const revoke = useMutation({
    mutationFn: async (id: number) => { await ensureCsrf(); return api.delete(`/auth/security/trusted-devices/${id}/`); },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["security-status"] })
  });

  if (status.isLoading || session.isLoading) return <LoadingState />;
  if (status.isError || !status.data) return <ErrorState />;

  function beginEnrollment() {
    setFeedback(null);
    action.mutate({ path: "/auth/security/totp/setup/", body: {} }, { onSuccess: (data) => setSetup(data as SetupPayload) });
  }

  function confirmEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    action.mutate(
      { path: "/auth/security/totp/confirm/", body: { token: data.get("token"), remember_device: true } },
      { onSuccess: (result) => {
        setCodes((result.recovery_codes as string[]) || []);
        setSetup(null);
        setFeedback({ tone: "success", message: "2FA е вклучена." });
        queryClient.invalidateQueries({ queryKey: ["security-status"] });
        queryClient.invalidateQueries({ queryKey: ["session"] });
      } }
    );
  }

  function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (data.get("new_password") !== data.get("confirm_password")) {
      setFeedback({ tone: "error", message: "Новите лозинки не се совпаѓаат." });
      return;
    }
    action.mutate(
      { path: "/auth/security/password/", body: { current_password: data.get("current_password"), new_password: data.get("new_password") } },
      { onSuccess: () => { setFeedback({ tone: "success", message: "Лозинката е сменета. Најави се повторно." }); form.reset(); } }
    );
  }

  function regenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    action.mutate(
      { path: "/auth/security/recovery-codes/regenerate/", body: { token: new FormData(form).get("token") } },
      { onSuccess: (result) => { setCodes((result.recovery_codes as string[]) || []); form.reset(); queryClient.invalidateQueries({ queryKey: ["security-status"] }); } }
    );
  }

  function disable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    action.mutate(
      { path: "/auth/security/totp/disable/", body: { password: data.get("password"), token: data.get("token") } },
      { onSuccess: () => { setFeedback({ tone: "success", message: "2FA е исклучена." }); form.reset(); queryClient.invalidateQueries({ queryKey: ["security-status"] }); queryClient.invalidateQueries({ queryKey: ["session"] }); } }
    );
  }

  return <div className="space-y-6">
    <div><p className="eyebrow">Профил</p><h1 className="mt-2 text-4xl font-black">Безбедност</h1><p className="mt-2 text-muted-foreground">Лозинка, доброволна двофакторска заштита и доверливи прелистувачи.</p></div>
    <ActionNotice feedback={feedback} />
    {codes.length ? <Card><CardContent className="p-6"><h2 className="text-xl font-black">Зачувај ги резервните кодови</h2><div className="mt-4 grid max-w-md grid-cols-2 gap-2 rounded border bg-muted p-4 font-mono text-sm">{codes.map((code) => <span key={code}>{code}</span>)}</div><p className="mt-3 text-sm text-muted-foreground">Секој код е еднократен и нема повторно да биде прикажан.</p><Button className="mt-4" variant="outline" onClick={() => setCodes([])}>Ги зачував</Button></CardContent></Card> : null}
    <Card><CardContent className="p-6"><div className="flex items-start justify-between gap-4"><div><h2 className="text-xl font-black">Двофакторска заштита</h2><p className="mt-1 text-sm text-muted-foreground">{status.data.two_factor_enabled ? `Вклучена · ${status.data.recovery_codes_remaining} резервни кодови преостануваат` : "Исклучена · најавата бара само корисничко име и лозинка"}</p></div><ShieldCheck className="h-7 w-7 text-primary" /></div>
      {!status.data.two_factor_enabled && !setup ? <Button className="mt-5" onClick={beginEnrollment}><KeyRound className="h-4 w-4" /> Вклучи 2FA</Button> : null}
      {setup ? <form onSubmit={confirmEnrollment} className="mt-5 max-w-md space-y-4"><img src={setup.qr_code} alt="QR код за authenticator апликација" className="h-48 w-48 rounded border" /><div className="rounded bg-muted p-3 font-mono text-sm break-all">{setup.secret}</div><Field label="Шестцифрен код"><Input name="token" aria-label="Шестцифрен код" required autoComplete="one-time-code" /></Field><Button disabled={action.isPending}>Потврди и вклучи</Button></form> : null}
      {status.data.two_factor_enabled ? <div className="mt-6 grid gap-6 lg:grid-cols-2"><form onSubmit={regenerate} className="space-y-3 rounded border p-4"><h3 className="font-bold">Нови резервни кодови</h3><Field label="Код од апликацијата"><Input name="token" aria-label="Код за нови резервни кодови" required /></Field><Button variant="outline" disabled={action.isPending}>Генерирај</Button></form>{!session.data?.user?.is_superuser ? <form onSubmit={disable} className="space-y-3 rounded border border-red-200 p-4"><h3 className="font-bold">Исклучи 2FA</h3><Field label="Лозинка"><Input name="password" aria-label="Лозинка за исклучување 2FA" type="password" required /></Field><Field label="Код"><Input name="token" aria-label="Код за исклучување 2FA" required /></Field><Button variant="destructive" disabled={action.isPending}>Исклучи</Button></form> : null}</div> : null}
    </CardContent></Card>
    <Card><CardContent className="p-6"><h2 className="text-xl font-black">Смени лозинка</h2><form onSubmit={changePassword} className="mt-4 max-w-md space-y-3"><Field label="Тековна лозинка"><Input name="current_password" aria-label="Тековна лозинка" type="password" required /></Field><Field label="Нова лозинка"><Input name="new_password" aria-label="Нова лозинка" type="password" required /></Field><Field label="Повтори нова лозинка"><Input name="confirm_password" aria-label="Повтори нова лозинка" type="password" required /></Field><Button disabled={action.isPending}>Смени лозинка</Button></form></CardContent></Card>
    <Card><CardContent className="p-6"><h2 className="text-xl font-black">Доверливи прелистувачи</h2><div className="mt-4 divide-y">{status.data.trusted_devices.length ? status.data.trusted_devices.map((device) => <div key={device.id} className="flex items-center justify-between gap-4 py-3"><div className="min-w-0"><p className="truncate text-sm font-bold">{device.label}</p><p className="text-xs text-muted-foreground">Важи до {new Date(device.expires_at).toLocaleDateString("mk-MK")}</p></div><Button size="icon" variant="ghost" aria-label="Отповикај доверлив прелистувач" onClick={() => revoke.mutate(device.id)}><Trash2 className="h-4 w-4" /></Button></div>) : <p className="text-sm text-muted-foreground">Нема активни доверливи прелистувачи.</p>}</div></CardContent></Card>
  </div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <div><Label className="mb-2 block">{label}</Label>{children}</div>; }
