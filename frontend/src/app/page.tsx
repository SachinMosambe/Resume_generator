"use client";

import { ChangeEvent, DragEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import toast, { Toaster } from "react-hot-toast";
import {
  FileText,
  FolderOpen,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type TemplateMode = "aptino_default" | "client_format" | "saved_format";

type ReviewStatus = "passed" | "needs_review" | "failed";

type Review = {
  status: ReviewStatus;
  warnings: string[];
};

const REVIEW_STYLES: Record<ReviewStatus, { box: string; title: string; body: string }> = {
  passed: {
    box: "border-emerald-200 bg-emerald-50",
    title: "Automated check passed",
    body: "Every employer, title, date, bullet, and section found in the source also appears in the document. This is a text-presence check, not a full proofread — skim before sending.",
  },
  needs_review: {
    box: "border-amber-200 bg-amber-50",
    title: "Review before sending",
    body: "The automated check found items that need a recruiter's eye:",
  },
  failed: {
    box: "border-red-200 bg-red-50",
    title: "Large parts of the source are missing",
    body: "Do not send this document as-is. Compare it with the original resume:",
  },
};

function parseReview(response: Response): Review | null {
  const status = response.headers.get("X-Review-Status") as ReviewStatus | null;
  if (!status || !(status in REVIEW_STYLES)) return null;
  let warnings: string[] = [];
  try {
    const parsed = JSON.parse(decodeURIComponent(response.headers.get("X-Review-Warnings") || "[]"));
    if (Array.isArray(parsed)) warnings = parsed.map(String);
  } catch {
    /* ignore malformed header */
  }
  return { status, warnings };
}

function ReviewPanel({ review }: { review: Review }) {
  const style = REVIEW_STYLES[review.status];
  return (
    <section role="status" className={`mt-6 rounded-2xl border p-5 ${style.box}`}>
      <p className="text-sm font-semibold text-gray-900">{style.title}</p>
      <p className="mt-1 text-sm text-gray-700">{style.body}</p>
      {review.warnings.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-700">
          {review.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

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

const fieldClass =
  "h-12 rounded-xl border-neutral-300 bg-white px-4 text-neutral-900 shadow-none focus-visible:ring-[#FF5050]/30";

function FilePicker({
  label,
  hint,
  file,
  accept,
  onChange,
  onClear,
  fill = false,
}: {
  label: string;
  hint: string;
  file: File | null;
  accept: string;
  onChange: (file: File | null) => void;
  onClear: () => void;
  fill?: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);
  const inputId = useMemo(() => `file-${label.replace(/\s+/g, "-").toLowerCase()}`, [label]);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.files?.[0] || null);
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragOver(false);
    onChange(event.dataTransfer.files?.[0] || null);
  };

  if (file) {
    return (
      <div className={fill ? "flex h-full flex-col gap-2" : "space-y-2"}>
        <Label className="text-sm font-medium text-neutral-900">{label}</Label>
        <div
          className={`flex items-center gap-3 rounded-xl border border-neutral-200 bg-neutral-50 p-4 ${
            fill ? "min-h-72 flex-1" : ""
          }`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#FF5050]/10 text-[#FF5050]">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-neutral-900">{file.name}</p>
            <p className="text-xs text-neutral-500">{(file.size / 1024).toFixed(1)} KB</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onClear}
            className="h-8 w-8 text-neutral-400 hover:text-neutral-700"
            aria-label="Remove file"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={fill ? "flex h-full flex-col gap-2" : "space-y-2"}>
      <Label className="text-sm font-medium text-neutral-900">{label}</Label>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`cursor-pointer rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${
          fill ? "flex min-h-72 flex-1 flex-col items-center justify-center" : "block"
        } ${
          dragOver
            ? "border-[#FF5050] bg-[#FF5050]/5"
            : "border-neutral-300 bg-neutral-50 hover:border-[#FF5050]/50 hover:bg-[#FF5050]/5"
        }`}
      >
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-neutral-200">
          <Upload className="h-6 w-6 text-neutral-600" />
        </div>
        <p className="mb-1 text-base font-medium text-neutral-900">Drop your file here</p>
        <p className="mb-4 text-sm text-neutral-500">{hint}</p>
        <span className="inline-flex h-10 items-center rounded-xl border border-neutral-300 bg-white px-4 text-sm font-medium text-neutral-800">
          Browse files
        </span>
        <input id={inputId} type="file" accept={accept} className="hidden" onChange={handleChange} />
      </label>
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
  const [formatQuery, setFormatQuery] = useState("");
  const [review, setReview] = useState<Review | null>(null);

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

  const filteredFormats = savedFormats.filter((fmt) =>
    fmt.name.toLowerCase().includes(formatQuery.toLowerCase()),
  );

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
    setReview(null);
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

      const result = parseReview(response);
      setReview(result);
      const suffix = result && result.status !== "passed" ? " · review needed" : "";
      const savedId = response.headers.get("X-Saved-Format-Id");
      if (savedId) {
        toast.success(`Resume downloaded · format saved${suffix}`, { id: toastId });
        await loadFormats();
        setSaveFormatAs(false);
      } else {
        toast.success(`Resume downloaded${suffix}`, { id: toastId });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to generate resume";
      toast.error(message, { id: toastId });
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-8 sm:px-6 sm:py-12">
      <Toaster position="top-right" />
      <Card className="mx-auto w-full max-w-5xl rounded-3xl border-neutral-200 bg-white shadow-2xl">
        <CardContent className="p-4 sm:p-6 lg:p-8">
          <div className="mb-6 flex items-start gap-3 sm:gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#FF5050] sm:h-12 sm:w-12">
              <FileText className="h-5 w-5 text-white sm:h-6 sm:w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="mb-2 text-base font-semibold text-neutral-900 sm:text-lg">
                Generate a client-ready resume
              </h1>
              <p className="max-w-xl text-sm font-normal leading-relaxed text-neutral-600">
                Drop a candidate resume, pick a company format, and download a polished DOCX you can
                review before sending.
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="lg:grid lg:grid-cols-2 lg:items-stretch lg:gap-8">
            <div className="mb-6 lg:mb-0 lg:h-full">
              <FilePicker
                label="Candidate resume"
                hint="PDF, DOC, or DOCX up to 10 MB"
                file={resumeFile}
                accept={ACCEPT_DOCS}
                onChange={setResumeFile}
                onClear={() => setResumeFile(null)}
                fill
              />
            </div>

            <div className="flex flex-col gap-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-6">
              <div>
                <Label htmlFor="client-name" className="mb-3 block text-sm font-medium text-neutral-900">
                  Client name
                </Label>
                <Input
                  id="client-name"
                  value={clientName}
                  onChange={(e) => setClientName(e.target.value)}
                  placeholder="e.g. Acme Corp"
                  className={fieldClass}
                />
              </div>
              <div>
                <Label htmlFor="job-role" className="mb-3 block text-sm font-medium text-neutral-900">
                  Target role
                </Label>
                <Input
                  id="job-role"
                  value={jobRole}
                  onChange={(e) => setJobRole(e.target.value)}
                  placeholder="e.g. Senior Software Engineer"
                  className={fieldClass}
                />
              </div>
            </div>

            <div>
              <Label className="mb-3 block text-sm font-medium text-neutral-900">Template</Label>
              <Tabs
                value={templateMode}
                onValueChange={(value) => {
                  const mode = value as TemplateMode;
                  setTemplateMode(mode);
                  if (mode === "saved_format") void loadFormats();
                }}
              >
                <TabsList className="grid h-auto w-full grid-cols-3 rounded-xl bg-neutral-100 p-1">
                  <TabsTrigger
                    value="aptino_default"
                    className="rounded-lg text-xs font-medium data-[state=active]:bg-white data-[state=active]:text-[#FF5050] data-[state=active]:shadow-sm sm:text-sm"
                  >
                    <Sparkles className="mr-1 h-4 w-4 sm:mr-2" />
                    <span className="hidden sm:inline">Aptino default</span>
                    <span className="sm:hidden">Default</span>
                  </TabsTrigger>
                  <TabsTrigger
                    value="client_format"
                    className="rounded-lg text-xs font-medium data-[state=active]:bg-white data-[state=active]:text-[#FF5050] data-[state=active]:shadow-sm sm:text-sm"
                  >
                    <Upload className="mr-1 h-4 w-4 sm:mr-2" />
                    <span className="hidden sm:inline">Upload format</span>
                    <span className="sm:hidden">Upload</span>
                  </TabsTrigger>
                  <TabsTrigger
                    value="saved_format"
                    className="rounded-lg text-xs font-medium data-[state=active]:bg-white data-[state=active]:text-[#FF5050] data-[state=active]:shadow-sm sm:text-sm"
                  >
                    <FolderOpen className="mr-1 h-4 w-4 sm:mr-2" />
                    <span className="hidden sm:inline">Saved format</span>
                    <span className="sm:hidden">Saved</span>
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="aptino_default" className="mt-6">
                  <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                    <p className="text-sm font-medium text-neutral-900">Built-in Aptino layout</p>
                    <p className="mt-1 text-sm leading-relaxed text-neutral-500">
                      Uses the standard logo, footer, and section order. No company template needed.
                    </p>
                  </div>
                </TabsContent>

                <TabsContent value="client_format" className="mt-6 space-y-4">
                  <FilePicker
                    label="Company format template"
                    hint="PDF, DOC, or DOCX — DOCX matches closest"
                    file={templateFile}
                    accept={ACCEPT_DOCS}
                    onChange={setTemplateFile}
                    onClear={() => setTemplateFile(null)}
                  />
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-3">
                    <input
                      type="checkbox"
                      checked={saveFormatAs}
                      onChange={(e) => setSaveFormatAs(e.target.checked)}
                      className="mt-1 accent-[#FF5050]"
                    />
                    <span className="space-y-1">
                      <span className="block text-sm font-medium text-neutral-900">
                        Save this format for reuse
                      </span>
                      <span className="block text-xs text-neutral-500">
                        Stores alignment, fonts, section order, logos, and the original file.
                      </span>
                    </span>
                  </label>
                  {saveFormatAs && (
                    <Input
                      value={formatName}
                      onChange={(e) => setFormatName(e.target.value)}
                      placeholder="Format name (e.g. Acme Corp 2026)"
                      className={fieldClass}
                      aria-label="Format name"
                    />
                  )}
                </TabsContent>

                <TabsContent value="saved_format" className="mt-6 space-y-4">
                  <div className="flex items-center gap-2">
                    <div className="relative min-w-0 flex-1">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
                      <Input
                        placeholder="Search formats..."
                        value={formatQuery}
                        onChange={(e) => setFormatQuery(e.target.value)}
                        className={`${fieldClass} pl-10`}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="h-12 w-12 shrink-0 rounded-xl border-neutral-300"
                      onClick={() => void loadFormats()}
                      aria-label="Refresh saved formats"
                    >
                      <RefreshCw className={`h-4 w-4 ${isLoadingFormats ? "animate-spin" : ""}`} />
                    </Button>
                  </div>

                  {savedFormats.length === 0 ? (
                    <p className="rounded-xl border border-dashed border-neutral-300 bg-neutral-50 px-4 py-8 text-center text-sm text-neutral-500">
                      No saved formats yet. Upload a template and check “Save this format”.
                    </p>
                  ) : filteredFormats.length === 0 ? (
                    <p className="rounded-xl border border-dashed border-neutral-300 bg-neutral-50 px-4 py-8 text-center text-sm text-neutral-500">
                      No formats match “{formatQuery}”.
                    </p>
                  ) : (
                    <ul className="max-h-64 space-y-2 overflow-y-auto">
                      {filteredFormats.map((fmt) => {
                        const selected = selectedFormatId === fmt.id;
                        return (
                          <li
                            key={fmt.id}
                            className={`rounded-xl border p-4 transition ${
                              selected
                                ? "border-[#FF5050] bg-[#FF5050]/5"
                                : "border-neutral-200 bg-white hover:border-neutral-300"
                            }`}
                          >
                            <div className="flex items-center gap-3">
                              <button
                                type="button"
                                className="flex min-w-0 flex-1 items-center gap-3 text-left"
                                onClick={() => setSelectedFormatId(fmt.id)}
                              >
                                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-neutral-200 text-neutral-700">
                                  <FileText className="h-4 w-4" />
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="mb-1 flex items-center gap-2">
                                    <p className="truncate text-sm font-medium text-neutral-900">{fmt.name}</p>
                                    {fmt.extraction_confidence ? (
                                      <Badge className="border-transparent bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-700 hover:bg-neutral-100">
                                        {fmt.extraction_confidence}
                                      </Badge>
                                    ) : null}
                                  </div>
                                  <p className="text-xs text-neutral-500">
                                    {(fmt.source_type || "file").toUpperCase()}
                                    {typeof fmt.section_count === "number"
                                      ? ` · ${fmt.section_count} sections`
                                      : ""}
                                    {typeof fmt.logo_count === "number" ? ` · ${fmt.logo_count} logos` : ""}
                                  </p>
                                  {fmt.preview_text ? (
                                    <p className="mt-1 line-clamp-2 text-xs text-neutral-400">{fmt.preview_text}</p>
                                  ) : null}
                                </div>
                              </button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-neutral-400 hover:text-red-500"
                                onClick={() => void handleDeleteFormat(fmt.id)}
                                aria-label={`Delete ${fmt.name}`}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </TabsContent>
              </Tabs>
            </div>

            </div>

            <div className="mt-6 flex flex-col gap-3 border-t border-neutral-200 pt-6 sm:flex-row sm:items-center sm:justify-between lg:col-span-2 lg:mt-0">
              <p className="text-xs text-neutral-500">Downloads a DOCX when generation finishes.</p>
              <Button
                type="submit"
                disabled={!canSubmit}
                className="h-12 rounded-xl bg-[#FF5050] px-8 font-medium text-white hover:bg-[#e84545]"
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Generating…
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Generate
                  </>
                )}
              </Button>
            </div>
          </form>
          {review && <ReviewPanel review={review} />}
        </CardContent>
      </Card>
    </main>
  );
}
