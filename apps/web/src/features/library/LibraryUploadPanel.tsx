export type LibraryUploadTab = "arxiv" | "file";

interface LibraryUploadPanelProps {
  uploadTab: LibraryUploadTab;
  uploadId: string;
  uploading: boolean;
  uploadError: string;
  selectedFile: File | null;
  onTabChange: (tab: LibraryUploadTab) => void;
  onUploadIdChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onUpload: () => void;
  onFileUpload: () => void;
}

export function LibraryUploadPanel({
  uploadTab,
  uploadId,
  uploading,
  uploadError,
  selectedFile,
  onTabChange,
  onUploadIdChange,
  onFileChange,
  onUpload,
  onFileUpload,
}: LibraryUploadPanelProps) {
  return (
    <div className="card-static p-5 mb-5 animate-fade-up">
      <div className="flex gap-4 mb-4">
        <button
          onClick={() => onTabChange("arxiv")}
          className={`text-[13px] font-medium pb-1 transition-colors ${uploadTab === "arxiv" ? "text-[var(--accent)] border-b-2 border-[var(--accent)]" : "text-[var(--text-muted)]"}`}
        >
          arXiv ID
        </button>
        <button
          onClick={() => onTabChange("file")}
          className={`text-[13px] font-medium pb-1 transition-colors ${uploadTab === "file" ? "text-[var(--accent)] border-b-2 border-[var(--accent)]" : "text-[var(--text-muted)]"}`}
        >
          Upload File
        </button>
      </div>

      {uploadTab === "arxiv" ? (
        <>
          <div className="flex gap-3">
            <input
              type="text"
              className="input-field text-[13px] flex-1"
              style={{ fontFamily: "var(--font-mono)" }}
              placeholder="e.g. 2505.24431"
              value={uploadId}
              onChange={(e) => onUploadIdChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") onUpload(); }}
            />
            <button onClick={onUpload} disabled={uploading || !uploadId.trim()} className="btn-primary text-[13px] px-5">
              {uploading ? <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />Adding</span> : "Add"}
            </button>
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-2">
            The paper will be downloaded from arXiv, parsed, tagged, and indexed.
          </p>
        </>
      ) : (
        <>
          <div className="flex gap-3 items-center">
            <label className="flex-1 cursor-pointer">
              <div className="input-field text-[13px] text-center py-6 border-dashed hover:border-[var(--accent)] transition-colors">
                {selectedFile ? (
                  <span className="text-[var(--text-primary)]">{selectedFile.name}</span>
                ) : (
                  <span className="text-[var(--text-muted)]">
                    Click to select .tar.gz, .gz, or .zip file
                  </span>
                )}
              </div>
              <input
                type="file"
                className="hidden"
                accept=".tar.gz,.tgz,.gz,.zip,.tex"
                onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
              />
            </label>
            <button
              onClick={onFileUpload}
              disabled={uploading || !selectedFile}
              className="btn-primary text-[13px] px-5"
            >
              {uploading ? <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-white/40 border-t-white animate-spin" />Uploading</span> : "Upload"}
            </button>
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-2">
            Upload a LaTeX source archive (same format as arXiv downloads). The paper will be parsed and indexed.
          </p>
        </>
      )}

      {uploading && (
        <div className="flex items-center gap-2 mt-3 text-[11px] text-[var(--text-muted)]">
          <div className="h-3 w-3 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin shrink-0" />
          <span className="animate-pulse">Downloading → Parsing → Analyzing → Tagging → Embedding → Storing...</span>
        </div>
      )}
      {uploadError && (
        <p className="text-[12px] text-[var(--accent-red)] mt-2">{uploadError}</p>
      )}
    </div>
  );
}
