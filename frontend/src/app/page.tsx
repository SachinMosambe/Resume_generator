"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import toast, { Toaster } from "react-hot-toast";
import {
  FileText,
  Loader2,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";

type TemplateMode = "aptino_default" | "client_format" | "saved_format";

type SavedFormat = {
  id: string;
  name: string;
  source_type?: string;
  preview_text?: string;
  section_count?: number;
  logo_count?: number;
  extraction_confidence?: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ACCEPT_DOCS =
  ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

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
  const [savedFormats, setSavedFormats] = useState<SavedFormat[]>([]);
  const [selectedFormatId, setSelectedFormatId] = useState("");
  const [saveFormatAs, setSaveFormatAs] = useState(false);
  const [formatName, setFormatName] = useState("");
  const [isLoadingFormats, setIsLoadingFormats] = useState(false);

  const loadFormats = useCallback(async () => {
    setIsLoadingFormats(true);
    try {
      const response = await fetch(`${API_URL}/api/formats`);
      if (!response.ok) throw new Error("Failed to load saved formats");
      const data = await response.json();
      setSavedFormats(Array.isArray(data.formats) ? data.formats : []);
    } catch {
      setSavedFormats([]);
    } finally {
      setIsLoadingFormats(false);
    }
  }, []);

  useEffect(() => {
    void loadFormats();
  }, [loadFormats]);

  const canSubmit =
    Boolean(resumeFile) &&
    !isGenerating &&
    (templateMode === "aptino_default" ||
      (templateMode === "client_format" && Boolean(templateFile)) ||
      (templateMode === "saved_format" && Boolean(selectedFormatId)));

  const handleDeleteFormat = async (id: string) => {
    try {
      const response = await fetch(`${API_URL}/api/formats/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Delete failed");
      toast.success("Format deleted");
      if (selectedFormatId === id) setSelectedFormatId("");
      await loadFormats();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to delete format");
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!resumeFile) {
      toast.error("Upload a candidate resume");
      return;
    }
    if (templateMode === "client_format" && !templateFile) {
      toast.error("Upload a client format template (PDF, DOC, or DOCX)");
      return;
    }
    if (templateMode === "saved_format" && !selectedFormatId) {
      toast.error("Select a saved company format");
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
        if (saveFormatAs) {
          form.append("save_format", "true");
          form.append("format_name", formatName.trim() || templateFile.name);
        }
      }
      if (templateMode === "saved_format" && selectedFormatId) {
        form.append("format_id", selectedFormatId);
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

      const savedId = response.headers.get("X-Saved-Format-Id");
      if (savedId) {
        toast.success("Resume downloaded · format saved", { id: toastId });
        await loadFormats();
        setSaveFormatAs(false);
      } else {
        toast.success("Resume downloaded", { id: toastId });
      }
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
            Upload a candidate resume, pick Aptino default, upload a company format (PDF/DOC/DOCX),
            or reuse a saved format — then download a polished DOCX.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="space-y-6 rounded-2xl border border-gray-200/70 bg-white p-5 shadow-sm md:p-7"
        >
          <FilePicker
            label="Candidate resume"
            hint="PDF, DOC, or DOCX up to 10 MB"
            file={resumeFile}
            accept={ACCEPT_DOCS}
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
            <div className="grid gap-3 sm:grid-cols-3">
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
                <p className="mt-0.5 text-xs text-gray-500">Built-in logo and footer</p>
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
                <p className="text-sm font-semibold text-gray-900">Upload format</p>
                <p className="mt-0.5 text-xs text-gray-500">PDF, DOC, or DOCX</p>
              </button>
              <button
                type="button"
                onClick={() => {
                  setTemplateMode("saved_format");
                  void loadFormats();
                }}
                className={`rounded-xl border px-4 py-3 text-left transition ${
                  templateMode === "saved_format"
                    ? "border-[#FF5050] bg-[#FF5050]/5 ring-1 ring-[#FF5050]/30"
                    : "border-gray-200 bg-gray-50/40 hover:border-gray-300"
                }`}
              >
                <p className="text-sm font-semibold text-gray-900">Saved format</p>
                <p className="mt-0.5 text-xs text-gray-500">Reuse a stored profile</p>
              </button>
            </div>
          </div>

          {templateMode === "client_format" && (
            <div className="space-y-4">
              <FilePicker
                label="Company format template"
                hint="PDF, DOC, or DOCX — DOCX recommended for closest match"
                file={templateFile}
                accept={ACCEPT_DOCS}
                onChange={setTemplateFile}
                onClear={() => setTemplateFile(null)}
              />
              <label className="flex items-start gap-3 rounded-xl border border-gray-200 bg-gray-50/50 px-4 py-3">
                <input
                  type="checkbox"
                  checked={saveFormatAs}
                  onChange={(e) => setSaveFormatAs(e.target.checked)}
                  className="mt-1"
                />
                <span className="space-y-1">
                  <span className="block text-sm font-semibold text-gray-900">
                    Save this format for reuse
                  </span>
                  <span className="block text-xs text-gray-500">
                    Stores fonts, section order, logos, and the original file.
                  </span>
                </span>
              </label>
              {saveFormatAs && (
                <input
                  value={formatName}
                  onChange={(e) => setFormatName(e.target.value)}
                  placeholder="Format name (e.g. Acme Corp 2026)"
                  className="h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-900 outline-none transition focus:border-[#FF5050] focus:ring-1 focus:ring-[#FF5050]/30"
                />
              )}
            </div>
          )}

          {templateMode === "saved_format" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
                  Saved company formats
                </label>
                <button
                  type="button"
                  onClick={() => void loadFormats()}
                  className="text-xs font-semibold text-[#FF5050] hover:underline"
                >
                  {isLoadingFormats ? "Loading…" : "Refresh"}
                </button>
              </div>
              {savedFormats.length === 0 ? (
                <p className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-4 py-6 text-center text-sm text-gray-500">
                  No saved formats yet. Upload a PDF/DOC/DOCX and check “Save this format”.
                </p>
              ) : (
                <ul className="space-y-2">
                  {savedFormats.map((fmt) => (
                    <li
                      key={fmt.id}
                      className={`flex items-start justify-between gap-3 rounded-xl border px-4 py-3 transition ${
                        selectedFormatId === fmt.id
                          ? "border-[#FF5050] bg-[#FF5050]/5"
                          : "border-gray-200 bg-white hover:border-gray-300"
                      }`}
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => setSelectedFormatId(fmt.id)}
                      >
                        <p className="truncate text-sm font-semibold text-gray-900">{fmt.name}</p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {(fmt.source_type || "file").toUpperCase()}
                          {typeof fmt.section_count === "number" ? ` · ${fmt.section_count} sections` : ""}
                          {typeof fmt.logo_count === "number" ? ` · ${fmt.logo_count} logos` : ""}
                          {fmt.extraction_confidence ? ` · ${fmt.extraction_confidence}` : ""}
                        </p>
                        {fmt.preview_text ? (
                          <p className="mt-1 line-clamp-2 text-xs text-gray-400">{fmt.preview_text}</p>
                        ) : null}
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDeleteFormat(fmt.id)}
                        className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-red-500"
                        aria-label={`Delete ${fmt.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
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
