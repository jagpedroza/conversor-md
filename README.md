# Markdown Converter

Converts course material into Markdown so it can be used as context for an LLM tutor.

## What it converts

- **Convert to Markdown:** HTML notebooks (including R notebooks), PDF, DOCX, PPTX and XLSX.
- **Copy unchanged:** any other file, such as `.Rmd`, `.csv` or `.txt`.
- **Skip:** files such as `Table of Contents.html`.

ZIP files are processed file by file, and their folder structure is preserved.

## Repository structure

```
.
├── webapp/          Main app (Gradio). Start here.
├── desktop/         Desktop scripts (Tkinter), older version of the same conversion
├── versions/        Earlier experiments, kept for reference
│   └── streamlit/   Streamlit version: not tested, not maintained
└── README.md
```

## Windows setup (webapp)

Requires Python 3.13. Some dependencies do not yet provide packages for Python 3.14 or 3.15.

Open PowerShell in the `webapp` folder:

```powershell
cd webapp
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run the webapp (Windows)

- **Double-click** `iniciar.bat` in the `webapp` folder, or
- From PowerShell, with the environment active:

```powershell
python launcher.py
```

The app opens in your browser at `http://127.0.0.1:7860`. Keep the console window open while you use it: closing it stops the app.

## How to use the webapp

1. **Choose files:** upload files or ZIPs.
2. **Review actions:** each file gets a suggested action. Change it in the table if needed.
3. **Options:**
   - *Include figures:* keep embedded images. Off by default.
   - *Include code outputs:* keep R output blocks. Off by default.
4. **Process**, then **Download ZIP**.

The ZIP contains the converted files, the copied files, and a `summary.txt` describing what happened to each file.

## Notes

- Each batch is limited to 20 MB. The limit is `MAX_BATCH_BYTES` in `converter_core.py`.
- Files are processed in memory and not stored by the app.
- R notebooks with embedded source are converted from that source, so `{r}` chunks stay runnable in RStudio.

## Desktop scripts (Windows)

The scripts in `desktop/` are Tkinter applications.

```powershell
cd desktop
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python conversor_md.py
```

## Earlier versions

`versions/streamlit/` contains an earlier Streamlit version of the same app. It was not fully tested and is not maintained.