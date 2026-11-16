# Markdown Converter

Converts course material into Markdown so it can be used as context for an LLM tutor.

Supported inputs:

- HTML notebooks, including R Markdown notebooks rendered to HTML
- PDF, DOCX, PPTX and XLSX files
- ZIP archives (processed file by file, folder structure preserved)

Files that are not converted (for example `.Rmd`, `.csv` or `.txt`) can be copied unchanged. Files such as `Table of Contents.html` can be skipped.

## Repository structure

```
.
├── webapp/          Main app: web interface built with Gradio (start here)
├── desktop/         Desktop scripts (Tkinter), same conversion logic, older
├── versions/        Previous experiments, kept for reference
│   └── streamlit/   Streamlit version: not tested, not maintained
└── README.md
```

## Web app (main)

Located in `webapp/`.

### Setup

Requires Python 3.13. Some dependencies do not yet provide packages for Python 3.14 or 3.15.

```bash
cd webapp
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Run

```bash
python launcher.py
```

This opens the app in your browser. On Windows you can also double-click `iniciar.bat`.

### How to use

1. **Choose files:** upload files or ZIPs.
2. **Review actions:** each file gets a suggested action. Change it in the table if needed:
   - `convert`: convert to Markdown
   - `copy`: keep the file unchanged
   - `skip`: leave it out
3. **Options:**
   - *Include figures:* keep embedded images. Off by default, because a text-based tutor cannot see them.
   - *Include code outputs:* keep R output blocks. Off by default, because the code is enough to teach the procedure.
4. **Process**, then **Download ZIP**.

The ZIP contains the converted files, the copied files, and a `summary.txt` describing what happened to each file.

### Notes

- Each batch is limited to 20 MB. The limit is `MAX_BATCH_BYTES` in `converter_core.py`.
- Files are processed in memory and the app does not store them. If you host the app on a third-party service, the uploads still travel to that service's servers.
- R notebooks that embed their source are converted from that source, which keeps the `{r}` chunks runnable in RStudio.

## Desktop scripts

Located in `desktop/`. These are Tkinter applications with the same conversion logic, run with `python conversor_md.py` after installing `requirements.txt` in that folder.

## Previous versions

`versions/streamlit/` contains an earlier Streamlit version of the same app. It was not fully tested and is not maintained. Keep it only for reference.