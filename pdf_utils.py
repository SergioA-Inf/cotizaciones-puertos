"""
pdf_utils.py
============
Todo lo relacionado con los PDF vive aquí.

La idea (Opción B): NO se escribe nada encima del PDF del proveedor. Se
genera una página nueva de "Acta de Aprobación" y se pega al final del
original. Así el documento del proveedor queda intacto y el acta siempre
se ve limpia, sin importar cómo venga el PDF.

Desde el Paso 8 el acta lleva el logo de la sede correspondiente.
"""

import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

ZONA = ZoneInfo("America/Panama")

ANCHO, ALTO = letter
MARGEN = 0.9 * inch

# Colores de marca, tomados de los propios logos
AZUL = (0x14 / 255, 0x26 / 255, 0x4F / 255)
VERDE = (0x61 / 255, 0x90 / 255, 0x4C / 255)

# Qué logo usa cada sede (sin extensión, a propósito: ver resolver_logo)
LOGOS = {
    "Panamá": "logo_panama",
    "Colón": "logo_colon",
}


def resolver_logo(sede: str):
    """
    Busca el archivo del logo de la sede.

    Prueba varias extensiones porque Windows esconde las extensiones y un
    archivo guardado como "logo.png" puede terminar siendo "logo.png.png"
    en el disco (lección aprendida en la app de HVAC).
    Devuelve la ruta, o None si no encuentra nada.
    """
    base = LOGOS.get(sede)
    if not base:
        return None

    carpeta = os.path.dirname(os.path.abspath(__file__))
    candidatos = [
        f"{base}.png", f"{base}.PNG", f"{base}.png.png",
        f"{base}.jpg", f"{base}.jpeg", f"{base}.png.jpg",
    ]
    for nombre in candidatos:
        ruta = os.path.join(carpeta, nombre)
        if os.path.exists(ruta):
            return ruta
    return None


# ---------------------------------------------------------------------------
# Limpieza de la firma dibujada
# ---------------------------------------------------------------------------
def limpiar_firma(imagen_bytes: bytes) -> bytes:
    """
    Deja la firma lista para estampar: recorta el espacio sobrante
    alrededor del trazo y conserva el fondo transparente.
    """
    img = Image.open(io.BytesIO(imagen_bytes)).convert("RGBA")
    caja = img.split()[-1].getbbox()
    if caja:
        img = img.crop(caja)

    salida = io.BytesIO()
    img.save(salida, format="PNG")
    return salida.getvalue()


def _imagen(data_o_ruta):
    """Envuelve bytes o una ruta para que reportlab pueda dibujarlos."""
    if isinstance(data_o_ruta, bytes):
        return ImageReader(io.BytesIO(data_o_ruta))
    return ImageReader(data_o_ruta)


# ---------------------------------------------------------------------------
# Página de acta
# ---------------------------------------------------------------------------
def _dibujar_acta(c, cotizacion, firma_bytes, nombre_aprobador, fecha):
    y = ALTO - MARGEN

    # --- Logo de la sede ---------------------------------------------------
    ruta_logo = resolver_logo(cotizacion.get("sede", ""))
    if ruta_logo:
        logo = Image.open(ruta_logo)
        max_ancho, max_alto = 2.3 * inch, 0.8 * inch
        escala = min(max_ancho / logo.width, max_alto / logo.height)
        ancho_l, alto_l = logo.width * escala, logo.height * escala
        y -= alto_l
        c.drawImage(
            _imagen(ruta_logo), (ANCHO - ancho_l) / 2, y,
            width=ancho_l, height=alto_l, mask="auto",
        )
        y -= 0.3 * inch

    # --- Encabezado --------------------------------------------------------
    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(ANCHO / 2, y, "ACTA DE APROBACIÓN DE COTIZACIÓN")
    y -= 0.22 * inch

    c.setFillGray(0.42)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(ANCHO / 2, y, str(cotizacion.get("sede", "")).upper())
    y -= 0.3 * inch

    # Línea de marca: azul (Panamá) -> verde (Colón)
    _linea_marca(c, y)
    y -= 0.4 * inch

    # --- Datos -------------------------------------------------------------
    campos = [
        ("N° de Orden de Compra", cotizacion.get("numero_odc", "—")),
        ("Fecha de la cotización", cotizacion.get("fecha_cotizacion", "—")),
        ("Área solicitante", cotizacion.get("area", "—")),
        ("Proveedor", cotizacion.get("proveedor", "—")),
        ("Monto", f"US$ {float(cotizacion.get('monto', 0)):,.2f}"),
    ]

    for etiqueta, valor in campos:
        c.setFillColorRGB(*AZUL)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGEN, y, f"{etiqueta}:")
        c.setFillGray(0.1)
        c.setFont("Helvetica", 10)
        c.drawString(MARGEN + 2.1 * inch, y, str(valor))
        y -= 0.28 * inch

    # --- Descripción (se parte en líneas) ---------------------------------
    y -= 0.08 * inch
    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGEN, y, "Descripción:")
    y -= 0.22 * inch

    c.setFillGray(0.1)
    c.setFont("Helvetica", 10)
    ancho_util = ANCHO - 2 * MARGEN
    linea = ""
    for palabra in str(cotizacion.get("descripcion", "") or "—").split():
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

    # --- Firma -------------------------------------------------------------
    y -= 0.5 * inch
    c.setStrokeGray(0.82)
    c.setLineWidth(0.5)
    c.line(MARGEN, y, ANCHO - MARGEN, y)
    y -= 0.35 * inch

    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(MARGEN, y, "APROBADO POR")
    y -= 1.35 * inch

    firma = Image.open(io.BytesIO(firma_bytes))
    max_ancho, max_alto = 2.4 * inch, 1.1 * inch
    escala = min(max_ancho / firma.width, max_alto / firma.height)

    c.drawImage(
        _imagen(firma_bytes), MARGEN, y + 0.1 * inch,
        width=firma.width * escala, height=firma.height * escala,
        mask="auto",
    )

    c.setStrokeColorRGB(*AZUL)
    c.setLineWidth(0.8)
    c.line(MARGEN, y, MARGEN + 2.6 * inch, y)
    y -= 0.2 * inch

    c.setFillGray(0.1)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGEN, y, nombre_aprobador)
    y -= 0.18 * inch

    c.setFillGray(0.42)
    c.setFont("Helvetica", 9)
    c.drawString(MARGEN, y, "Junta Directiva")
    y -= 0.16 * inch
    c.drawString(
        MARGEN, y,
        f"Fecha y hora: {fecha.strftime('%d/%m/%Y %H:%M')} (hora de Panamá)",
    )

    # --- Pie ---------------------------------------------------------------
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillGray(0.55)
    c.drawCentredString(
        ANCHO / 2, MARGEN - 0.3 * inch,
        "Documento generado por el Sistema de Cotizaciones. "
        "La aprobación queda registrada con usuario, fecha y hora.",
    )
    c.setFillGray(0)


def _linea_marca(c, y):
    """Línea fina que va del azul de Panamá al verde de Colón."""
    x0, x1 = MARGEN, ANCHO - MARGEN
    pasos = 120
    ancho_paso = (x1 - x0) / pasos
    c.setLineWidth(1.6)
    for i in range(pasos):
        t = i / (pasos - 1)
        c.setStrokeColorRGB(
            AZUL[0] + (VERDE[0] - AZUL[0]) * t,
            AZUL[1] + (VERDE[1] - AZUL[1]) * t,
            AZUL[2] + (VERDE[2] - AZUL[2]) * t,
        )
        c.line(x0 + i * ancho_paso, y, x0 + (i + 1) * ancho_paso, y)
    c.setStrokeColorRGB(0, 0, 0)


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------
def generar_pdf_firmado(pdf_original: bytes, cotizacion: dict,
                        firma_bytes: bytes, nombre_aprobador: str) -> bytes:
    """PDF original + acta de aprobación al final."""
    fecha = datetime.now(ZONA)

    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=letter)
    _dibujar_acta(c, cotizacion, firma_bytes, nombre_aprobador, fecha)
    c.showPage()
    c.save()
    buffer.seek(0)

    escritor = PdfWriter()
    for pagina in PdfReader(io.BytesIO(pdf_original)).pages:
        escritor.add_page(pagina)
    for pagina in PdfReader(buffer).pages:
        escritor.add_page(pagina)

    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()
