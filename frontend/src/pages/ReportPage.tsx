import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, CheckCircle2, Clipboard, Printer, Send, TriangleAlert, Upload, X } from "lucide-react";
import { api, ApiError, isNotFoundError } from "../lib/api";
import type { FormOptions } from "../lib/types";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { Textarea } from "../components/ui/textarea";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { SectionHeading } from "../components/shared";
import { NotFoundPage } from "./NotFoundPage";

type CreatedIssue = { id: number; tracking_code: string; status: string; status_label: string; receipt_delivery: "queued" | "sent" | "failed" | "not_requested" };
type PhotoPreview = { file: File; url: string; originalName: string };
type FieldErrors = Record<string, string[]>;
type Draft = { settlement?: string; category?: string; location_text?: string; title?: string; description?: string };

const MAX_PHOTOS = 5;
const MAX_PHOTO_SIZE = 5 * 1024 * 1024;
const ALLOWED_PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const FIELD_LABELS: Record<string, string> = { settlement: "Населено место", category: "Категорија", location_text: "Локација", title: "Краток наслов", description: "Опис", photos: "Фотографии", citizen_name: "Име и презиме", citizen_email: "Е-пошта", citizen_phone: "Телефон", send_receipt: "Потврда по е-пошта", consent: "Согласност" };

export function ReportPage() {
  const { municipalitySlug = "" } = useParams();
  const draftKey = `sredi:draft:${municipalitySlug}`;
  const draft = useMemo<Draft>(() => { try { return JSON.parse(sessionStorage.getItem(draftKey) || "{}"); } catch { return {}; } }, [draftKey]);
  const [createdIssue, setCreatedIssue] = useState<CreatedIssue | null>(null);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [photos, setPhotos] = useState<PhotoPreview[]>([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isPreparingPhotos, setIsPreparingPhotos] = useState(false);
  const [copied, setCopied] = useState(false);
  const photosRef = useRef<PhotoPreview[]>([]);
  const summaryRef = useRef<HTMLDivElement>(null);
  const options = useQuery({ queryKey: ["form-options", municipalitySlug], queryFn: () => api.get<FormOptions>(`/municipalities/${municipalitySlug}/form-options/`) });
  const submit = useMutation({
    mutationFn: (formData: FormData) => api.upload<CreatedIssue>(`/municipalities/${municipalitySlug}/issues/`, formData, setUploadProgress),
    onSuccess: (data) => { photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.url)); photosRef.current = []; setPhotos([]); setError(""); setFieldErrors({}); setCreatedIssue(data); sessionStorage.removeItem(draftKey); window.scrollTo({ top: 0, behavior: "smooth" }); },
    onError: (err) => { setUploadProgress(0); if (err instanceof ApiError) { const nextErrors = normalizeFieldErrors(err.errors.errors); setFieldErrors(nextErrors); setCooldownSeconds(err.meta?.retry_after_seconds || 0); setError(Object.keys(nextErrors).length ? "" : err.message); } else setError("Пријавата не е испратена."); }
  });

  useEffect(() => { photosRef.current = photos; }, [photos]);
  useEffect(() => () => photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.url)), []);
  useEffect(() => { if (Object.values(fieldErrors).some((messages) => messages.length > 0)) summaryRef.current?.focus(); }, [fieldErrors]);
  useEffect(() => { if (cooldownSeconds <= 0) return; const timer = window.setInterval(() => setCooldownSeconds((current) => Math.max(0, current - 1)), 1000); return () => window.clearInterval(timer); }, [cooldownSeconds]);

  if (options.isLoading) return <LoadingState />;
  if (isNotFoundError(options.error)) return <NotFoundPage />;
  if (options.isError || !options.data) return <ErrorState message="Не може да се вчита формата." />;

  if (createdIssue) return <Receipt issue={createdIssue} municipalitySlug={municipalitySlug} copied={copied} onCopy={async () => { await navigator.clipboard.writeText(createdIssue.tracking_code); setCopied(true); window.setTimeout(() => setCopied(false), 2500); }} />;

  function persistDraft(form: HTMLFormElement) {
    const data = new FormData(form);
    const safeDraft: Draft = {};
    (["settlement", "category", "location_text", "title", "description"] as const).forEach((key) => { safeDraft[key] = String(data.get(key) || ""); });
    sessionStorage.setItem(draftKey, JSON.stringify(safeDraft));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submit.isPending || isPreparingPhotos || cooldownSeconds > 0) return;
    setError(""); setFieldErrors({}); setUploadProgress(0);
    const formData = new FormData(event.currentTarget);
    formData.set("consent", formData.get("consent") ? "on" : "");
    formData.set("send_receipt", formData.get("send_receipt") ? "on" : "");
    formData.delete("photos");
    photos.forEach((photo) => formData.append("photos", photo.file));
    submit.mutate(formData);
  }

  async function addPhotos(files: File[]) {
    if (isPreparingPhotos) return;
    setIsPreparingPhotos(true);
    const errors: string[] = [];
    const prepared: PhotoPreview[] = [];
    const available = MAX_PHOTOS - photosRef.current.length;
    if (files.length > available) errors.push(`Може да прикачиш најмногу ${MAX_PHOTOS} фотографии.`);
    for (const file of files.slice(0, available)) {
      if (!ALLOWED_PHOTO_TYPES.has(file.type)) {
        errors.push(`${file.name}: форматот не е JPG, PNG или WEBP.`);
        continue;
      }
      try {
        prepared.push(await prepareBrowserPhoto(file));
      } catch (photoError) {
        errors.push(`${file.name}: ${photoError instanceof Error ? photoError.message : "фотографијата не може да се обработи."}`);
      }
    }
    const next = [...photosRef.current, ...prepared];
    photosRef.current = next;
    setPhotos(next);
    setFieldErrors((current) => ({ ...current, photos: errors }));
    setIsPreparingPhotos(false);
  }

  function removePhoto(index: number) {
    const removed = photosRef.current[index];
    if (removed) URL.revokeObjectURL(removed.url);
    const next = photosRef.current.filter((_, photoIndex) => photoIndex !== index);
    photosRef.current = next;
    setPhotos(next);
  }

  const initialSettlement = draft.settlement && options.data.settlements.some((item) => String(item.id) === draft.settlement) ? draft.settlement : String(options.data.settlements[0]?.id || "");
  const initialCategory = draft.category && options.data.categories.some((item) => String(item.id) === draft.category) ? draft.category : String(options.data.categories[0]?.id || "");

  return (
    <section className="mx-auto max-w-[760px]">
      <div className="mb-10 border-b pb-8"><p className="eyebrow">{options.data.municipality.name}</p><h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Пријави локален проблем</h1><p className="mt-4 max-w-2xl text-lg leading-7 text-muted-foreground">Полињата со ѕвездичка се задолжителни. Контактот и фотографиите се по избор.</p></div>
      <form className="report-form space-y-6" onSubmit={handleSubmit} onInput={(event) => persistDraft(event.currentTarget)} onChange={(event) => persistDraft(event.currentTarget)} noValidate>
        <input type="hidden" name="website" value="" />
        {Object.values(fieldErrors).some((messages) => messages.length > 0) ? <div ref={summaryRef} tabIndex={-1} role="alert" aria-labelledby="error-summary-title" className="rounded-md border border-red-300 bg-red-50 p-5"><h2 id="error-summary-title" className="font-semibold text-red-900">Провери ги означените полиња</h2><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-red-800">{Object.entries(fieldErrors).flatMap(([field, messages]) => messages.map((message) => <li key={`${field}-${message}`}><a className="underline" href={`#${field}`}>{FIELD_LABELS[field] || field}: {message}</a></li>))}</ul></div> : null}
        {error ? <ErrorState message={error} /> : null}
        {cooldownSeconds > 0 ? <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm font-semibold text-amber-950" role="status">Нова пријава ќе може да се испрати за {formatCooldown(cooldownSeconds)}.</div> : null}

        <section><SectionHeading number="01" title="Каде е проблемот?" description="Одбери ја областа и наведи адреса или препознатлива насока." /><div className="grid grid-cols-1 gap-5 md:grid-cols-2"><Field id="settlement" label="Населено место" requirement="задолжително" errors={fieldErrors.settlement}><Select id="settlement" name="settlement" defaultValue={initialSettlement} required aria-invalid={Boolean(fieldErrors.settlement)}>{options.data.settlements.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field><Field id="category" label="Категорија" requirement="задолжително" errors={fieldErrors.category}><Select id="category" name="category" defaultValue={initialCategory} required aria-invalid={Boolean(fieldErrors.category)}>{options.data.categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field><Field id="location_text" label="Локација / адреса / насока" requirement="задолжително" className="md:col-span-2" errors={fieldErrors.location_text}><Input id="location_text" name="location_text" defaultValue={draft.location_text} autoComplete="street-address" placeholder="Пр. улица, маало, близу објект…" required aria-invalid={Boolean(fieldErrors.location_text)} /></Field></div></section>

        <section><SectionHeading number="02" title="Што треба да се среди?" description="Опиши го проблемот јасно и без лични податоци за други лица." /><div className="space-y-5"><Field id="title" label="Краток наслов" requirement="задолжително" errors={fieldErrors.title}><Input id="title" name="title" defaultValue={draft.title} autoComplete="off" placeholder="Пр. Не работи улично светло" required aria-invalid={Boolean(fieldErrors.title)} /></Field><Field id="description" label="Опис на проблемот" requirement="задолжително" errors={fieldErrors.description}><Textarea id="description" name="description" maxLength={5000} defaultValue={draft.description} placeholder="Опиши што се случува, колку долго трае и дали има ризик." required aria-invalid={Boolean(fieldErrors.description)} /></Field><Field id="photos" label="Фотографии" requirement="незадолжително" errors={fieldErrors.photos}><label htmlFor="photos" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addPhotos(Array.from(event.dataTransfer.files)); }} className="flex min-h-28 cursor-pointer items-center gap-4 rounded-lg border border-dashed bg-white p-5 hover:border-primary"><Upload className="h-6 w-6 shrink-0 text-primary" /><span><strong className="block">Додај фотографии</strong><small className="mt-1 block text-muted-foreground">JPG, PNG или WEBP · до 5 MB · максимум 5</small></span></label><input id="photos" name="photos" className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => { addPhotos(Array.from(event.target.files || [])); event.target.value = ""; }} />{photos.length ? <div className="mt-3 grid gap-3 sm:grid-cols-2">{photos.map((photo, index) => <div key={`${photo.file.name}-${photo.file.lastModified}`} className="relative overflow-hidden rounded-md border bg-muted"><img src={photo.url} alt={photo.originalName} className="h-32 w-full object-cover" /><div className="flex items-center justify-between gap-2 p-2 text-xs"><span className="truncate">{photo.originalName}</span><Button type="button" size="icon" variant="outline" aria-label={`Отстрани ${photo.originalName}`} onClick={() => removePhoto(index)}><X className="h-4 w-4" /></Button></div></div>)}</div> : null}</Field></div></section>

        <section><SectionHeading number="03" title="Контакт, ако сакаш" description="Контактот не е задолжителен. Е-пошта е потребна само ако сакаш потврда." /><div className="grid grid-cols-1 gap-5 md:grid-cols-2"><Field id="citizen_name" label="Име и презиме" requirement="незадолжително" errors={fieldErrors.citizen_name}><Input id="citizen_name" name="citizen_name" autoComplete="name" /></Field><Field id="citizen_email" label="Е-пошта" requirement="незадолжително" errors={fieldErrors.citizen_email}><Input id="citizen_email" name="citizen_email" type="email" inputMode="email" autoComplete="email" /></Field><Field id="citizen_phone" label="Телефон" requirement="незадолжително" errors={fieldErrors.citizen_phone}><Input id="citizen_phone" name="citizen_phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+389 7…" /></Field></div><label id="send_receipt" className="mt-5 flex min-h-11 gap-3 border p-4 text-sm"><input name="send_receipt" type="checkbox" className="mt-1" /><span><strong>Испрати ми потврда по е-пошта</strong><small className="mt-1 block text-muted-foreground">Ќе го добиеш приватниот код на внесената адреса.</small></span></label><FieldError messages={fieldErrors.send_receipt} /><div className="mt-5 flex gap-3 border-l-4 border-amber-400 bg-amber-50 p-4 text-sm text-amber-950"><TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" /><p>Намерно лажни, измамнички или манипулирани пријави може да бидат отфрлени. <Link className="font-bold underline" to="/uslovi">Прочитај ги целосните услови.</Link></p></div><label id="consent" className="mt-5 flex min-h-11 gap-3 border bg-muted p-4 text-sm"><input name="consent" type="checkbox" required className="mt-1" /><span>Се согласувам пријавата да биде обработена од општината. <strong>*</strong></span></label><FieldError messages={fieldErrors.consent} /><div className="mt-7 border-t pt-6"><div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs text-muted-foreground">Контакт, согласност и фотографии не се зачувуваат како нацрт во овој уред.</p><Button disabled={submit.isPending || isPreparingPhotos || cooldownSeconds > 0} size="lg"><Send className="h-5 w-5" /> {isPreparingPhotos ? "Се обработуваат фотографии…" : submit.isPending ? "Се испраќа…" : cooldownSeconds > 0 ? `Почекај ${formatCooldown(cooldownSeconds)}` : "Испрати пријава"}</Button></div>{submit.isPending ? <div className="mt-4" role="status" aria-live="polite"><div className="mb-1 flex justify-between text-xs"><span>Испраќање на пријавата</span><span>{uploadProgress}%</span></div><div className="h-2 overflow-hidden bg-slate-200"><div className="h-full bg-primary transition-[width]" style={{ width: `${uploadProgress}%` }} /></div></div> : null}</div></section>
      </form>
    </section>
  );
}

function Receipt({ issue, municipalitySlug, copied, onCopy }: { issue: CreatedIssue; municipalitySlug: string; copied: boolean; onCopy: () => void }) {
  return (
    <section className="print-receipt mx-auto max-w-2xl">
      <Card><CardContent className="p-8 text-center">
        <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-primary" />
        <h1 className="text-3xl font-semibold">Пријавата е примена</h1>
        <p className="mt-2 text-muted-foreground">Зачувај го приватниот код. Со него го проверуваш статусот без профил.</p>
        <div className="my-6 rounded-lg border bg-muted p-6">
          <p className="eyebrow">Код за следење</p>
          <p className="mt-2 break-all font-mono text-4xl font-semibold text-primary">{issue.tracking_code}</p>
          <Button className="no-print mt-4" variant="outline" onClick={onCopy}>{copied ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}{copied ? "Кодот е копиран" : "Копирај код"}</Button>
        </div>
        {issue.receipt_delivery === "queued" ? <p className="mb-5 text-sm text-emerald-700">Потврдата е ставена во редица за испраќање по е-пошта.</p> : null}
        {issue.receipt_delivery === "sent" ? <p className="mb-5 text-sm text-emerald-700">Потврдата е испратена по е-пошта.</p> : null}
        {issue.receipt_delivery === "failed" ? <p className="mb-5 text-sm text-amber-800">Пријавата е успешна, но е-поштата не можеше да се стави во редица. Зачувај го кодот од екранот.</p> : null}
        <div className="no-print flex flex-col justify-center gap-3 sm:flex-row"><Button asChild size="lg"><Link to={`/${municipalitySlug}/sledi?code=${issue.tracking_code}`}>Провери статус</Link></Button><Button variant="outline" size="lg" onClick={() => window.print()}><Printer className="h-5 w-5" /> Печати / зачувај потврда</Button></div>
      </CardContent></Card>
    </section>
  );
}

async function prepareBrowserPhoto(source: File): Promise<PhotoPreview> {
  if (!("createImageBitmap" in window)) {
    if (source.size > MAX_PHOTO_SIZE) throw new Error("фотографијата е поголема од 5 MB и прелистувачот не може да ја намали.");
    return { file: source, url: URL.createObjectURL(source), originalName: source.name };
  }
  const bitmap = await createImageBitmap(source, { imageOrientation: "from-image" });
  try {
    const uploadSize = fitWithin(bitmap.width, bitmap.height, 2048);
    const uploadBlob = await canvasBlob(drawBitmap(bitmap, uploadSize.width, uploadSize.height), "image/webp", 0.82);
    if (uploadBlob.type !== "image/webp") {
      if (source.size > MAX_PHOTO_SIZE) throw new Error("фотографијата не може да се претвори во WebP.");
      return { file: source, url: URL.createObjectURL(source), originalName: source.name };
    }
    if (uploadBlob.size > MAX_PHOTO_SIZE) throw new Error("обработената фотографија е поголема од 5 MB.");
    const previewSize = fitWithin(bitmap.width, bitmap.height, 512);
    const previewBlob = await canvasBlob(drawBitmap(bitmap, previewSize.width, previewSize.height), "image/webp", 0.75);
    const filename = `${source.name.replace(/\.[^.]+$/, "") || "photo"}.webp`;
    return {
      file: new File([uploadBlob], filename, { type: "image/webp", lastModified: source.lastModified }),
      url: URL.createObjectURL(previewBlob),
      originalName: source.name
    };
  } finally {
    bitmap.close();
  }
}

function fitWithin(width: number, height: number, maximum: number) {
  const scale = Math.min(1, maximum / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

function drawBitmap(bitmap: ImageBitmap, width: number, height: number) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("фотографијата не може да се обработи.");
  context.drawImage(bitmap, 0, 0, width, height);
  return canvas;
}

function canvasBlob(canvas: HTMLCanvasElement, type: string, quality: number) {
  return new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("фотографијата не може да се обработи.")), type, quality));
}

function Field({ id, label, requirement, className, errors, children }: { id: string; label: string; requirement: "задолжително" | "незадолжително"; className?: string; errors?: string[]; children: React.ReactNode }) { return <div className={className}><Label htmlFor={id} className="mb-2 flex items-center justify-between gap-3"><span>{label}{requirement === "задолжително" ? " *" : ""}</span>{requirement === "незадолжително" ? <small className="font-normal text-muted-foreground">по избор</small> : null}</Label>{children}<FieldError messages={errors} /></div>; }
function FieldError({ messages }: { messages?: string[] }) { if (!messages?.length) return null; return <div className="mt-2 space-y-1 text-sm text-destructive" role="alert">{messages.map((message) => <p key={message}>{message}</p>)}</div>; }
function normalizeFieldErrors(errors?: Record<string, unknown>): FieldErrors { if (!errors) return {}; return Object.fromEntries(Object.entries(errors).map(([key, value]) => [key, Array.isArray(value) ? value.map(String) : [String(value)]])); }
function formatCooldown(seconds: number) { const minutes = Math.floor(seconds / 60); const remaining = seconds % 60; return minutes ? `${minutes}:${String(remaining).padStart(2, "0")} мин.` : `${remaining} сек.`; }
