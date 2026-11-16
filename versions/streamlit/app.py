import hashlib
import io
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from converter_core import ACTIONS, MAX_BATCH_BYTES, convert_item, list_zip_entries, suggested_action

st.set_page_config(page_title="Markdown Converter", page_icon="📄", layout="wide")

MB = 1024 * 1024
STEPS = ["1. Choose files", "2. Process", "3. Download"]
HINTS = {
    1: "upload files or ZIPs to begin.",
    2: "check the action for each file, then click Process.",
    3: "click Download ZIP to save the results.",
}
LABELS = {"convert": "CONVERTED", "copy": "COPIED", "skip": "SKIPPED"}

if "upload_gen" not in st.session_state:
    st.session_state.upload_gen = 0
if "result" not in st.session_state:
    st.session_state.result = None


def load_items(uploaded):
    """Expand uploads into one item per file, opening ZIPs in memory."""
    items = []
    for f in uploaded:
        data = f.getvalue()
        if f.name.lower().endswith(".zip"):
            stem = Path(f.name).stem
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for inner in list_zip_entries(data):
                    items.append({
                        "display": f"{f.name} > {inner}",
                        "full": f"{stem}/{inner}",
                        "name": inner,
                        "data": z.read(inner),
                    })
        else:
            items.append({"display": f.name, "full": f.name, "name": f.name, "data": data})
    return items


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


def run_conversion(items, actions, include_figures, include_outputs):
    outputs = {}
    log = []
    for item, action in zip(items, actions):
        try:
            files, note = convert_item(item["full"], item["data"], action,
                                       include_figures, include_outputs)
            written = []
            for path, content in files:
                key = unique_key(path, outputs)
                outputs[key] = content
                written.append(key)
            line = f"{LABELS[action]:<11}{item['display']}"
            if written:
                line += " -> " + ", ".join(written)
            if note:
                line += f" ({note})"
        except Exception as e:
            line = f"ERROR      {item['display']}: {e}"
        log.append(line)

    header = [
        f"Conversion run: {datetime.now():%Y-%m-%d %H:%M}",
        f"Include figures: {include_figures}",
        f"Include code outputs: {include_outputs}",
        "",
    ]
    summary = "\n".join(header + log) + "\n"
    outputs["summary.txt"] = summary.encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in outputs.items():
            z.writestr(path, content)
    return buffer.getvalue(), summary


# ---------- Layout ----------
st.title("Markdown Converter")
st.write(
    "Upload files or ZIPs. Everything is processed in memory and nothing is stored. "
    "Only the output ZIP is returned."
)
st.markdown(
    "**Supported types:** Convert to Markdown: HTML (including R notebooks), PDF, DOCX, PPTX, XLSX. "
    "Copy unchanged: any other file, such as Rmd, CSV or TXT. "
    "Skip: Table of Contents files."
)
bar = st.empty()  # filled at the end, once we know the current step

st.subheader("1. Choose files")
uploaded = st.file_uploader(
    "Files or ZIPs",
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.upload_gen}",
)
items = load_items(uploaded) if uploaded else []
total = sum(len(i["data"]) for i in items)
too_big = total > MAX_BATCH_BYTES

if items:
    st.caption(f"{len(items)} item(s), {total / MB:.1f} MB total.")
    if too_big:
        st.warning(f"{total / MB:.1f} MB in this batch. The limit is {MAX_BATCH_BYTES // MB} MB. Remove some files.")
    sig = hashlib.md5(
        "|".join(f"{i['display']}:{len(i['data'])}" for i in items).encode()
    ).hexdigest()
    df = pd.DataFrame({
        "File": [i["display"] for i in items],
        "Action": [suggested_action(i["name"]) for i in items],
    })
    edited = st.data_editor(
        df,
        key=f"table_{sig}",
        disabled=["File"],
        hide_index=True,
        column_config={
            "Action": st.column_config.SelectboxColumn("Action", options=list(ACTIONS), required=True),
        },
    )
    actions = [str(a) for a in edited["Action"].tolist()]
else:
    sig = ""
    actions = []

c1, c2 = st.columns(2)
include_figures = c1.checkbox("Include figures", value=False)
include_outputs = c2.checkbox("Include code outputs", value=False)

# Any change to files, actions or options makes the previous ZIP stale
current_key = (sig, tuple(actions), include_figures, include_outputs)

st.subheader("2. Process")
b1, b2 = st.columns(2)
process_clicked = b1.button("Process", disabled=not items or too_big, type="primary")
if b2.button("Clear"):
    st.session_state.upload_gen += 1
    st.session_state.result = None
    st.rerun()

if process_clicked:
    selected = sum(len(i["data"]) for i, a in zip(items, actions) if a != "skip")
    if selected > MAX_BATCH_BYTES:
        st.error(f"Selected files total {selected / MB:.1f} MB. The limit is {MAX_BATCH_BYTES // MB} MB.")
    else:
        with st.spinner("Converting..."):
            data, summary = run_conversion(items, actions, include_figures, include_outputs)
        st.session_state.result = {"key": current_key, "data": data, "summary": summary}

result = st.session_state.result
ready = bool(result) and result["key"] == current_key

st.subheader("3. Download")
if ready:
    st.download_button(
        "Download ZIP",
        result["data"],
        file_name=f"markdown_{datetime.now():%Y%m%d_%H%M}.zip",
        mime="application/zip",
        type="primary",
    )
    st.text_area("Log", result["summary"], height=220, disabled=True)
else:
    st.button("Download ZIP", disabled=True)
    st.caption("Available after you click Process.")

if not items:
    step = 1
elif ready:
    step = 3
else:
    step = 2

parts = [f"**{s}**" if i == step else s for i, s in enumerate(STEPS, 1)]
bar.markdown(" → ".join(parts) + f"\n\n*Next:* {HINTS[step]}")