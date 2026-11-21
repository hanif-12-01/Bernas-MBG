"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Loader2, Plus, Play } from "lucide-react";

import { ErrorState } from "@/components/feedback/FeedbackStates";
import { NumericInput } from "@/components/ui/NumericInput";
import { useWorkspace } from "@/hooks/useWorkspace";
import { parseNumericInput } from "@/lib/formatters/numericInput";
import { formatDateTimeID } from "@/lib/formatters/indonesian";
import { getJakartaTodayISO } from "@/lib/formatters/jakartaDate";

const numberFields = [
  { key: "servings_per_day", label: "Porsi per hari", mode: "integer", min: 1, max: 10000 },
  { key: "days", label: "Jumlah hari", mode: "integer", min: 1, max: 14 },
  { key: "budget_idr_per_serving", label: "Anggaran per porsi (Rp)", mode: "decimal", min: 0.01 },
  { key: "max_repeat_per_family", label: "Maksimum pengulangan keluarga resep", mode: "integer", min: 1, max: 14 },
] as const;

const initialNumbers = {
  servings_per_day: "100",
  days: "5",
  budget_idr_per_serving: "12000",
  max_repeat_per_family: "2",
};

export function ScenarioPlanningForm({ initialDatasetId = "", expanded = false }: {
  initialDatasetId?: string;
  expanded?: boolean;
}) {
  const {
    datasets, scenarios, runs, createScenario, optimizeScenario, isOptimizingScenario,
  } = useWorkspace();
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const resultsLink = useRef<HTMLAnchorElement>(null);
  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState(initialDatasetId);
  const [startDate, setStartDate] = useState(() => getJakartaTodayISO());
  const [numbers, setNumbers] = useState(initialNumbers);
  const [attempted, setAttempted] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const [open, setOpen] = useState(expanded);
  const busy = creating || isOptimizingScenario;
  const dataset = datasets.find((entry) => entry.id === datasetId);
  const runScenarioIds = new Set(runs.map((run) => run.scenario_id));
  const pending = scenarios.filter((scenario) => !scenario.locked && !runScenarioIds.has(scenario.id) && !scenario.parent_scenario_id);
  const parsed = numberFields.map((field) => ({
    ...field,
    result: parseNumericInput(numbers[field.key], field),
  }));

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempted(true);
    setError(null);
    setCompleted(false);
    if (!dataset || !name.trim() || parsed.some(({ result }) => !result.valid)) {
      requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus());
      return;
    }

    setCreating(true);
    try {
      const [servings, days, budget, repeat] = parsed.map(({ result }) => result.valid ? result.value : Number.NaN);
      const created = await createScenario({
        name: name.trim(),
        dataset_version_id: dataset.id,
        source_label: dataset.source_type,
        servings_per_day: servings,
        days,
        budget_idr_per_serving: budget,
        max_repeat_per_family: repeat,
        production_date: startDate ? `${startDate}T08:00:00Z` : undefined,
      });
      setName("");
      setAttempted(false);
      void calculate(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Skenario gagal disimpan.");
    } finally {
      setCreating(false);
    }
  }

  async function calculate(scenarioId: string) {
    setError(null);
    setCompleted(false);
    try {
      await optimizeScenario(scenarioId);
      setCompleted(true);
      requestAnimationFrame(() => resultsLink.current?.focus());
    } catch (cause) {
      setError(`Skenario tersimpan. ${cause instanceof Error ? cause.message : "Hasil belum dapat dimuat."} Coba hitung kembali dari daftar skenario tersimpan.`);
    }
  }

  return (
    <details id="buat-rencana" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}
      className="min-w-0 scroll-mt-20 rounded-2xl border border-[#B5DFDA] bg-white">
      <summary className="flex min-h-[52px] cursor-pointer list-none items-center gap-2 rounded-2xl px-4 py-3.5 text-sm font-bold text-[#0F766E] [&::-webkit-details-marker]:hidden">
        <Plus className="h-5 w-5 shrink-0" aria-hidden="true" />
        Buat Rencana Menu
      </summary>
      <div className="space-y-4 border-t border-[#DCE6DE] p-4 sm:p-5">
        {datasets.length === 0 ? (
          <p className="text-sm text-[#4A6170]">
            Belum ada dataset untuk dapur ini.{" "}
            <Link href="/settings" className="font-semibold text-[#0F766E] underline">Impor dataset CSV</Link>{" "}
            untuk mulai merencanakan menu.
          </p>
        ) : (
          <form ref={formRef} noValidate onSubmit={handleSubmit} className="space-y-4">
            <fieldset disabled={busy} className="grid min-w-0 gap-3 sm:grid-cols-2">
              <div className="min-w-0">
                <label htmlFor={`${id}-name`} className="block text-sm font-semibold">Nama rencana</label>
                <input id={`${id}-name`} value={name} onChange={(event) => setName(event.target.value)}
                  required maxLength={120} aria-invalid={attempted && !name.trim()}
                  aria-describedby={attempted && !name.trim() ? `${id}-name-error` : undefined}
                  className="mt-1 min-h-[44px] w-full rounded-xl border border-[#DCE6DE] px-3 text-base sm:text-sm" />
                {attempted && !name.trim() && <p id={`${id}-name-error`} className="mt-1 text-xs text-[#991B1B]">Isi nama rencana.</p>}
              </div>
              <div className="min-w-0">
                <label htmlFor={`${id}-dataset`} className="block text-sm font-semibold">Dataset bahan, harga dan stok</label>
                <select id={`${id}-dataset`} required value={datasetId} onChange={(event) => setDatasetId(event.target.value)}
                  aria-invalid={attempted && !dataset} aria-describedby={attempted && !dataset ? `${id}-dataset-error` : undefined}
                  className="mt-1 min-h-[44px] w-full min-w-0 rounded-xl border border-[#DCE6DE] bg-white px-3 text-base sm:text-sm">
                  <option value="">Pilih versi dataset</option>
                  {datasets.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name} ({entry.is_synthetic ? "Simulasi" : "Impor"}, {formatDateTimeID(entry.created_at)})
                    </option>
                  ))}
                </select>
                {attempted && !dataset && <p id={`${id}-dataset-error`} className="mt-1 text-xs text-[#991B1B]">Pilih versi dataset.</p>}
              </div>
              {parsed.map(({ key, label, mode, min, result, ...bounds }) => (
                <div key={key}>
                  <span aria-hidden="true" className="block text-sm font-semibold">{label}</span>
                  <NumericInput id={`${id}-${key}`} label={label} mode={mode} min={min}
                    max={"max" in bounds ? bounds.max : undefined}
                    value={numbers[key]} onChange={(value) => setNumbers((previous) => ({ ...previous, [key]: value }))}
                    error={attempted && !result.valid ? result.error : null}
                    className="mt-1 min-h-[44px] w-full text-base sm:text-sm" />
                </div>
              ))}
              <div className="min-w-0">
                <label htmlFor={`${id}-start-date`} className="block text-sm font-semibold">
                  Tanggal mulai pelayanan
                </label>
                <input
                  id={`${id}-start-date`}
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                  className="mt-1 min-h-[44px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-base sm:text-sm"
                />
              </div>
            </fieldset>
            <p className="text-xs leading-relaxed text-[#647A87]">
              Perhitungan memakai dataset terpilih dan target gizi simulasi.{" "}
              <Link href="/settings" className="font-semibold text-[#0F766E] underline">Kelola versi dataset</Link>
            </p>
            <button type="submit" disabled={busy} className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60 sm:w-auto">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
              {busy ? "Menyimpan dan menghitung…" : "Simpan & Hitung Rencana"}
            </button>
          </form>
        )}
        {error && <ErrorState title="Rencana belum selesai" message={error} />}
        {completed && (
          <p role="status" className="rounded-xl bg-[#EBF6F5] px-3 py-2 text-sm font-semibold text-[#0F766E]">
            Hasil perhitungan tersimpan. <a ref={resultsLink} href="#hasil-rencana" className="underline">Lihat hasil</a>
          </p>
        )}
        {pending.length > 0 && (
          <section className="space-y-2" aria-label="Skenario tersimpan tanpa hasil">
            <h3 className="text-sm font-bold">Skenario tersimpan tanpa hasil</h3>
            {pending.map((scenario) => (
              <div key={scenario.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#DCE6DE] px-3 py-2">
                <span className="min-w-0 break-words text-sm">{scenario.name}</span>
                <button type="button" disabled={busy} onClick={() => void calculate(scenario.id)}
                  className="min-h-[44px] rounded-xl border border-[#B5DFDA] px-3 text-sm font-semibold text-[#0F766E] disabled:opacity-60">
                  Hitung Rencana
                </button>
              </div>
            ))}
          </section>
        )}
      </div>
    </details>
  );
}
