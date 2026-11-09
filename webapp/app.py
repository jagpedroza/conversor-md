import io
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import gradio as gr
import pandas as pd

from converter_core import ACTIONS, MAX_BATCH_BYTES, convert_item, list_zip_entries, suggested_action


def load_items(files):
    """Expand uploads into one item per file, opening ZIPs in memory."""
    items = []
    for f in files or []:
        path = Path(f)
        data = path.read_bytes()
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in list_zip_entries(data):
                    items.append({
                        "display": f"{path.name} > {name}",
                        "full": f"{path.stem}/{name}",
                        "name": name,
                        "data": z.read(name),
                    })
        else:
            items.append({"display": path.name, "full": path.name,
                          "name": path.name, "data": data})
    return items


def empty_table():
    return pd.DataFrame(columns=["File", "Action"])


def on_upload(files):
    items = load_items(files)
    total = sum(len(i["data"]) for i in items)
    table = pd.DataFrame(
        [[i["display"], suggested_action(i["name"])] for i in items],
        columns=["File", "Action"],
    )
    mb = total / (1024 * 1024)
    if total > MAX_BATCH_BYTES:
        status = f"⚠️ {mb:.1f} MB in this batch. The limit is 20 MB. Remove some files."
    elif items:
        status = f"{len(items)} item(s), {mb:.1f} MB total."
    else:
        status = ""
    return table, items, status


def unique_key(path: str, taken: dict) -> str:
    if path not in taken:
        return path
    p = Path(path)
    i = 1
    while True:
        candidate = p.with_name(f"{p.stem}_{i}{p.suffix}").as_posix()
        if candidate not in taken:
            return candidate
        i += 1


def process(table, items, include_figures, include_outputs, progress=gr.Progress()):
    if not items:
        raise gr.Error("Upload at least one file.")

    actions = [str(a).strip().lower() for a in table["Action"].tolist()]
    if len(actions) != len(items):
        raise gr.Error("The action table does not match the uploaded files. Upload them again.")
    bad = [a for a in actions if a not in ACTIONS]
    if bad:
        raise gr.Error(f"Invalid action(s): {', '.join(set(bad))}. Use: convert, copy, or skip.")

    selected = sum(len(i["data"]) for i, a in zip(items, actions) if a != "skip")
    if selected > MAX_BATCH_BYTES:
        raise gr.Error(f"Selected files total {selected / 1048576:.1f} MB. The limit is 20 MB.")

    outputs = {}
    log = []
    for n, (item, action) in enumerate(zip(items, actions), 1):
        progress(n / len(items), desc=item["display"])
        try:
            files, note = convert_item(item["full"], item["data"], action,
                                       include_figures, include_outputs)
            tag = {"convert": "CONVERTED", "copy": "COPIED", "skip": "SKIPPED"}[action]
            written = []
            for path, content in files:
                key = unique_key(path, outputs)
                outputs[key] = content
                written.append(key)
            line = f"{tag:<11}{item['display']}"
            if written:
                line += " -> " + ", ".join(written)
            if note:
                line += f" ({note})"
        except Exception as e:
            line = f"ERROR      {item['display']}: {e}"
        log.append(line)

    header = [f"Conversion run: {datetime.now():%Y-%m-%d %H:%M}",
              f"Include figures: {include_figures}",
              f"Include code outputs: {include_outputs}", ""]
    summary = "\n".join(header + log) + "\n"
    outputs["summary.txt"] = summary.encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in outputs.items():
            z.writestr(path, content)

    # Gradio needs a file path to serve the download. Only the output ZIP is written here.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="markdown_") as tmp:
        tmp.write(buffer.getvalue())

    return gr.update(value=tmp.name, interactive=True), summary


def clear_all():
    return (
        None,                                   # uploads
        [],                                     # items state
        empty_table(),                          # table
        "",                                     # status
        gr.update(value=None, interactive=False),  # download button
        "",                                     # log
    )


with gr.Blocks(title="Markdown Converter") as demo:
    gr.Markdown(
        "# Markdown Converter\n"
        "Upload files or ZIPs. Everything is processed in memory and nothing is stored. "
        "Only the output ZIP is returned.\n\n"
        "**Supported types:** Convert to Markdown: HTML (including R notebooks), PDF, DOCX, PPTX, XLSX. "
        "Copy unchanged: any other file, such as Rmd, CSV or TXT. "
        "Skip: Table of Contents files."
    )

    items_state = gr.State([])

    gr.Markdown("### 1. Choose files")
    uploads = gr.File(label="Files or ZIPs", file_count="multiple")
    status = gr.Markdown()

    table = gr.Dataframe(
        headers=["File", "Action"],
        datatype=["str", "str"],
        interactive=True,
        wrap=True,
        column_widths=["75%", "25%"],
        label="Action per file: convert, copy, or skip",
    )

    with gr.Row():
        include_figures = gr.Checkbox(label="Include figures", value=False)
        include_outputs = gr.Checkbox(label="Include code outputs", value=False)

    gr.Markdown("### 2. Process")
    with gr.Row():
        process_btn = gr.Button("Process", variant="secondary")
        clear_btn = gr.Button("Clear", variant="stop")

    gr.Markdown("### 3. Download")
    download_btn = gr.DownloadButton("Download ZIP", variant="primary", interactive=False)
    log = gr.Textbox(label="Log", lines=12, interactive=False)

    uploads.change(on_upload, inputs=uploads, outputs=[table, items_state, status])
    process_btn.click(process,
                      inputs=[table, items_state, include_figures, include_outputs],
                      outputs=[download_btn, log])
    clear_btn.click(clear_all,
                    outputs=[uploads, items_state, table, status, download_btn, log])

if __name__ == "__main__":
    demo.launch(show_api=False)