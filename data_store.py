"""
data_store.py
=============
Capa de acceso a datos: todo lo que habla con Supabase vive aquí.

Paso 9: respaldos de ejecución (reportes y fotos) y rol administrativo.
"""

import mimetypes
import re
import uuid
from datetime import datetime, timezone

import bcrypt
import streamlit as st
from supabase import create_client, Client

BUCKET = "cotizaciones"          # público: PDFs y respaldos
BUCKET_FIRMAS = "firmas"         # privado: imágenes de firma
TABLA = "cotizaciones"
TABLA_FIRMAS = "firmas_usuarios"
TABLA_USUARIOS = "usuarios"
TABLA_RESPALDOS = "respaldos"

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

# jefe          -> sube cotizaciones y marca ejecutado
# junta         -> aprueba y firma
# administrativo-> ve lo firmado/ejecutado y baja archivos (solo lectura)
# admin         -> todo, más la gestión de usuarios
ROLES = ["jefe", "junta", "administrativo", "admin"]

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
# Contraseñas
# ---------------------------------------------------------------------------
def cifrar_password(texto: str) -> str:
    return bcrypt.hashpw(texto.encode(), bcrypt.gensalt()).decode()


def password_correcta(texto: str, cifrada: str) -> bool:
    try:
        return bcrypt.checkpw(texto.encode(), cifrada.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def cargar_usuarios_para_login() -> dict:
    """Credenciales para streamlit-authenticator. Solo usuarios ACTIVOS."""
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
            "password": u["password_hash"],
            "roles": list(u.get("roles") or []),
        }
    return credenciales


def listar_usuarios():
    cliente = conectar()
    if cliente is None:
        return []
    return cliente.table(TABLA_USUARIOS).select("*").order("usuario").execute().data or []


def obtener_usuario(usuario: str):
    cliente = conectar()
    if cliente is None:
        return None
    r = cliente.table(TABLA_USUARIOS).select("*").eq("usuario", usuario).execute()
    return r.data[0] if r.data else None


def crear_usuario(usuario, nombre, apellido, email, password, roles, sede=None):
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
    cliente.table(TABLA_USUARIOS).update(
        {"password_hash": cifrar_password(nueva)}
    ).eq("usuario", usuario).execute()


def activar_usuario(usuario: str, activo: bool) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    cliente.table(TABLA_USUARIOS).update({"activo": activo}).eq("usuario", usuario).execute()


def usuario_tiene_historial(usuario: str) -> bool:
    """
    ¿Esta persona ya dejó rastro en el sistema?

    Si subió, aprobó o ejecutó algo, NO se debe borrar: el historial
    quedaría apuntando a un usuario inexistente. En ese caso se desactiva.
    """
    cliente = conectar()
    if cliente is None:
        return True   # ante la duda, proteger

    for campo in ("subido_por", "aprobado_por", "ejecutado_por"):
        r = cliente.table(TABLA).select("id").eq(campo, usuario).limit(1).execute()
        if r.data:
            return True

    r = cliente.table(TABLA_RESPALDOS).select("id").eq("subido_por", usuario).limit(1).execute()
    return bool(r.data)


def contar_admins_activos() -> int:
    cliente = conectar()
    if cliente is None:
        return 0
    r = cliente.table(TABLA_USUARIOS).select("usuario, roles").eq("activo", True).execute()
    return sum(1 for u in (r.data or []) if "admin" in (u.get("roles") or []))


def eliminar_usuario(usuario: str) -> None:
    """
    Borra un usuario que nunca actuó. Se lleva también su firma, si tenía.
    Quien llama debe validar antes con usuario_tiene_historial().
    """
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    registro = obtener_registro_firma(usuario)
    if registro:
        try:
            cliente.storage.from_(BUCKET_FIRMAS).remove([registro["ruta_firma"]])
        except Exception:
            pass   # si el archivo ya no está, seguimos igual
        cliente.table(TABLA_FIRMAS).delete().eq("usuario", usuario).execute()

    cliente.table(TABLA_USUARIOS).delete().eq("usuario", usuario).execute()


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------
def _ruta_desde_url(url: str) -> str:
    """.../public/cotizaciones/originales/abc.pdf -> originales/abc.pdf"""
    return url.split("?")[0].split(f"/{BUCKET}/", 1)[-1]


def _nombre_seguro(nombre: str) -> str:
    """Quita acentos, espacios y símbolos raros del nombre de archivo."""
    limpio = re.sub(r"[^A-Za-z0-9._-]", "_", nombre)
    return limpio[:80] or "archivo"


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
    """Baja cualquier archivo del bucket público a partir de su URL."""
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    return cliente.storage.from_(BUCKET).download(_ruta_desde_url(url))


# Mismo comportamiento, nombre más claro cuando no es un PDF
descargar_archivo = descargar_pdf


def subir_pdf_firmado(contenido: bytes, numero_odc: str) -> str:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    nombre = f"firmados/{_nombre_seguro(numero_odc)}_{uuid.uuid4().hex[:8]}.pdf"
    cliente.storage.from_(BUCKET).upload(
        nombre, contenido, {"content-type": "application/pdf"}
    )
    return cliente.storage.from_(BUCKET).get_public_url(nombre)


def subir_expediente(contenido: bytes, numero_odc: str) -> str:
    """Sube el PDF completo de la orden (cotización + acta + respaldos)."""
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    nombre = f"expedientes/{_nombre_seguro(numero_odc)}_{uuid.uuid4().hex[:8]}.pdf"
    cliente.storage.from_(BUCKET).upload(
        nombre, contenido, {"content-type": "application/pdf"}
    )
    return cliente.storage.from_(BUCKET).get_public_url(nombre)


def guardar_expediente(id_cot: str, url: str) -> None:
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    cliente.table(TABLA).update({"pdf_expediente_url": url}).eq("id", id_cot).execute()


# ---------------------------------------------------------------------------
# Respaldos de ejecución (reportes, fotos)
# ---------------------------------------------------------------------------
def subir_respaldo(cotizacion_id: str, archivo, usuario: str) -> str:
    """Sube un archivo de respaldo y lo registra contra su cotización."""
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")

    limpio = _nombre_seguro(archivo.name)
    ruta = f"respaldos/{cotizacion_id}/{uuid.uuid4().hex[:8]}_{limpio}"
    tipo = (
        getattr(archivo, "type", None)
        or mimetypes.guess_type(archivo.name)[0]
        or "application/octet-stream"
    )

    cliente.storage.from_(BUCKET).upload(ruta, archivo.getvalue(), {"content-type": tipo})
    url = cliente.storage.from_(BUCKET).get_public_url(ruta)

    cliente.table(TABLA_RESPALDOS).insert({
        "cotizacion_id": cotizacion_id,
        "nombre_archivo": archivo.name,
        "url": url,
        "subido_por": usuario,
    }).execute()
    return url


def listar_respaldos(cotizacion_id: str):
    cliente = conectar()
    if cliente is None:
        return []
    r = (cliente.table(TABLA_RESPALDOS).select("*")
         .eq("cotizacion_id", cotizacion_id)
         .order("fecha_subida").execute())
    return r.data or []


def contar_respaldos() -> dict:
    """{cotizacion_id: cuántos respaldos tiene}. Una sola consulta."""
    cliente = conectar()
    if cliente is None:
        return {}
    r = cliente.table(TABLA_RESPALDOS).select("cotizacion_id").execute()
    cuentas = {}
    for fila in (r.data or []):
        cuentas[fila["cotizacion_id"]] = cuentas.get(fila["cotizacion_id"], 0) + 1
    return cuentas


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


def listar_cotizaciones(sede=None, subido_por=None, estatus=None, estatus_en=None):
    """
    Trae cotizaciones con filtros opcionales.
      estatus     -> un estatus exacto
      estatus_en  -> lista de estatus (ej. las firmadas y ejecutadas)
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
    if estatus_en:
        consulta = consulta.in_("estatus", estatus_en)

    return consulta.order("fecha_subida", desc=True).execute().data or []


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
    return bool(cliente.table(TABLA).select("id").eq("numero_odc", numero).execute().data)


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


def marcar_ejecutado(id_cot: str, usuario: str, nota: str = None) -> None:
    """Cierra el ciclo: el trabajo se realizó."""
    cliente = conectar()
    if cliente is None:
        raise RuntimeError("Sin conexión a Supabase.")
    cliente.table(TABLA).update({
        "estatus": "ejecutado",
        "ejecutado_por": usuario,
        "fecha_ejecucion": ahora_iso(),
        "nota_ejecucion": nota or None,
    }).eq("id", id_cot).execute()


# ---------------------------------------------------------------------------
# Utilidad
# ---------------------------------------------------------------------------
def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
