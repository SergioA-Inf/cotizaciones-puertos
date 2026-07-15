"""
pdf_utils.py
============
Todo lo relacionado con los PDF vive aquí.

La idea (Opción B que elegimos): NO se escribe nada encima del PDF del
proveedor. Se genera una página nueva de "Acta de Aprobación" y se pega
al final del original. Así el documento del proveedor queda intacto y el
acta siempre se ve limpia, sin importar cómo venga el PDF.
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas

ZONA = ZoneInfo("America/Panama")

ANCHO, ALTO = letter
MARGEN = 0.9 * inch


# ---------------------------------------------------------------------------
# Limpieza de la firma dibujada
# ---------------------------------------------------------------------------
def limpiar_firma(imagen_bytes: bytes) -> bytes:
    """
    Recibe el PNG de la firma y lo deja listo para estampar:
      1. Recorta el espacio en blanco sobrante alrededor del trazo.
      2. Deja el fondo transparente (para que no tape lo que hay debajo).

    Devuelve el PNG ya procesado, en bytes.
    """
    img = Image.open(io.BytesIO(imagen_bytes)).convert("RGBA")

    # Recortar al área realmente dibujada (usa el canal de transparencia).
    caja = img.split()[-1].getbbox()
    if caja:
        img = img.crop(caja)

    salida = io.BytesIO()
    img.save(salida, format="PNG")
    return salida.getvalue()


# ---------------------------------------------------------------------------
# Página de acta
# ---------------------------------------------------------------------------
def _dibujar_acta(c: rl_canvas.Canvas, cotizacion: dict, firma_bytes: bytes,
                  nombre_aprobador: str, fecha_aprobacion: datetime):
    """Dibuja el contenido del acta en una página."""

    y = ALTO - MARGEN

    # --- Encabezado ---
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(ANCHO / 2, y, "ACTA DE APROBACIÓN DE COTIZACIÓN")
    y -= 0.25 * inch

    c.setFont("Helvetica", 9)
    c.setFillGray(0.4)
    c.drawCentredString(ANCHO / 2, y, "Terminales de Cruceros · Panamá y Colón")
    c.setFillGray(0)
    y -= 0.35 * inch

    c.setLineWidth(1.2)
    c.line(MARGEN, y, ANCHO - MARGEN, y)
    y -= 0.4 * inch

    # --- Datos de la cotización ---
    campos = [
        ("N° de Orden de Compra", cotizacion.get("numero_odc", "—")),
        ("Fecha de la cotización", cotizacion.get("fecha_cotizacion", "—")),
        ("Sede", cotizacion.get("sede", "—")),
        ("Área solicitante", cotizacion.get("area", "—")),
        ("Proveedor", cotizacion.get("proveedor", "—")),
        ("Monto", f"US$ {float(cotizacion.get('monto', 0)):,.2f}"),
    ]

    for etiqueta, valor in campos:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGEN, y, f"{etiqueta}:")
        c.setFont("Helvetica", 10)
        c.drawString(MARGEN + 2.1 * inch, y, str(valor))
        y -= 0.28 * inch

    # --- Descripción (puede ser larga: se parte en varias líneas) ---
    y -= 0.1 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGEN, y, "Descripción:")
    y -= 0.22 * inch

    c.setFont("Helvetica", 10)
    texto = str(cotizacion.get("descripcion", "") or "—")
    ancho_util = ANCHO - 2 * MARGEN
    linea = ""
    for palabra in texto.split():
        prueba = f"{linea} {palabra}".strip()
        if c.stringWidth(prueba, "Helvetica", 10) <= ancho_util:
            linea = prueba
        else:
            c.drawString(MARGEN, y, linea)
            y -= 0.20 * inch
            linea = palabra
    if linea:
        c.drawString(MARGEN, y, linea)
        y -= 0.20 * inch

    # --- Bloque de firma ---
    y -= 0.5 * inch
    c.setLineWidth(0.5)
    c.setStrokeGray(0.7)
    c.line(MARGEN, y, ANCHO - MARGEN, y)
    c.setStrokeGray(0)
    y -= 0.35 * inch

    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGEN, y, "APROBADO POR:")
    y -= 1.35 * inch

    # Imagen de la firma, escalada para que quepa en 2.4" x 1.1"
    firma_img = Image.open(io.BytesIO(firma_bytes))
    max_ancho, max_alto = 2.4 * inch, 1.1 * inch
    escala = min(max_ancho / firma_img.width, max_alto / firma_img.height)
    ancho_f = firma_img.width * escala
    alto_f = firma_img.height * escala

    c.drawImage(
        ImageReaderBytes(firma_bytes),
        MARGEN,
        y + 0.1 * inch,
        width=ancho_f,
        height=alto_f,
        mask="auto",
    )

    # Línea y nombre debajo de la firma
    c.setLineWidth(0.8)
    c.line(MARGEN, y, MARGEN + 2.6 * inch, y)
    y -= 0.2 * inch

    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGEN, y, nombre_aprobador)
    y -= 0.18 * inch

    c.setFont("Helvetica", 9)
    c.setFillGray(0.35)
    c.drawString(MARGEN, y, "Junta Directiva")
    y -= 0.16 * inch
    c.drawString(MARGEN, y, f"Fecha y hora: {fecha_aprobacion.strftime('%d/%m/%Y %H:%M')} (hora de Panamá)")
    c.setFillGray(0)

    # --- Pie ---
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillGray(0.5)
    c.drawCentredString(
        ANCHO / 2,
        MARGEN - 0.3 * inch,
        "Documento generado automáticamente por el Sistema de Cotizaciones. "
        "La aprobación queda registrada con usuario, fecha y hora.",
    )
    c.setFillGray(0)


def ImageReaderBytes(data: bytes):
    """Envuelve unos bytes para que reportlab pueda dibujarlos como imagen."""
    from reportlab.lib.utils import ImageReader
    return ImageReader(io.BytesIO(data))


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------
def generar_pdf_firmado(pdf_original: bytes, cotizacion: dict,
                        firma_bytes: bytes, nombre_aprobador: str) -> bytes:
    """
    Toma el PDF original + la firma y devuelve un PDF nuevo con el acta
    de aprobación agregada al final.
    """
    fecha = datetime.now(ZONA)

    # 1. Crear la página del acta en memoria
    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=letter)
    _dibujar_acta(c, cotizacion, firma_bytes, nombre_aprobador, fecha)
    c.showPage()
    c.save()
    buffer.seek(0)

    # 2. Pegar: páginas del original + página del acta
    escritor = PdfWriter()

    for pagina in PdfReader(io.BytesIO(pdf_original)).pages:
        escritor.add_page(pagina)

    for pagina in PdfReader(buffer).pages:
        escritor.add_page(pagina)

    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()
