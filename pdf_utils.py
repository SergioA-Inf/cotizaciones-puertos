"""
pdf_utils.py
============
Todo lo relacionado con los PDF vive aquí.

Paso 10: el EXPEDIENTE. Al cerrar una orden se arma un solo PDF con:
    1. La cotización original del proveedor
    2. El acta de aprobación firmada por la Junta
    3. Una hoja separadora de respaldos
    4. Cada respaldo (PDFs pegados tal cual, fotos convertidas a página)

Así el área administrativa baja un único archivo y tiene el caso completo.
"""

import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps
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

LOGOS = {"Panamá": "logo_panama", "Colón": "logo_colon"}

# Tamaño máximo al que se reducen las fotos antes de meterlas al PDF.
# Sin esto, 5 fotos de celular producen un archivo de 40 MB.
MAX_LADO_FOTO = 1600


def resolver_logo(sede: str):
    """
    Busca el archivo del logo de la sede.

    Prueba varias extensiones porque Windows esconde las extensiones y un
    archivo guardado como "logo.png" puede terminar siendo "logo.png.png"
    en el disco (lección aprendida en la app de HVAC).
    """
    base = LOGOS.get(sede)
    if not base:
        return None

    carpeta = os.path.dirname(os.path.abspath(__file__))
    for nombre in (f"{base}.png", f"{base}.PNG", f"{base}.png.png",
                   f"{base}.jpg", f"{base}.jpeg", f"{base}.png.jpg"):
        ruta = os.path.join(carpeta, nombre)
        if os.path.exists(ruta):
            return ruta
    return None


def es_imagen(nombre: str) -> bool:
    return nombre.lower().endswith((".png", ".jpg", ".jpeg"))


def es_pdf(nombre: str) -> bool:
    return nombre.lower().endswith(".pdf")


# ---------------------------------------------------------------------------
# Firma
# ---------------------------------------------------------------------------
def limpiar_firma(imagen_bytes: bytes) -> bytes:
    """Recorta el espacio sobrante y conserva el fondo transparente."""
    img = Image.open(io.BytesIO(imagen_bytes)).convert("RGBA")
    caja = img.split()[-1].getbbox()
    if caja:
        img = img.crop(caja)
    salida = io.BytesIO()
    img.save(salida, format="PNG")
    return salida.getvalue()


def _imagen(data_o_ruta):
    if isinstance(data_o_ruta, bytes):
        return ImageReader(io.BytesIO(data_o_ruta))
    return ImageReader(data_o_ruta)


def _linea_marca(c, y):
    """Línea fina que va del azul de Panamá al verde de Colón."""
    x0, x1 = MARGEN, ANCHO - MARGEN
    pasos = 120
    paso = (x1 - x0) / pasos
    c.setLineWidth(1.6)
    for i in range(pasos):
        t = i / (pasos - 1)
        c.setStrokeColorRGB(
            AZUL[0] + (VERDE[0] - AZUL[0]) * t,
            AZUL[1] + (VERDE[1] - AZUL[1]) * t,
            AZUL[2] + (VERDE[2] - AZUL[2]) * t,
        )
        c.line(x0 + i * paso, y, x0 + (i + 1) * paso, y)
    c.setStrokeColorRGB(0, 0, 0)


def _dibujar_logo(c, sede, y):
    """Dibuja el logo centrado y devuelve la nueva altura."""
    ruta = resolver_logo(sede)
    if not ruta:
        return y
    logo = Image.open(ruta)
    escala = min(2.3 * inch / logo.width, 0.8 * inch / logo.height)
    ancho, alto = logo.width * escala, logo.height * escala
    y -= alto
    c.drawImage(_imagen(ruta), (ANCHO - ancho) / 2, y,
                width=ancho, height=alto, mask="auto")
    return y - 0.3 * inch


def _parrafo(c, texto, y, fuente="Helvetica", tam=10):
    """Escribe un texto partiéndolo en líneas. Devuelve la nueva altura."""
    c.setFont(fuente, tam)
    ancho_util = ANCHO - 2 * MARGEN
    linea = ""
    for palabra in str(texto).split():
        prueba = f"{linea} {palabra}".strip()
        if c.stringWidth(prueba, fuente, tam) <= ancho_util:
            linea = prueba
        else:
            c.drawString(MARGEN, y, linea)
            y -= 0.20 * inch
            linea = palabra
    if linea:
        c.drawString(MARGEN, y, linea)
        y -= 0.20 * inch
    return y


# ---------------------------------------------------------------------------
# Acta de aprobación
# ---------------------------------------------------------------------------
def _dibujar_acta(c, cotizacion, firma_bytes, nombre_aprobador, fecha):
    y = _dibujar_logo(c, cotizacion.get("sede", ""), ALTO - MARGEN)

    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(ANCHO / 2, y, "ACTA DE APROBACIÓN DE COTIZACIÓN")
    y -= 0.22 * inch

    c.setFillGray(0.42)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(ANCHO / 2, y, str(cotizacion.get("sede", "")).upper())
    y -= 0.3 * inch

    _linea_marca(c, y)
    y -= 0.4 * inch

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

    y -= 0.08 * inch
    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGEN, y, "Descripción:")
    y -= 0.22 * inch
    c.setFillGray(0.1)
    y = _parrafo(c, cotizacion.get("descripcion", "") or "—", y)

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
    escala = min(2.4 * inch / firma.width, 1.1 * inch / firma.height)
    c.drawImage(_imagen(firma_bytes), MARGEN, y + 0.1 * inch,
                width=firma.width * escala, height=firma.height * escala,
                mask="auto")

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
    c.drawString(MARGEN, y,
                 f"Fecha y hora: {fecha.strftime('%d/%m/%Y %H:%M')} (hora de Panamá)")

    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillGray(0.55)
    c.drawCentredString(
        ANCHO / 2, MARGEN - 0.3 * inch,
        "Documento generado por el Sistema de Cotizaciones. "
        "La aprobación queda registrada con usuario, fecha y hora.",
    )
    c.setFillGray(0)


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


# ---------------------------------------------------------------------------
# Expediente
# ---------------------------------------------------------------------------
def _hoja_separadora(cotizacion: dict, respaldos, fecha) -> bytes:
    """Portada de la sección de respaldos."""
    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=letter)

    y = _dibujar_logo(c, cotizacion.get("sede", ""), ALTO - MARGEN)

    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(ANCHO / 2, y, "RESPALDOS DE EJECUCIÓN")
    y -= 0.22 * inch

    c.setFillGray(0.42)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(
        ANCHO / 2, y,
        f"{cotizacion.get('numero_odc', '')} · {str(cotizacion.get('sede', '')).upper()}",
    )
    y -= 0.3 * inch

    _linea_marca(c, y)
    y -= 0.4 * inch

    campos = [
        ("Proveedor", cotizacion.get("proveedor", "—")),
        ("Área solicitante", cotizacion.get("area", "—")),
        ("Monto", f"US$ {float(cotizacion.get('monto', 0)):,.2f}"),
        ("Ejecutado por", cotizacion.get("ejecutado_por", "—")),
        ("Fecha de registro", fecha.strftime("%d/%m/%Y %H:%M") + " (hora de Panamá)"),
    ]
    for etiqueta, valor in campos:
        c.setFillColorRGB(*AZUL)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGEN, y, f"{etiqueta}:")
        c.setFillGray(0.1)
        c.setFont("Helvetica", 10)
        c.drawString(MARGEN + 2.1 * inch, y, str(valor))
        y -= 0.28 * inch

    nota = cotizacion.get("nota_ejecucion")
    if nota:
        y -= 0.08 * inch
        c.setFillColorRGB(*AZUL)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGEN, y, "Nota de ejecución:")
        y -= 0.22 * inch
        c.setFillGray(0.1)
        y = _parrafo(c, nota, y)

    y -= 0.25 * inch
    c.setFillColorRGB(*AZUL)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGEN, y, f"Archivos adjuntos ({len(respaldos)}):")
    y -= 0.24 * inch

    c.setFillGray(0.1)
    c.setFont("Helvetica", 9.5)
    for i, r in enumerate(respaldos, start=1):
        c.drawString(MARGEN + 0.12 * inch, y, f"{i}.  {r['nombre']}")
        y -= 0.21 * inch
        if y < MARGEN + 0.5 * inch:      # por si son muchísimos
            break

    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillGray(0.55)
    c.drawCentredString(
        ANCHO / 2, MARGEN - 0.3 * inch,
        "Los archivos listados se anexan a continuación, en este mismo orden.",
    )

    c.showPage()
    c.save()
    return buffer.getvalue()


def _pagina_de_imagen(contenido: bytes, nombre: str) -> bytes:
    """Convierte una foto en una página del expediente."""
    img = Image.open(io.BytesIO(contenido))

    # Las fotos de celular traen la orientación en los datos EXIF: sin esto
    # salen acostadas.
    img = ImageOps.exif_transpose(img)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Reducir para que el expediente no pese decenas de MB
    if max(img.size) > MAX_LADO_FOTO:
        escala = MAX_LADO_FOTO / max(img.size)
        img = img.resize(
            (int(img.width * escala), int(img.height * escala)), Image.LANCZOS
        )

    comprimida = io.BytesIO()
    img.save(comprimida, format="JPEG", quality=82)

    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=letter)

    max_ancho = ANCHO - 2 * MARGEN
    max_alto = ALTO - 2 * MARGEN - 0.35 * inch
    escala = min(max_ancho / img.width, max_alto / img.height)
    ancho, alto = img.width * escala, img.height * escala

    c.drawImage(
        _imagen(comprimida.getvalue()),
        (ANCHO - ancho) / 2, ALTO - MARGEN - alto,
        width=ancho, height=alto,
    )

    c.setFont("Helvetica", 8.5)
    c.setFillGray(0.4)
    c.drawCentredString(ANCHO / 2, MARGEN - 0.25 * inch, nombre)

    c.showPage()
    c.save()
    return buffer.getvalue()


def generar_expediente(pdf_firmado: bytes, cotizacion: dict, respaldos) -> bytes:
    """
    Arma el PDF completo de la orden.

    respaldos: lista de {"nombre": str, "contenido": bytes}
    Devuelve el expediente en bytes.
    """
    escritor = PdfWriter()

    # 1 y 2. Cotización original + acta firmada (ya vienen juntas)
    for pagina in PdfReader(io.BytesIO(pdf_firmado)).pages:
        escritor.add_page(pagina)

    if not respaldos:
        salida = io.BytesIO()
        escritor.write(salida)
        return salida.getvalue()

    fecha = datetime.now(ZONA)

    # 3. Hoja separadora
    hoja = _hoja_separadora(cotizacion, respaldos, fecha)
    for pagina in PdfReader(io.BytesIO(hoja)).pages:
        escritor.add_page(pagina)

    # 4. Cada respaldo
    for r in respaldos:
        nombre, contenido = r["nombre"], r["contenido"]
        try:
            if es_pdf(nombre):
                for pagina in PdfReader(io.BytesIO(contenido)).pages:
                    escritor.add_page(pagina)
            elif es_imagen(nombre):
                pagina_img = _pagina_de_imagen(contenido, nombre)
                for pagina in PdfReader(io.BytesIO(pagina_img)).pages:
                    escritor.add_page(pagina)
        except Exception:
            # Un archivo dañado no debe tumbar el expediente completo:
            # se anota y se sigue con los demás.
            aviso = _pagina_aviso(nombre)
            for pagina in PdfReader(io.BytesIO(aviso)).pages:
                escritor.add_page(pagina)

    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def _pagina_aviso(nombre: str) -> bytes:
    """Página que avisa que un respaldo no se pudo anexar."""
    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=letter)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColorRGB(*AZUL)
    c.drawCentredString(ANCHO / 2, ALTO / 2 + 0.2 * inch,
                        "Respaldo no anexado")
    c.setFont("Helvetica", 10)
    c.setFillGray(0.35)
    c.drawCentredString(ANCHO / 2, ALTO / 2 - 0.1 * inch, nombre)
    c.drawCentredString(ANCHO / 2, ALTO / 2 - 0.35 * inch,
                        "El archivo no se pudo leer. Descárgalo por separado desde la app.")
    c.showPage()
    c.save()
    return buffer.getvalue()
