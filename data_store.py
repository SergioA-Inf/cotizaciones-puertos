"""
data_store.py
=============
Capa de acceso a datos: todo lo que habla con Supabase vive aquí.

Desde el Paso 7 los USUARIOS también viven en Supabase (antes estaban en
los Secrets). Las contraseñas se guardan cifradas con bcrypt: ni el
administrador puede leerlas.
"""

import uuid
from datetime import datetime, timezone

import bcrypt
import streamlit as st
from supabase import create_client, Client

BUCKET = "cotizaciones"          # público: PDFs
BUCKET_FIRMAS = "firmas"         # privado: imágenes de firma
TABLA = "cotizaciones"
TABLA_FIRMAS = "firmas_usuarios"
TABLA_USUARIOS = "usuarios"

# --- Listas fijas ---------------------------------------------------------
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

ROLES = ["jefe", "junta", "admin"]

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
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


def conectar():
    """
    Devuelve el cliente de Supabase, o None si algo falla.

    El error se reporta AQUÍ y no dentro de la función cacheada, porque
    @st.cache_resource silencia los errores en los reruns siguientes
    (lección aprendida en la app de HVAC).
    """
    try:
        return _crear_cliente()
    except Exception as e:
        st.error("No se pudo conectar a Supabase.")
        st.caption(f"Detalle técnico: {e}")
        return None


# ---------------------------------------------------------------------------
# Contraseñas (cifrado)
# ---------------------------------------------------------------------------
def cifrar_password(texto: str) -> str:
    """Convierte una contraseña en su versión cifrada (irreversible)."""
    return bcrypt.hashpw(texto.encode(), bcrypt.gensalt()).decode()


def password_correcta(texto: str, cifrada: str) -> bool:
    """Comprueba si una contraseña coincide con su versión cifrada."""
    try:
        return bcrypt.checkpw(texto.encode(), cifrada.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def cargar_usuarios_para_login() -> dict:
    """
    Arma el diccionario de credenciales que necesita streamlit-authenticator.
    Solo incluye usuarios ACTIVOS.
    """
    cliente = conectar()
    if cliente is None:
        return {"usernames": {}}

    r = cliente.table(TABLA_USUARIOS).select("*").eq("activo", True).execute()

    credenciales = {"usernames": {}}
    for u in (r.data or []):
        credenciales["usernames"][u["usuario"]] = {
            "first_name": u.get("nombre", ""),
            "last_name": u.get("apellido", "") or "",
            "email": u.get("email", "") or "",
            "password": u["password_hash"],   # ya viene cifrada
            "roles": list(u.get("roles") or []),
        }
    return credenciales


def listar_usuarios():
    cliente = conectar()
    if cliente is None:
        return []
    r = cliente.table(TABLA_USUARIOS).select("*").order("usuario").execute()
    return r.data or []


def obtener_usuario(usuario: str):
    cliente = conectar()
    if cliente is None:
        return None
    r = cliente.table(TABLA_USUARIOS).select("*").eq("usuario", usuario).execute()
    return r.data[0] if r.data else None


def crear_usuario(usuario, nombre, apellido, email, password, roles, sede=None):
    """Da de alta un usuario nuevo con su contraseña ya cifrada."""
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    cliente.table(TABLA_USUARIOS).insert({
        "usuario": usuario,
        "nombre": nombre,
        "apellido": apellido or None,
        "email": email or None,
        "password_hash": cifrar_password(password),
        "roles": roles,
        "sede": sede,
        "activo": True,
    }).execute()


def cambiar_password(usuario: str, nueva: str) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    cliente.table(TABLA_USUARIOS).update({
        "password_hash": cifrar_password(nueva)
    }).eq("usuario", usuario).execute()


def activar_usuario(usuario: str, activo: bool) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    cliente.table(TABLA_USUARIOS).update({"activo": activo}).eq("usuario", usuario).execute()


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------
def _ruta_desde_url(url: str) -> str:
    """.../public/cotizaciones/originales/abc.pdf -> originales/abc.pdf"""
    limpia = url.split("?")[0]
    return limpia.split(f"/{BUCKET}/", 1)[-1]


def subir_pdf(archivo) -> str:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    nombre = f"originales/{uuid.uuid4().hex}.pdf"
    cliente.storage.from_(BUCKET).upload(
        nombre, archivo.getvalue(), {"content-type": "application/pdf"}
    )
    return cliente.storage.from_(BUCKET).get_public_url(nombre)


def descargar_pdf(url: str) -> bytes:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    return cliente.storage.from_(BUCKET).download(_ruta_desde_url(url))


def subir_pdf_firmado(contenido: bytes, numero_odc: str) -> str:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    nombre = f"firmados/{numero_odc}_{uuid.uuid4().hex[:8]}.pdf"
    cliente.storage.from_(BUCKET).upload(
        nombre, contenido, {"content-type": "application/pdf"}
    )
    return cliente.storage.from_(BUCKET).get_public_url(nombre)


# ---------------------------------------------------------------------------
# Firmas (bucket PRIVADO)
# ---------------------------------------------------------------------------
def guardar_firma(usuario: str, nombre_completo: str, imagen: bytes) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    ruta = f"{usuario}.png"
    cliente.storage.from_(BUCKET_FIRMAS).upload(
        ruta, imagen, {"content-type": "image/png", "upsert": "true"}
    )
    cliente.table(TABLA_FIRMAS).upsert({
        "usuario": usuario,
        "nombre_completo": nombre_completo,
        "ruta_firma": ruta,
        "fecha_registro": ahora_iso(),
    }).execute()


def obtener_registro_firma(usuario: str):
    cliente = conectar()
    if cliente is None:
        return None
    r = cliente.table(TABLA_FIRMAS).select("*").eq("usuario", usuario).execute()
    return r.data[0] if r.data else None


def descargar_firma(ruta: str) -> bytes:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    return cliente.storage.from_(BUCKET_FIRMAS).download(ruta)


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------
def crear_cotizacion(datos: dict) -> dict:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    r = cliente.table(TABLA).insert(datos).execute()
    return r.data[0] if r.data else {}


def listar_cotizaciones(sede=None, subido_por=None, estatus=None):
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

    r = consulta.order("fecha_subida", desc=True).execute()
    return r.data or []


def obtener_cotizacion(id_cot: str):
    cliente = conectar()
    if cliente is None:
        return None
    r = cliente.table(TABLA).select("*").eq("id", id_cot).execute()
    return r.data[0] if r.data else None


def numero_odc_existe(numero: str) -> bool:
    cliente = conectar()
    if cliente is None or not numero:
        return False
    r = cliente.table(TABLA).select("id").eq("numero_odc", numero).execute()
    return bool(r.data)


def aprobar_cotizacion(id_cot: str, usuario: str, url_firmado: str) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    cliente.table(TABLA).update({
        "estatus": "aprobado_firmado",
        "aprobado_por": usuario,
        "fecha_aprobacion": ahora_iso(),
        "pdf_firmado_url": url_firmado,
    }).eq("id", id_cot).execute()


def rechazar_cotizacion(id_cot: str, usuario: str, motivo: str) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    cliente.table(TABLA).update({
        "estatus": "rechazada",
        "aprobado_por": usuario,
        "fecha_aprobacion": ahora_iso(),
        "motivo_rechazo": motivo,
    }).eq("id", id_cot).execute()


# ---------------------------------------------------------------------------
# Utilidad
# ---------------------------------------------------------------------------
def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
