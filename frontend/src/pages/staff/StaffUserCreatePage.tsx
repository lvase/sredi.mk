import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { api, ensureCsrf, ApiError } from "../../lib/api";
import type { Municipality, StaffChoices } from "../../lib/types";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { LoadingState } from "../../components/LoadingState";
import { ErrorState } from "../../components/ErrorState";

export function StaffUserCreatePage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const municipalities = useQuery({
    queryKey: ["municipalities"],
    queryFn: () => api.get<Municipality[]>("/municipalities/")
  });
  const choices = useQuery({
    queryKey: ["staff-choices"],
    queryFn: () => api.get<StaffChoices>("/staff/choices/")
  });
  const createUser = useMutation({
    mutationFn: async (payload: Record<string, string | boolean>) => {
      await ensureCsrf();
      return api.post("/staff/users/", payload);
    },
    onSuccess: () => navigate("/staff"),
    onError: (err) => setError(err instanceof ApiError ? err.message : "Корисникот не е креиран.")
  });

  if (municipalities.isLoading || choices.isLoading) return <LoadingState />;
  if (municipalities.isError || choices.isError || !municipalities.data || !choices.data) return <ErrorState />;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createUser.isPending) return;
    setError("");
    const data = new FormData(event.currentTarget);
    createUser.mutate({
      username: String(data.get("username") || ""),
      email: String(data.get("email") || ""),
      password: String(data.get("password") || ""),
      municipality: String(data.get("municipality") || ""),
      department: String(data.get("department") || ""),
      role: String(data.get("role") || "")
    });
  }

  return (
    <section className="grid gap-8 lg:grid-cols-[360px_1fr]">
      <div>
        <p className="eyebrow">Opštinski Inbox</p>
        <h1 className="mt-2 text-4xl font-black">Нов службен корисник</h1>
        <p className="mt-3 text-muted-foreground">Креирај пристап за општински службеник и ограничи го според општина, одделение и улога.</p>
      </div>
      <Card>
        <CardContent className="p-6">
          {error ? <div className="mb-5"><ErrorState message={error} /></div> : null}
          <form onSubmit={handleSubmit} className="grid gap-4 md:grid-cols-2">
            <Field label="Корисничко име"><Input name="username" aria-label="Корисничко име" required /></Field>
            <Field label="Е-пошта"><Input name="email" aria-label="Е-пошта" type="email" /></Field>
            <Field label="Привремена лозинка"><Input name="password" aria-label="Привремена лозинка" type="password" required /></Field>
            <Field label="Улога"><Select name="role" aria-label="Улога" required>{choices.data.role_choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</Select></Field>
            <Field label="Општина"><Select name="municipality" aria-label="Општина" required>{municipalities.data.map((municipality) => <option key={municipality.id} value={municipality.id}>{municipality.name}</option>)}</Select></Field>
            <Field label="Одделение"><Select name="department" aria-label="Одделение"><option value="">Без одделение</option>{choices.data.departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</Select></Field>
            <p className="rounded-lg border bg-muted p-4 text-sm md:col-span-2">Корисникот мора да ја смени привремената лозинка при првата најава. Потоа може доброволно да вклучи 2FA од „Безбедност“.</p>
            <div className="flex gap-2 border-t pt-5 md:col-span-2">
              <Button disabled={createUser.isPending}><UserPlus className="h-4 w-4" /> {createUser.isPending ? "Се креира..." : "Креирај корисник"}</Button>
              <Button type="button" variant="outline" onClick={() => navigate("/staff")}>Откажи</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </section>
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
