"""Conversion logic. Everything runs in memory; nothing is written to disk here."""
import base64
import io
import re
import zipfile
from pathlib import Path

from markitdown import MarkItDown

CONVERT_EXTENSIONS = {".html", ".htm", ".pdf", ".docx", ".pptx", ".xlsx"}
SKIP_PREFIXES = ("table of contents",)
ACTIONS = ("convert", "copy", "skip")
MAX_BATCH_BYTES = 20 * 1024 * 1024

md = MarkItDown()

IMAGE_DATA = re.compile(r"data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=]+)")
IMAGE_TAG = re.compile(r"<img[^>]*src=\"data:image/[^\"]*\"[^>]*>")
# <pre> blocks without class="r" are chunk outputs, not R code
OUTPUT_BLOCK = re.compile(r"<pre(?![^>]*class=\"[^\"]*\br\b)[^>]*>.*?</pre>", re.S)
LONG_BASE64 = re.compile(r"[A-Za-z0-9+/=]{2000,}")
NOTEBOOK_UI = re.compile(
    r"^\s*\*?\s*(Show|Hide) All Code\s*$|^\s*\*?\s*Download Rmd\s*$", re.M
)


def suggested_action(name: str) -> str:
    path = Path(name)
    if path.name.lower().startswith(SKIP_PREFIXES):
        return "skip"
    if path.suffix.lower() in CONVERT_EXTENSIONS:
        return "convert"
    return "copy"


def list_zip_entries(data: bytes) -> list[str]:
    names = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
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


def take_embedded_rmd(html: str):
    """Remove the embedded .Rmd source from the HTML. Returns (html, rmd_text or None)."""
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
    """R Markdown source to plain Markdown: keeps prose and chunks intact, no outputs."""
    text = rmd.replace("\r\n", "\n")
    title = ""
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if front:
        title_match = re.search(r'^title:\s*"?(.*?)"?\s*$', front.group(1), re.M)
        if title_match:
            title = f"# {title_match.group(1)}\n\n"
        text = text[front.end():]
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title + text.strip() + "\n"

def fix_r_fences(text: str) -> str:
    """Markitdown writes R code blocks as ```r; RStudio needs ```{r}."""
    return re.sub(r"^```r[ \t]*$", "```{r}", text, flags=re.M)


def html_to_markdown(html: str, stem: str, include_figures: bool, include_outputs: bool):
    """Returns (markdown, [(figure_name, bytes)], figure_folder)."""
    figures = []
    folder = f"{stem}_images"

    if include_figures:
        def save_figure(m):
            ext = m.group(1).replace("jpeg", "jpg")
            name = f"img_{len(figures) + 1:03d}.{ext}"
            figures.append((name, base64.b64decode(m.group(2))))
            return f"{folder}/{name}"
        html = IMAGE_DATA.sub(save_figure, html)
    else:
        html = IMAGE_TAG.sub("", html)

    if not include_outputs and 'class="r"' in html:
        html = OUTPUT_BLOCK.sub("", html)

    text = md.convert_stream(io.BytesIO(html.encode("utf-8")), file_extension=".html").text_content
    return clean_notebook_ui(text), figures, folder


def convert_item(name: str, data: bytes, action: str,
                 include_figures: bool, include_outputs: bool):
    """
    Process one file. 'name' is its path inside the batch.
    Returns (list of (output_path, bytes), note).
    """
    path = Path(name)
    base = path.parent

    if action == "skip":
        return [], "skipped"
    if action == "copy":
        return [(name, data)], "copied"

    ext = path.suffix.lower()
    if ext in {".html", ".htm"}:
        html, rmd = take_embedded_rmd(data.decode("utf-8", errors="replace"))
        note = ""
        if rmd is not None:
            text, figures, folder = rmd_to_markdown(rmd), [], None
            note = "from embedded .Rmd"
        else:
            text, figures, folder = html_to_markdown(html, path.stem, include_figures, include_outputs)

        outputs = [((base / f"{path.stem}.md").as_posix(), fix_latex(text).encode("utf-8"))]
        for fig_name, content in figures:
            outputs.append(((base / folder / fig_name).as_posix(), content))
        if figures:
            note = f"{note}, {len(figures)} figure(s)".strip(", ")
        return outputs, note

    text = md.convert_stream(io.BytesIO(data), file_extension=ext).text_content
    return [((base / f"{path.stem}.md").as_posix(), fix_latex(text).encode("utf-8"))], ""