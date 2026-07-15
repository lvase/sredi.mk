import { FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router-dom";
import { KeyRound, LogIn, ShieldCheck } from "lucide-react";
import { useLogin, useSession } from "../hooks/useSession";
import { api, apiErrorMessage, ensureCsrf } from "../lib/api";
import type { AuthNextStep, LoginResult } from "../lib/types";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";

type Phase = "credentials" | Exclude<AuthNextStep, "authenticated"> | "recovery_codes";
type SetupPayload = { secret: string; configuration_url: string; qr_code: string };

export function LoginPage() {
  const session = useSession();
  const login = useLogin();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<Phase>("credentials");
  const [error, setError] = useState("");
  const [setup, setSetup] = useState<SetupPayload | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);

  const securityAction = useMutation({
    mutationFn: async ({ path, body }: { path: string; body: Record<string, unknown> }) => {
      await ensureCsrf();
      return api.post<LoginResult & Partial<SetupPayload>>(path, body);
    },
    onError: (err) => setError(apiErrorMessage(err, "Проверката не успеа. Обиди се повторно."))
  });

  if (session.isLoading) return <LoadingState />;
  if (session.data?.isAuthenticated) return <Navigate to="/staff" replace />;

  function finish(result: LoginResult) {
    if (result.recovery_codes?.length) {
      setRecoveryCodes(result.recovery_codes);
      setPhase("recovery_codes");
      return;
    }
    if (result.authenticated || result.next_step === "authenticated") {
      queryClient.invalidateQueries({ queryKey: ["session"] });
      navigate("/staff", { replace: true });
      return;
    }
    setPhase(result.next_step);
    if (result.next_step === "enroll_superuser_2fa") {
      securityAction.mutate(
        { path: "/auth/security/totp/setup/", body: {} },
        { onSuccess: (data) => setSetup(data as SetupPayload) }
      );
    }
  }

  function handleCredentials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    login.mutate(
      { username: String(data.get("username") || ""), password: String(data.get("password") || "") },
      {
        onSuccess: finish,
        onError: (err) => setError(apiErrorMessage(err, "Невалидно корисничко име или лозинка."))
      }
    );
  }

  function handleToken(event: FormEvent<HTMLFormElement>, enrollment = false) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    securityAction.mutate(
      {
        path: enrollment ? "/auth/security/totp/confirm/" : "/auth/2fa/verify/",
        body: { token: data.get("token"), remember_device: Boolean(data.get("remember_device")) }
      },
      { onSuccess: finish }
    );
  }

  function handlePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    if (data.get("new_password") !== data.get("confirm_password")) {
      setError("Новите лозинки не се совпаѓаат.");
      return;
    }
    securityAction.mutate(
      {
        path: "/auth/security/password/",
        body: { current_password: data.get("current_password"), new_password: data.get("new_password") }
      },
      { onSuccess: finish }
    );
  }

  return (
    <section className="mx-auto max-w-md">
      <Card>
        <CardContent className="p-8">
          <p className="eyebrow">Opštinski Inbox</p>
          <h1 className="mt-2 text-3xl font-black">{phaseTitle(phase)}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{phaseDescription(phase)}</p>
          {error ? <div className="mt-5"><ErrorState message={error} /></div> : null}

          {phase === "credentials" ? (
            <form onSubmit={handleCredentials} className="mt-6 space-y-4">
              <Field label="Корисничко име"><Input name="username" aria-label="Корисничко име" required autoComplete="username" /></Field>
              <Field label="Лозинка"><Input name="password" aria-label="Лозинка" required type="password" autoComplete="current-password" /></Field>
              <Button className="w-full" size="lg" disabled={login.isPending}><LogIn className="h-5 w-5" /> Најави се</Button>
            </form>
          ) : null}

          {phase === "verify_2fa" ? (
            <form onSubmit={(event) => handleToken(event)} className="mt-6 space-y-4">
              <Field label="Код од апликацијата или резервен код"><Input name="token" aria-label="Код од апликацијата или резервен код" required autoComplete="one-time-code" autoFocus /></Field>
              <RememberDevice />
              <Button className="w-full" size="lg" disabled={securityAction.isPending}><ShieldCheck className="h-5 w-5" /> Потврди</Button>
            </form>
          ) : null}

          {phase === "enroll_superuser_2fa" ? (
            setup ? <form onSubmit={(event) => handleToken(event, true)} className="mt-6 space-y-4">
              <img src={setup.qr_code} alt="QR код за authenticator апликација" className="mx-auto h-48 w-48 rounded border" />
              <div className="rounded bg-muted p-3 text-center font-mono text-sm break-all">{setup.secret}</div>
              <Field label="Шестцифрен код"><Input name="token" aria-label="Шестцифрен код" required inputMode="numeric" autoComplete="one-time-code" /></Field>
              <RememberDevice />
              <Button className="w-full" size="lg" disabled={securityAction.isPending}><KeyRound className="h-5 w-5" /> Вклучи 2FA</Button>
            </form> : <LoadingState />
          ) : null}

          {phase === "change_password" ? (
            <form onSubmit={handlePassword} className="mt-6 space-y-4">
              <Field label="Привремена лозинка"><Input name="current_password" aria-label="Привремена лозинка" type="password" required autoComplete="current-password" /></Field>
              <Field label="Нова лозинка"><Input name="new_password" aria-label="Нова лозинка" type="password" required autoComplete="new-password" /></Field>
              <Field label="Повтори ја новата лозинка"><Input name="confirm_password" aria-label="Повтори ја новата лозинка" type="password" required autoComplete="new-password" /></Field>
              <Button className="w-full" size="lg" disabled={securityAction.isPending}>Смени лозинка</Button>
            </form>
          ) : null}

          {phase === "recovery_codes" ? (
            <div className="mt-6 space-y-5">
              <div className="grid grid-cols-2 gap-2 rounded border bg-muted p-4 font-mono text-sm">{recoveryCodes.map((code) => <span key={code}>{code}</span>)}</div>
              <p className="text-sm text-muted-foreground">Зачувај ги сега на безбедно место. Секој код може да се употреби само еднаш.</p>
              <Button className="w-full" onClick={() => { queryClient.invalidateQueries({ queryKey: ["session"] }); navigate("/staff", { replace: true }); }}>Ги зачував кодовите</Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><Label className="mb-2 block">{label}</Label>{children}</div>;
}

function RememberDevice() {
  return <label className="flex items-center gap-2 text-sm"><input name="remember_device" type="checkbox" defaultChecked /> Верувај му на овој прелистувач 30 дена</label>;
}

function phaseTitle(phase: Phase) {
  if (phase === "verify_2fa") return "Безбедносна проверка";
  if (phase === "enroll_superuser_2fa") return "Заштити ја администраторската сметка";
  if (phase === "change_password") return "Постави лична лозинка";
  if (phase === "recovery_codes") return "Резервни кодови";
  return "Најава за службени лица";
}

function phaseDescription(phase: Phase) {
  if (phase === "verify_2fa") return "Внеси код само на нов или недоверлив прелистувач.";
  if (phase === "enroll_superuser_2fa") return "Скенирај го кодот со authenticator апликација. Овој прелистувач потоа може да остане доверлив 30 дена.";
  if (phase === "change_password") return "Привремената лозинка мора да се смени пред пристап до работниот простор.";
  if (phase === "recovery_codes") return "Овие десет кодови се прикажуваат само еднаш.";
  return "Административен простор за обработка на граѓански пријави.";
}
