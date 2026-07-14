"""
App de Cotizaciones - Terminales de Cruceros (Panamá y Colón)
=============================================================
PASO 4: login + panel del Jefe (formulario y subida de PDF).

El panel de la Junta llega en el Paso 5.
"""

from datetime import date

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth

import data_store as ds

st.set_page_config(page_title="Cotizaciones Puertos", page_icon="📋", layout="wide")


# ---------------------------------------------------------------------------
# 1. Credenciales desde los Secrets de Streamlit
# ---------------------------------------------------------------------------
def cargar_credenciales():
    credenciales = {"usernames": {}}
    for usuario, datos in st.secrets["credentials"].items():
        credenciales["usernames"][usuario] = {
            "first_name": datos.get("first_name", ""),
            "last_name": datos.get("last_name", ""),
            "email": datos.get("email", ""),
            "password": datos["password"],
            "roles": list(datos.get("roles", [])),
        }
    return credenciales


authenticator = stauth.Authenticate(
    cargar_credenciales(),
    st.secrets["auth_cookie"]["name"],
    st.secrets["auth_cookie"]["key"],
    st.secrets["auth_cookie"]["expiry_days"],
)


# ---------------------------------------------------------------------------
# 2. Panel del Jefe: formulario + subida de PDF
# ---------------------------------------------------------------------------
def panel_jefe(usuario: str, nombre: str):
    st.subheader("➕ Nueva cotización")

    with st.form("form_cotizacion", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            numero_odc = st.text_input("N° de OdC *", placeholder="Ej: RB-0069")
            sede = st.selectbox("Sede *", ds.SEDES)
            area = st.selectbox("Área *", ds.AREAS)
            fecha_cotizacion = st.date_input("Fecha de la cotización *", value=date.today())

        with col2:
            proveedor = st.text_input("Proveedor *")
            monto = st.number_input("Monto (USD) *", min_value=0.0, step=100.0, format="%.2f")
            descripcion = st.text_area("Descripción / concepto *", height=100)
            observaciones = st.text_area("Observaciones (opcional)", height=68)

        archivo = st.file_uploader("PDF de la cotización *", type=["pdf"])

        enviado = st.form_submit_button("Guardar cotización", type="primary")

    if not enviado:
        return

    # --- Validaciones antes de guardar ------------------------------------
    faltantes = []
    if not numero_odc.strip():
        faltantes.append("N° de OdC")
    if not proveedor.strip():
        faltantes.append("Proveedor")
    if not descripcion.strip():
        faltantes.append("Descripción")
    if monto <= 0:
        faltantes.append("Monto (debe ser mayor a 0)")
    if archivo is None:
        faltantes.append("PDF de la cotización")

    if faltantes:
        st.error("Faltan datos obligatorios: " + ", ".join(faltantes))
        return

    if ds.numero_odc_existe(numero_odc.strip()):
        st.error(f"El N° de OdC «{numero_odc.strip()}» ya existe. Verifica el número.")
        return

    # --- Guardar -----------------------------------------------------------
    try:
        with st.spinner("Subiendo el PDF..."):
            url_pdf = ds.subir_pdf(archivo)

        with st.spinner("Guardando la cotización..."):
            ds.crear_cotizacion({
                "numero_odc": numero_odc.strip(),
                "fecha_cotizacion": fecha_cotizacion.isoformat(),
                "sede": sede,
                "area": area,
                "proveedor": proveedor.strip(),
                "descripcion": descripcion.strip(),
                "monto": float(monto),
                "observaciones": observaciones.strip() or None,
                "estatus": "por_aprobar",
                "pdf_original_url": url_pdf,
                "subido_por": usuario,
            })

        st.success(f"✅ Cotización {numero_odc.strip()} guardada y enviada a la Junta.")
        st.balloons()

    except Exception as e:
        st.error("No se pudo guardar la cotización.")
        st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 3. Tabla de cotizaciones ya cargadas
# ---------------------------------------------------------------------------
def tabla_cotizaciones(usuario: str, es_admin: bool):
    st.subheader("📄 Mis cotizaciones" if not es_admin else "📄 Todas las cotizaciones")

    filas = ds.listar_cotizaciones(subido_por=None if es_admin else usuario)

    if not filas:
        st.info("Todavía no hay cotizaciones registradas.")
        return

    df = pd.DataFrame(filas)
    df["Estatus"] = df["estatus"].map(ds.ETIQUETA_ESTATUS).fillna(df["estatus"])

    columnas = {
        "numero_odc": "N° OdC",
        "fecha_cotizacion": "Fecha",
        "sede": "Sede",
        "area": "Área",
        "proveedor": "Proveedor",
        "descripcion": "Descripción",
        "monto": "Monto (USD)",
        "Estatus": "Estatus",
        "pdf_original_url": "PDF",
    }
    vista = df[list(columnas.keys())].rename(columns=columnas)

    st.dataframe(
        vista,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Monto (USD)": st.column_config.NumberColumn(format="$ %.2f"),
            "PDF": st.column_config.LinkColumn("PDF", display_text="Abrir"),
        },
    )
    st.caption(f"Total: {len(vista)} cotización(es).")


# ---------------------------------------------------------------------------
# 4. Pantalla principal
# ---------------------------------------------------------------------------
st.title("📋 Cotizaciones · Terminales de Cruceros")

try:
    authenticator.login(location="main")
except Exception as e:
    st.error(f"Error en el login: {e}")

estado = st.session_state.get("authentication_status")

if estado is False:
    st.error("Usuario o contraseña incorrectos.")
elif estado is None:
    st.info("Ingresa tu usuario y contraseña para continuar.")
elif estado:
    nombre = st.session_state.get("name", "")
    usuario = st.session_state.get("username", "")
    roles = st.session_state.get("roles", []) or []

    with st.sidebar:
        st.write(f"**Sesión:** {nombre}")
        st.caption(f"Usuario: {usuario}")
        st.caption(f"Rol: {', '.join(roles) if roles else '—'}")
        authenticator.logout("Cerrar sesión", location="sidebar")

    es_admin = "admin" in roles

    if es_admin or "jefe" in roles:
        panel_jefe(usuario, nombre)
        st.divider()
        tabla_cotizaciones(usuario, es_admin)

    elif "junta" in roles:
        st.subheader("Panel de la Junta Directiva")
        st.info("El panel de aprobación se construye en el próximo paso.")
        st.divider()
        tabla_cotizaciones(usuario, es_admin=True)

    else:
        st.warning("Tu usuario no tiene un rol asignado. Avisa al administrador.")
