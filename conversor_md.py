import base64
import queue
import re
import tempfile
import threading
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from markitdown import MarkItDown

SUPPORTED = {".pdf", ".html", ".htm", ".docx", ".pptx", ".xlsx", ".csv", ".json", ".xml"}
PICKER_TYPES = [
    ("Archivos soportados", "*.pdf *.html *.htm *.zip *.docx *.pptx *.xlsx *.csv *.json *.xml"),
    ("Todos los archivos", "*.*"),
]

md = MarkItDown()

# Imágenes embebidas como data URI (PNG, JPG, GIF, WEBP)
DATA_IMG = re.compile(r"data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=]+)")
# Cadenas base64 largas (aquí aparece el .Rmd embebido en notebooks de R)
BASE64_LARGO = re.compile(r"[A-Za-z0-9+/=]{2000,}")
# Controles de la interfaz de la notebook que no son contenido
UI_NOTEBOOK = re.compile(
    r"^\s*\*?\s*(Show|Hide) All Code\s*$|^\s*\*?\s*Download Rmd\s*$", re.M
)


def unique_path(p: Path) -> Path:
    """Evita sobrescribir: si existe 'x.md', devuelve 'x_1.md', 'x_2.md', ..."""
    if not p.exists():
        return p
    i = 1
    while True:
        candidato = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not candidato.exists():
            return candidato
        i += 1


def arreglar_latex(texto: str) -> str:
    """Dentro de \\( \\) y \\[ \\], convierte '\\_' en '_' para que los subíndices funcionen."""
    def limpiar(m):
        return m.group(0).replace(r"\_", "_")
    texto = re.sub(r"\\\((.*?)\\\)", limpiar, texto, flags=re.S)
    texto = re.sub(r"\\\[(.*?)\\\]", limpiar, texto, flags=re.S)
    return texto


def limpiar_notebook(texto: str) -> str:
    """Quita los controles de la interfaz de la notebook (Show/Hide All Code, Download Rmd)."""
    texto = UI_NOTEBOOK.sub("", texto)
    if texto.startswith("Code\n"):
        texto = texto[len("Code\n"):]
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.lstrip()


def preparar_html(html_text: str, destino: Path):
    """
    Extrae las imágenes a una carpeta junto al .md, y el .Rmd embebido a un archivo.
    Devuelve el HTML sin esos bloques de base64.
    """
    carpeta_img = destino.parent / f"{destino.stem}_imagenes"
    contador = 0

    def guardar_img(m):
        nonlocal contador
        contador += 1
        ext = m.group(1).replace("jpeg", "jpg")
        carpeta_img.mkdir(parents=True, exist_ok=True)
        nombre = f"img_{contador:03d}.{ext}"
        (carpeta_img / nombre).write_bytes(base64.b64decode(m.group(2)))
        return f"{carpeta_img.name}/{nombre}"

    html_text = DATA_IMG.sub(guardar_img, html_text)

    rmd = None

    def revisar_bloque(m):
        nonlocal rmd
        cadena = m.group(0)
        try:
            texto = base64.b64decode(cadena + "=" * (-len(cadena) % 4)).decode("utf-8")
        except Exception:
            return cadena
        # Solo tratamos como .Rmd si parece un documento de R Markdown
        if texto.lstrip().startswith("---") and ("output:" in texto or "title:" in texto):
            if rmd is None:
                rmd = texto
            return ""
        return cadena

    html_text = BASE64_LARGO.sub(revisar_bloque, html_text)

    if rmd is not None:
        (destino.parent / f"{destino.stem}.Rmd").write_text(rmd, encoding="utf-8")
    return html_text


def convertir_a_md(origen: Path, destino: Path) -> None:
    """Convierte un archivo y escribe el .md en 'destino' (la ruta ya viene libre de colisiones)."""
    destino.parent.mkdir(parents=True, exist_ok=True)

    if origen.suffix.lower() in {".html", ".htm"}:
        html = origen.read_text(encoding="utf-8", errors="replace")
        html = preparar_html(html, destino)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_html = Path(tmp) / origen.name
            tmp_html.write_text(html, encoding="utf-8")
            texto = md.convert(str(tmp_html)).text_content
        texto = limpiar_notebook(texto)
    else:
        texto = md.convert(str(origen)).text_content

    texto = arreglar_latex(texto)
    destino.write_text(texto, encoding="utf-8")


def convertir_zip(zip_path: Path, out_dir: Path) -> int:
    """Extrae el ZIP en una carpeta temporal y convierte cada archivo compatible."""
    destino_base = out_dir / zip_path.stem
    contador = 0
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)  # ZipFile sanitiza rutas con '..' o absolutas
        for p in Path(tmp).rglob("*"):
            rel = p.relative_to(tmp)
            # Ignorar basura de macOS y archivos ocultos
            if any(part.startswith(("__MACOSX", ".")) for part in rel.parts):
                continue
            if p.is_file() and p.suffix.lower() in SUPPORTED:
                dest = unique_path(destino_base / rel.with_suffix(".md"))
                convertir_a_md(p, dest)
                contador += 1
    return contador


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Conversor a Markdown (markitdown)")
        root.geometry("720x560")

        self.archivos: list[Path] = []
        self.out_dir = tk.StringVar(value=str(Path.home() / "markdown_salida"))
        self.cola = queue.Queue()

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        botones = ttk.Frame(frame)
        botones.pack(fill="x")
        ttk.Button(botones, text="Agregar archivos", command=self.agregar_archivos).pack(side="left")
        ttk.Button(botones, text="Agregar carpeta", command=self.agregar_carpeta).pack(side="left", padx=5)
        ttk.Button(botones, text="Quitar seleccionados", command=self.quitar_seleccionados).pack(side="left")
        ttk.Button(botones, text="Limpiar", command=self.limpiar).pack(side="left", padx=5)

        self.lista = tk.Listbox(frame, selectmode="extended", height=10)
        self.lista.pack(fill="both", expand=True, pady=8)

        salida = ttk.Frame(frame)
        salida.pack(fill="x")
        ttk.Label(salida, text="Carpeta de salida:").pack(side="left")
        ttk.Entry(salida, textvariable=self.out_dir).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(salida, text="Elegir...", command=self.elegir_salida).pack(side="left")

        self.btn_convertir = ttk.Button(frame, text="Convertir a Markdown", command=self.iniciar)
        self.btn_convertir.pack(pady=8)

        self.progreso = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progreso.pack(fill="x")

        self.log = scrolledtext.ScrolledText(frame, height=10, state="disabled")
        self.log.pack(fill="both", expand=True, pady=(8, 0))

        self.root.after(100, self.revisar_cola)

    # ---------- Selección ----------
    def agregar_archivos(self):
        rutas = filedialog.askopenfilenames(filetypes=PICKER_TYPES)
        for r in rutas:
            self._agregar(Path(r))

    def agregar_carpeta(self):
        carpeta = filedialog.askdirectory()
        if not carpeta:
            return
        for p in Path(carpeta).rglob("*"):
            if p.is_file() and (p.suffix.lower() in SUPPORTED or p.suffix.lower() == ".zip"):
                self._agregar(p)

    def _agregar(self, p: Path):
        if p not in self.archivos:
            self.archivos.append(p)
            self.lista.insert("end", str(p))

    def quitar_seleccionados(self):
        for i in reversed(self.lista.curselection()):
            self.lista.delete(i)
            del self.archivos[i]

    def limpiar(self):
        self.lista.delete(0, "end")
        self.archivos.clear()

    def elegir_salida(self):
        carpeta = filedialog.askdirectory()
        if carpeta:
            self.out_dir.set(carpeta)

    # ---------- Conversión ----------
    def iniciar(self):
        if not self.archivos:
            messagebox.showwarning("Sin archivos", "Agrega al menos un archivo.")
            return
        out = Path(self.out_dir.get()).expanduser()
        out.mkdir(parents=True, exist_ok=True)

        self.btn_convertir.config(state="disabled")
        self.progreso["value"] = 0
        threading.Thread(target=self._trabajar, args=(list(self.archivos), out), daemon=True).start()

    def _trabajar(self, archivos, out):
        total = len(archivos)
        for i, f in enumerate(archivos, 1):
            try:
                if f.suffix.lower() == ".zip":
                    n = convertir_zip(f, out)
                    self.cola.put(("log", f"OK    {f.name} -> {n} archivo(s) convertido(s)"))
                else:
                    dest = unique_path(out / f.with_suffix(".md").name)
                    convertir_a_md(f, dest)
                    self.cola.put(("log", f"OK    {f.name} -> {dest.name}"))
            except Exception as e:
                self.cola.put(("log", f"ERROR {f.name}: {e}"))
            self.cola.put(("progreso", i / total * 100))
        self.cola.put(("fin", None))

    # ---------- Comunicación con la GUI ----------
    def revisar_cola(self):
        try:
            while True:
                tipo, valor = self.cola.get_nowait()
                if tipo == "log":
                    self._escribir(valor)
                elif tipo == "progreso":
                    self.progreso["value"] = valor
                elif tipo == "fin":
                    self.btn_convertir.config(state="normal")
                    self._escribir("— Proceso terminado —")
        except queue.Empty:
            pass
        self.root.after(100, self.revisar_cola)

    def _escribir(self, texto: str):
        self.log.config(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()