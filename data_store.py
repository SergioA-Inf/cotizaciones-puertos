"""
data_store.py
=============
Capa de acceso a datos: todo lo que habla con Supabase vive aquí.

¿Por qué un archivo aparte? Para que app.py se dedique SOLO a la pantalla
(lo que ve el usuario) y este archivo se dedique SOLO a los datos.
Si mañana cambia algo de la base de datos, se toca aquí y en ningún otro lado.
"""

import uuid
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client, Client

BUCKET = "cotizaciones"
TABLA = "cotizaciones"

# --- Listas fijas del formulario (menús desplegables) ----------------------
SEDES = ["Panamá", "Colón"]

AREAS = [
    "Mantenimiento",
    "Operaciones",
    "Administración",
    "Seguridad",
    "IT / Tecnología",
    "Limpieza",
    "Recursos Humanos",
    "Reservas",
]

# Etiquetas para mostrar los estatus en pantalla
ETIQUETA_ESTATUS = {
    "por_aprobar": "🟡 Por aprobar",
    "aprobado_firmado": "🟢 Aprobado y firmado",
    "ejecutado": "🔵 Ejecutado",
    "rechazada": "🔴 Rechazada",
}


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------
@st.cache_resource
def _crear_cliente() -> Client:
    """Crea la conexión a Supabase una sola vez y la reutiliza."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


def conectar():
    """
    Devuelve el cliente de Supabase, o None si algo falla.

    Nota: el error se reporta AQUÍ y no dentro de la función cacheada,
    porque @st.cache_resource silencia los errores en los reruns
    siguientes (lección aprendida en la app de HVAC).
    """
    try:
        return _crear_cliente()
    except Exception as e:
        st.error("No se pudo conectar a Supabase.")
        st.caption(f"Detalle técnico: {e}")
        return None


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------
def subir_pdf(archivo) -> str:
    """
    Sube el PDF al bucket y devuelve su URL pública.
    El nombre lleva un código único (uuid) para que dos archivos que se
    llamen igual nunca se pisen entre sí.
    """
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    nombre = f"originales/{uuid.uuid4().hex}.pdf"
    contenido = archivo.getvalue()

    cliente.storage.from_(BUCKET).upload(
        nombre,
        contenido,
        {"content-type": "application/pdf"},
    )
    return cliente.storage.from_(BUCKET).get_public_url(nombre)


def crear_cotizacion(datos: dict) -> dict:
    """Inserta una fila nueva en la tabla cotizaciones."""
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    respuesta = cliente.table(TABLA).insert(datos).execute()
    return respuesta.data[0] if respuesta.data else {}


# ---------------------------------------------------------------------------
# Consultar
# ---------------------------------------------------------------------------
def listar_cotizaciones(sede=None, subido_por=None, estatus=None):
    """
    Trae cotizaciones de la base, con filtros opcionales.
    Devuelve una lista (vacía si no hay nada o si falla la conexión).
    """
    cliente = conectar()
    if cliente is None:
        return []

    consulta = cliente.table(TABLA).select("*")

    if sede:
        consulta = consulta.eq("sede", sede)
    if subido_por:
        consulta = consulta.eq("subido_por", subido_por)
    if estatus:
        consulta = consulta.eq("estatus", estatus)

    respuesta = consulta.order("fecha_subida", desc=True).execute()
    return respuesta.data or []


def numero_odc_existe(numero: str) -> bool:
    """Revisa si un N° de OdC ya fue usado, para evitar duplicados."""
    cliente = conectar()
    if cliente is None or not numero:
        return False

    respuesta = cliente.table(TABLA).select("id").eq("numero_odc", numero).execute()
    return bool(respuesta.data)


# ---------------------------------------------------------------------------
# Utilidad
# ---------------------------------------------------------------------------
def ahora_iso() -> str:
    """Fecha y hora actual en el formato que entiende la base de datos."""
    return datetime.now(timezone.utc).isoformat()
