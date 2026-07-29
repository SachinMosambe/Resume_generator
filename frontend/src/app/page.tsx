"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import toast, { Toaster } from "react-hot-toast";
import {
  FileText,
  Loader2,
  Sparkles,
  Upload,
  X,
} from "lucide-react";

type TemplateMode = "aptino_default" | "client_format";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function FilePicker({
  label,
  hint,
  file,
  accept,
  onChange,
  onClear,
}: {
  label: string;
  hint: string;
  file: File | null;
  accept: string;
  onChange: (file: File | null) => void;
  onClear: () => void;
}) {
  const inputId = useMemo(() => `file-${label.replace(/\s+/g, "-").toLowerCase()}`, [label]);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.files?.[0] || null);
  };

  return (
    <div className="space-y-2">
      <label className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
        {label}
      </label>
      {!file ? (
        <label
          htmlFor={inputId}
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-gray-300 bg-gray-50/60 px-4 py-8 text-center transition hover:border-[#FF5050]/60 hover:bg-[#FF5050]/5"
        >
          <Upload className="h-6 w-6 text-gray-400" />
          <span className="text-sm font-semibold text-gray-700">Drop or click to upload</span>
          <span className="text-xs text-gray-400">{hint}</span>
          <input
            id={inputId}
            type="file"
            accept={accept}
            className="hidden"
            onChange={handleChange}
          />
        </label>
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <FileText className="h-5 w-5 shrink-0 text-[#FF5050]" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-gray-900">{file.name}</p>
              <p className="text-xs text-gray-400">{(file.size / 1024).toFixed(1)} KB</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClear}
            className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
            aria-label="Remove file"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}

export default function HomePage() {
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [templateMode, setTemplateMode] = useState<TemplateMode>("aptino_default");
  const [clientName, setClientName] = useState("");
  const [jobRole, setJobRole] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);

  const canSubmit =
    Boolean(resumeFile) &&
    !isGenerating &&
    (templateMode === "aptino_default" || Boolean(templateFile));

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!resumeFile) {
      toast.error("Upload a candidate resume");
      return;
    }
    if (templateMode === "client_format" && !templateFile) {
      toast.error("Upload a client format template");
      return;
    }

    setIsGenerating(true);
    const toastId = toast.loading("Generating resume… this can take a minute");

    try {
      const form = new FormData();
      form.append("resume", resumeFile);
      form.append("template_source", templateMode);
      form.append("client_name", clientName.trim());
      form.append("job_role", jobRole.trim());
      if (templateMode === "client_format" && templateFile) {
        form.append("template", templateFile);
      }

      const response = await fetch(`${API_URL}/api/generate`, {
        method: "POST",
        body: form,
      });

      if (!response.ok) {
        let detail = "Failed to generate resume";
        try {
          const data = await response.json();
          detail = data.detail || detail;
        } catch {
          /* ignore */
        }
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match?.[1] || "generated_resume.docx";

      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);

      toast.success("Resume downloaded", { id: toastId });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to generate resume";
      toast.error(message, { id: toastId });
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50/80">
      <Toaster position="top-right" />
      <div className="mx-auto max-w-3xl px-4 py-10 md:px-6 md:py-14">
        <header className="mb-8 space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-semibold text-gray-500">
            <span className="h-2 w-2 rounded-full bg-[#FF5050]" />
            Resume Generator
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 md:text-4xl">
            Generate a client-ready resume
          </h1>
          <p className="max-w-2xl text-sm text-gray-500 md:text-base">
            Upload a candidate resume, pick the Aptino default template or a client format,
            and download a polished DOCX.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="space-y-6 rounded-2xl border border-gray-200/70 bg-white p-5 shadow-sm md:p-7"
        >
          <FilePicker
            label="Candidate resume"
            hint="PDF or DOCX up to 10 MB"
            file={resumeFile}
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={setResumeFile}
            onClear={() => setResumeFile(null)}
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
                Client name (optional)
              </label>
              <input
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                placeholder="e.g. Acme Corp"
                className="h-10 w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 text-sm text-gray-900 outline-none transition focus:border-[#FF5050] focus:ring-1 focus:ring-[#FF5050]/30"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
                Target role (optional)
              </label>
              <input
                value={jobRole}
                onChange={(e) => setJobRole(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                className="h-10 w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 text-sm text-gray-900 outline-none transition focus:border-[#FF5050] focus:ring-1 focus:ring-[#FF5050]/30"
              />
            </div>
          </div>

          <div className="space-y-3">
            <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
              Template
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setTemplateMode("aptino_default")}
                className={`rounded-xl border px-4 py-3 text-left transition ${
                  templateMode === "aptino_default"
                    ? "border-[#FF5050] bg-[#FF5050]/5 ring-1 ring-[#FF5050]/30"
                    : "border-gray-200 bg-gray-50/40 hover:border-gray-300"
                }`}
              >
                <p className="text-sm font-semibold text-gray-900">Aptino default</p>
                <p className="mt-0.5 text-xs text-gray-500">Built-in logo and company footer</p>
              </button>
              <button
                type="button"
                onClick={() => setTemplateMode("client_format")}
                className={`rounded-xl border px-4 py-3 text-left transition ${
                  templateMode === "client_format"
                    ? "border-[#FF5050] bg-[#FF5050]/5 ring-1 ring-[#FF5050]/30"
                    : "border-gray-200 bg-gray-50/40 hover:border-gray-300"
                }`}
              >
                <p className="text-sm font-semibold text-gray-900">Upload client format</p>
                <p className="mt-0.5 text-xs text-gray-500">Match an existing PDF/DOCX layout</p>
              </button>
            </div>
          </div>

          {templateMode === "client_format" && (
            <FilePicker
              label="Client format template"
              hint="PDF or DOCX sample to extract style and logos"
              file={templateFile}
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={setTemplateFile}
              onClear={() => setTemplateFile(null)}
            />
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#FF5050] px-4 text-sm font-semibold text-white transition hover:bg-[#e84545] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isGenerating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Generate &amp; download DOCX
              </>
            )}
          </button>
        </form>
      </div>
    </main>
  );
}
