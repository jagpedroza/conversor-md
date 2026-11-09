import base64
import io
import queue
import re
import threading
import zipfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from markitdown import MarkItDown

# File types converted to Markdown
CONVERT_EXTENSIONS = {".html", ".htm", ".pdf", ".docx", ".pptx", ".xlsx"}
# Files whose names start with these prefixes are skipped (course indexes, no content)
SKIP_PREFIXES = ("table of contents",)

ACTION_LABELS = {"convert": "Convert to MD", "copy": "Copy as is", "skip": "Skip"}
LOG_TAGS = {"convert": "CONVERTED", "copy": "COPIED", "skip": "SKIPPED"}

md = MarkItDown()

# Embedded base64 image data URI: (format, base64 data)
IMAGE_DATA = re.compile(r"data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=]+)")
# Complete <img> tag that holds an embedded image
IMAGE_TAG = re.compile(r"<img[^>]*src=\"data:image/[^\"]*\"[^>]*>")
# <pre> blocks that are NOT R code (R code blocks carry class="r"), i.e. chunk outputs
OUTPUT_BLOCK = re.compile(r"<pre(?![^>]*class=\"[^\"]*\br\b)[^>]*>.*?</pre>", re.S)
# Very long base64 strings (where the embedded .Rmd source is stored)
LONG_BASE64 = re.compile(r"[A-Za-z0-9+/=]{2000,}")
# Notebook interface controls
NOTEBOOK_UI = re.compile(
    r"^\s*\*?\s*(Show|Hide) All Code\s*$|^\s*\*?\s*Download Rmd\s*$", re.M
)


# ---------- Classification and source reading ----------
def suggested_action(name: str) -> str:
    path = Path(name)
    if path.name.lower().startswith(SKIP_PREFIXES):
        return "skip"
    if path.suffix.lower() in CONVERT_EXTENSIONS:
        return "convert"
    return "copy"


def list_zip_entries(path: Path) -> list[str]:
    """Return the internal file paths of a ZIP, ignoring junk and unsafe paths."""
    names = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            p = Path(info.filename)
            if p.is_absolute() or ".." in p.parts:
                continue
            if any(part.startswith(("__MACOSX", ".")) for part in p.parts):
                continue
            names.append(info.filename)
    return names


def read_source(row: dict) -> bytes:
    if row["from_zip"]:
        with zipfile.ZipFile(row["source"]) as z:
            return z.read(row["internal"])
    return Path(row["source"]).read_bytes()


def unique_path(p: Path) -> Path:
    """Avoid overwriting: if 'x.md' exists, return 'x_1.md', 'x_2.md', ..."""
    if not p.exists():
        return p
    i = 1
    while True:
        candidate = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


# ---------- Text cleanup ----------
def fix_latex(text: str) -> str:
    """Inside \\( \\) and \\[ \\], turn '\\_' into '_' so subscripts render."""
    def clean(m):
        return m.group(0).replace(r"\_", "_")
    text = re.sub(r"\\\((.*?)\\\)", clean, text, flags=re.S)
    text = re.sub(r"\\\[(.*?)\\\]", clean, text, flags=re.S)
    return text


def clean_notebook_ui(text: str) -> str:
    text = NOTEBOOK_UI.sub("", text)
    if text.startswith("Code\n"):
        text = text[len("Code\n"):]
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.lstrip()


# ---------- Notebook conversion ----------
def take_embedded_rmd(html: str):
    """Remove the embedded .Rmd source from the HTML and return (html, rmd_text or None)."""
    rmd = None

    def take(m):
        nonlocal rmd
        chunk = m.group(0)
        try:
            text = base64.b64decode(chunk + "=" * (-len(chunk) % 4)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return chunk
        if text.lstrip().startswith("---") and ("output:" in text or "title:" in text):
            if rmd is None:
                rmd = text
            return ""
        return chunk

    return LONG_BASE64.sub(take, html), rmd


def rmd_to_markdown(rmd: str) -> str:
    """Turn R Markdown source into plain Markdown: keep prose and code, no outputs."""
    text = rmd.replace("\r\n", "\n")
    title = ""
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if front:
        title_match = re.search(r'^title:\s*"?(.*?)"?\s*$', front.group(1), re.M)
        if title_match:
            title = f"# {title_match.group(1)}\n\n"
        text = text[front.end():]
    # Chunk headers ```{r setup, include=FALSE} -> ```r
    text = re.sub(r"^```\{(\w+)[^}]*\}\s*$", r"```\1", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title + text.strip() + "\n"


def html_to_markdown(html: str, stem: str, include_figures: bool, include_outputs: bool):
    """
    Convert notebook HTML to Markdown.
    Returns (markdown_text, [(image_name, bytes)], figure_folder_name).
    """
    images = []
    figure_folder = f"{stem}_images"

    if include_figures:
        def save_figure(m):
            ext = m.group(1).replace("jpeg", "jpg")
            name = f"img_{len(images) + 1:03d}.{ext}"
            images.append((name, base64.b64decode(m.group(2))))
            return f"{figure_folder}/{name}"
        html = IMAGE_DATA.sub(save_figure, html)
    else:
        html = IMAGE_TAG.sub("", html)

    # Only strip outputs from R notebooks (identified by R code blocks)
    if not include_outputs and 'class="r"' in html:
        html = OUTPUT_BLOCK.sub("", html)

    text = md.convert_stream(io.BytesIO(html.encode("utf-8")), file_extension=".html").text_content
    return clean_notebook_ui(text), images, figure_folder


def convert_html(data: bytes, dest_md: Path, include_figures: bool, include_outputs: bool) -> str:
    """Convert an HTML file and write the .md. Returns a short note for the log."""
    html = data.decode("utf-8", errors="replace")
    html, rmd = take_embedded_rmd(html)

    note = ""
    if rmd is not None:
        text = rmd_to_markdown(rmd)
        images, folder = [], None
        note = " (from embedded .Rmd)"
    else:
        text, images, folder = html_to_markdown(html, dest_md.stem, include_figures, include_outputs)

    dest_md.parent.mkdir(parents=True, exist_ok=True)
    dest_md.write_text(fix_latex(text), encoding="utf-8")

    if images:
        figure_dir = dest_md.parent / folder
        figure_dir.mkdir(parents=True, exist_ok=True)
        for name, content in images:
            (figure_dir / name).write_bytes(content)
        note += f" + {len(images)} figure(s)"
    return note


def convert_document(data: bytes, ext: str) -> str:
    return md.convert_stream(io.BytesIO(data), file_extension=ext).text_content


# ---------- GUI ----------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Markdown Converter for LLM Tutors")
        root.geometry("900x700")

        self.rows: dict[str, dict] = {}   # item id -> row data
        self.out_dir = tk.StringVar(value=str(Path.home() / "markdown_output"))
        self.include_figures = tk.BooleanVar(value=False)
        self.include_outputs = tk.BooleanVar(value=False)
        self.queue = queue.Queue()

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        # Selection buttons
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Add files", command=self.add_files).pack(side="left")
        ttk.Button(buttons, text="Add folder", command=self.add_folder).pack(side="left", padx=5)
        ttk.Button(buttons, text="Remove selected", command=self.remove_selected).pack(side="left")
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left", padx=5)

        # Action for the selected items
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Label(actions, text="Set action for selection:").pack(side="left")
        for key in ("convert", "copy", "skip"):
            ttk.Button(actions, text=ACTION_LABELS[key],
                       command=lambda k=key: self.set_action(k)).pack(side="left", padx=5)

        ttk.Label(
            frame,
            text="Convert: HTML, PDF, DOCX, PPTX, XLSX  ·  Skip: Table of Contents  ·  Copy: everything else (Rmd, csv, ...)",
            foreground="#555555",
        ).pack(fill="x", pady=(4, 0))

        # Options
        options = ttk.Frame(frame)
        options.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(options, text="Include figures (images)",
                        variable=self.include_figures).pack(side="left")
        ttk.Checkbutton(options, text="Include code outputs",
                        variable=self.include_outputs).pack(side="left", padx=15)

        # File tree
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(tree_frame, columns=("action",), selectmode="extended")
        self.tree.heading("#0", text="File")
        self.tree.heading("action", text="Action")
        self.tree.column("action", width=150, anchor="center", stretch=False)
        self.tree.tag_configure("convert", foreground="#0a7d2c")
        self.tree.tag_configure("copy", foreground="#1f5fbf")
        self.tree.tag_configure("skip", foreground="#888888")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Output folder
        output = ttk.Frame(frame)
        output.pack(fill="x")
        ttk.Label(output, text="Output folder:").pack(side="left")
        ttk.Entry(output, textvariable=self.out_dir).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(output, text="Browse...", command=self.choose_output).pack(side="left")

        self.btn_process = ttk.Button(frame, text="Process", command=self.start)
        self.btn_process.pack(pady=8)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x")

        self.log = scrolledtext.ScrolledText(frame, height=9, state="disabled")
        self.log.pack(fill="both", expand=True, pady=(8, 0))

        self.root.after(100, self.check_queue)

    # ---------- Selection ----------
    def add_files(self):
        for path in filedialog.askopenfilenames():
            self._add(Path(path))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        base = Path(folder)
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            parts = p.relative_to(base).parts
            if any(part.startswith((".", "__MACOSX")) for part in parts):
                continue
            self._add(p)

    def _add(self, path: Path):
        item_id = str(path)
        if self.tree.exists(item_id):
            return

        if path.suffix.lower() == ".zip":
            try:
                names = list_zip_entries(path)
            except zipfile.BadZipFile:
                messagebox.showerror("Corrupt ZIP", f"Could not open:\n{path}")
                return
            self.tree.insert("", "end", iid=item_id, text=f"[ZIP] {path.name}", open=True)
            for name in names:
                child_id = f"{item_id}|{name}"
                row = {
                    "source": item_id, "from_zip": True, "internal": name,
                    "folder": path.stem, "display": f"{path.name} > {name}",
                    "action": suggested_action(name),
                }
                self.rows[child_id] = row
                self.tree.insert(item_id, "end", iid=child_id, text=name,
                                 values=(ACTION_LABELS[row["action"]],), tags=(row["action"],))
        else:
            row = {
                "source": item_id, "from_zip": False, "internal": path.name,
                "folder": "", "display": path.name,
                "action": suggested_action(path.name),
            }
            self.rows[item_id] = row
            self.tree.insert("", "end", iid=item_id, text=path.name,
                             values=(ACTION_LABELS[row["action"]],), tags=(row["action"],))

    def _refresh(self, item_id: str):
        row = self.rows[item_id]
        self.tree.item(item_id, values=(ACTION_LABELS[row["action"]],), tags=(row["action"],))

    def set_action(self, action: str):
        for item_id in self.tree.selection():
            children = self.tree.get_children(item_id)
            for target in (children or (item_id,)):
                if target in self.rows:
                    self.rows[target]["action"] = action
                    self._refresh(target)

    def remove_selected(self):
        for item_id in self.tree.selection():
            if not self.tree.exists(item_id):
                continue
            for child in self.tree.get_children(item_id):
                self.rows.pop(child, None)
            self.rows.pop(item_id, None)
            self.tree.delete(item_id)

    def clear(self):
        for item_id in self.tree.get_children(""):
            self.tree.delete(item_id)
        self.rows.clear()

    def choose_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.out_dir.set(folder)

    # ---------- Processing ----------
    def _plan(self) -> list[dict]:
        plan = []
        for top in self.tree.get_children(""):
            children = self.tree.get_children(top)
            if children:
                plan.extend(self.rows[c] for c in children if c in self.rows)
            elif top in self.rows:
                plan.append(self.rows[top])
        return [dict(row) for row in plan]

    def start(self):
        plan = self._plan()
        if not plan:
            messagebox.showwarning("No files", "Add at least one file.")
            return
        out = Path(self.out_dir.get()).expanduser()
        out.mkdir(parents=True, exist_ok=True)

        self.btn_process.config(state="disabled")
        self.progress["value"] = 0
        options = (self.include_figures.get(), self.include_outputs.get())
        threading.Thread(target=self._work, args=(plan, out, *options), daemon=True).start()

    def _work(self, plan, out: Path, include_figures: bool, include_outputs: bool):
        total = len(plan)
        summary = [
            f"Conversion run: {datetime.now():%Y-%m-%d %H:%M}",
            f"Include figures: {include_figures}",
            f"Include code outputs: {include_outputs}",
            "",
        ]

        for i, row in enumerate(plan, 1):
            action = row["action"]
            try:
                if action == "skip":
                    line = f"{LOG_TAGS[action]:<12}{row['display']}"
                else:
                    data = read_source(row)
                    rel = Path(row["internal"])
                    base = out / row["folder"]

                    if action == "copy":
                        dest = unique_path(base / rel)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(data)
                        note = ""
                    elif rel.suffix.lower() in {".html", ".htm"}:
                        dest = unique_path(base / rel.with_suffix(".md"))
                        note = convert_html(data, dest, include_figures, include_outputs)
                    else:
                        dest = unique_path(base / rel.with_suffix(".md"))
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        text = convert_document(data, rel.suffix.lower())
                        dest.write_text(fix_latex(text), encoding="utf-8")
                        note = ""

                    line = f"{LOG_TAGS[action]:<12}{row['display']} -> {dest.relative_to(out)}{note}"
            except Exception as e:
                line = f"ERROR       {row['display']}: {e}"

            self.queue.put(("log", line))
            summary.append(line)
            self.queue.put(("progress", i / total * 100))

        summary_path = out / f"summary_{datetime.now():%Y%m%d_%H%M%S}.txt"
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
        self.queue.put(("log", f"Summary saved to: {summary_path}"))
        self.queue.put(("done", None))

    # ---------- GUI communication ----------
    def check_queue(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "log":
                    self._write(value)
                elif kind == "progress":
                    self.progress["value"] = value
                elif kind == "done":
                    self.btn_process.config(state="normal")
                    self._write("— Finished —")
        except queue.Empty:
            pass
        self.root.after(100, self.check_queue)

    def _write(self, text: str):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()