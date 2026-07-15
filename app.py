"""
App de Cotizaciones - Terminales de Cruceros (Panamá y Colón)
=============================================================
PASO 5: login + panel del Jefe + panel de la Junta (firma y aprobación).
"""

import io
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from PIL import Image
from streamlit_drawable_canvas import st_canvas

import data_store as ds
import pdf_utils

st.set_page_config(page_title="Cotizaciones Puertos", page_icon="📋", layout="wide")


# ---------------------------------------------------------------------------
# 1. Credenciales desde los Secrets
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
# 2. Panel del Jefe
# ---------------------------------------------------------------------------
def panel_jefe(usuario: str):
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

    faltantes = []
    if not numero_odc.strip():
        faltantes.append("N° de OdC")
    if not proveedor.strip():
        faltantes.append("Proveedor")
    if not descripcion.strip():
        faltantes.append("Descripción")
    if monto <= 0:
        faltantes.append("Monto (mayor a 0)")
    if archivo is None:
        faltantes.append("PDF de la cotización")

    if faltantes:
        st.error("Faltan datos obligatorios: " + ", ".join(faltantes))
        return

    if ds.numero_odc_existe(numero_odc.strip()):
        st.error(f"El N° de OdC «{numero_odc.strip()}» ya existe.")
        return

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
        st.success(f"✅ Cotización {numero_odc.strip()} enviada a la Junta.")
        st.balloons()
    except Exception as e:
        st.error("No se pudo guardar la cotización.")
        st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 3. Registro de firma (solo la propia)
# ---------------------------------------------------------------------------
def registrar_firma(usuario: str, nombre: str, ya_tiene: bool):
    titulo = "✍️ Cambiar mi firma" if ya_tiene else "✍️ Registrar mi firma"

    with st.expander(titulo, expanded=not ya_tiene):
        if not ya_tiene:
            st.warning("Necesitas registrar tu firma una sola vez para poder aprobar.")

        st.caption(
            "Dibuja tu firma con el dedo (celular/tablet) o con el mouse. "
            "Si prefieres, puedes subir una foto de tu firma hecha en papel."
        )

        modo = st.radio(
            "¿Cómo quieres registrarla?",
            ["Dibujarla", "Subir una imagen"],
            horizontal=True,
            key="modo_firma",
        )

        imagen_final = None

        if modo == "Dibujarla":
            lienzo = st_canvas(
                fill_color="rgba(0,0,0,0)",
                stroke_width=3,
                stroke_color="#000000",
                background_color="#FFFFFF",
                height=170,
                width=340,
                drawing_mode="freedraw",
                key="lienzo_firma",
            )
            if lienzo.image_data is not None:
                arreglo = np.array(lienzo.image_data, dtype=np.uint8)
                # Si el canal de transparencia está todo en cero, no dibujó nada.
                if arreglo[:, :, 3].max() > 0:
                    img = Image.fromarray(arreglo, "RGBA")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    imagen_final = buf.getvalue()

            st.caption("Usa la papelera 🗑 debajo del recuadro para borrar y repetir.")

        else:
            subida = st.file_uploader(
                "Foto de tu firma (fondo blanco, marcador negro)",
                type=["png", "jpg", "jpeg"],
                key="upload_firma",
            )
            if subida is not None:
                imagen_final = subida.getvalue()
                st.image(imagen_final, width=260, caption="Vista previa")

        if st.button("Guardar mi firma", type="primary", key="btn_guardar_firma"):
            if imagen_final is None:
                st.error("Todavía no hay ninguna firma para guardar.")
                return
            try:
                limpia = pdf_utils.limpiar_firma(imagen_final)
                ds.guardar_firma(usuario, nombre, limpia)
                st.success("✅ Firma registrada. Ya puedes aprobar cotizaciones.")
                st.rerun()
            except Exception as e:
                st.error("No se pudo guardar la firma.")
                st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 4. Panel de la Junta
# ---------------------------------------------------------------------------
def panel_junta(usuario: str, nombre: str):
    st.subheader("🏛️ Panel de la Junta Directiva")

    registro = ds.obtener_registro_firma(usuario)
    registrar_firma(usuario, nombre, ya_tiene=registro is not None)

    if registro is None:
        st.info("Registra tu firma arriba para habilitar la aprobación.")
        return

    st.divider()

    sede_filtro = st.radio(
        "Sede", ["Todas"] + ds.SEDES, horizontal=True, key="sede_junta"
    )
    sede = None if sede_filtro == "Todas" else sede_filtro

    pendientes = ds.listar_cotizaciones(sede=sede, estatus="por_aprobar")

    st.markdown(f"### Pendientes de aprobación ({len(pendientes)})")

    if not pendientes:
        st.success("No hay cotizaciones pendientes. 🎉")
        return

    for cot in pendientes:
        titulo = (
            f"{cot['numero_odc']} · {cot['proveedor']} · "
            f"US$ {float(cot['monto']):,.2f} · {cot['sede']}"
        )
        with st.expander(titulo):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.write(f"**Área:** {cot['area']}")
                st.write(f"**Fecha cotización:** {cot.get('fecha_cotizacion', '—')}")
                st.write(f"**Descripción:** {cot.get('descripcion', '—')}")
                if cot.get("observaciones"):
                    st.write(f"**Observaciones:** {cot['observaciones']}")
                st.write(f"**Subido por:** {cot.get('subido_por', '—')}")
            with c2:
                st.link_button("📄 Ver PDF", cot["pdf_original_url"])

            st.divider()

            b1, b2 = st.columns(2)

            with b1:
                if st.button("✅ Aprobar y firmar", key=f"ap_{cot['id']}", type="primary"):
                    try:
                        with st.spinner("Firmando el documento..."):
                            original = ds.descargar_pdf(cot["pdf_original_url"])
                            firma = ds.descargar_firma(registro["ruta_firma"])
                            firmado = pdf_utils.generar_pdf_firmado(
                                original, cot, firma, registro["nombre_completo"]
                            )
                            url = ds.subir_pdf_firmado(firmado, cot["numero_odc"])
                            ds.aprobar_cotizacion(cot["id"], usuario, url)
                        st.success(f"✅ {cot['numero_odc']} aprobada y firmada.")
                        st.rerun()
                    except Exception as e:
                        st.error("No se pudo aprobar.")
                        st.caption(f"Detalle técnico: {e}")

            with b2:
                motivo = st.text_input("Motivo del rechazo", key=f"mot_{cot['id']}")
                if st.button("❌ Rechazar", key=f"re_{cot['id']}"):
                    if not motivo.strip():
                        st.error("Escribe el motivo del rechazo.")
                    else:
                        try:
                            ds.rechazar_cotizacion(cot["id"], usuario, motivo.strip())
                            st.warning(f"{cot['numero_odc']} rechazada.")
                            st.rerun()
                        except Exception as e:
                            st.error("No se pudo rechazar.")
                            st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 5. Tabla general
# ---------------------------------------------------------------------------
def tabla_cotizaciones(usuario: str, ver_todo: bool):
    st.subheader("📄 Todas las cotizaciones" if ver_todo else "📄 Mis cotizaciones")

    filas = ds.listar_cotizaciones(subido_por=None if ver_todo else usuario)
    if not filas:
        st.info("Todavía no hay cotizaciones registradas.")
        return

    df = pd.DataFrame(filas)
    for col in ["pdf_firmado_url", "observaciones", "motivo_rechazo"]:
        if col not in df.columns:
            df[col] = None

    df["Estatus"] = df["estatus"].map(ds.ETIQUETA_ESTATUS).fillna(df["estatus"])

    columnas = {
        "numero_odc": "N° OdC",
        "fecha_cotizacion": "Fecha",
        "sede": "Sede",
        "area": "Área",
        "proveedor": "Proveedor",
        "monto": "Monto (USD)",
        "Estatus": "Estatus",
        "pdf_original_url": "PDF original",
        "pdf_firmado_url": "PDF firmado",
    }
    vista = df[list(columnas.keys())].rename(columns=columnas)

    st.dataframe(
        vista,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Monto (USD)": st.column_config.NumberColumn(format="$ %.2f"),
            "PDF original": st.column_config.LinkColumn(display_text="Abrir"),
            "PDF firmado": st.column_config.LinkColumn(display_text="Descargar"),
        },
    )
    st.caption(f"Total: {len(vista)} cotización(es).")


# ---------------------------------------------------------------------------
# 6. Pantalla principal
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
    es_junta = "junta" in roles

    if es_junta:
        panel_junta(usuario, nombre)
        st.divider()
        tabla_cotizaciones(usuario, ver_todo=True)

    elif es_admin or "jefe" in roles:
        panel_jefe(usuario)
        st.divider()
        tabla_cotizaciones(usuario, ver_todo=es_admin)

    else:
        st.warning("Tu usuario no tiene un rol asignado. Avisa al administrador.")
