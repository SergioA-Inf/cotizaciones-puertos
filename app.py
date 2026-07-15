"""
App de Cotizaciones - Terminales de Cruceros (Panamá y Colón)
=============================================================
PASO 7: los usuarios ahora viven en Supabase.

Novedades:
  - Login contra la tabla `usuarios` (ya no contra los Secrets).
  - Cada quien puede cambiar su propia contraseña.
  - El administrador da de alta jefes desde la app, sin tocar código.
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
# 1. Login (credenciales desde Supabase)
# ---------------------------------------------------------------------------
credenciales = ds.cargar_usuarios_para_login()

if not credenciales["usernames"]:
    st.error(
        "No se pudieron cargar los usuarios desde la base de datos. "
        "Revisa la conexión con Supabase."
    )
    st.stop()

authenticator = stauth.Authenticate(
    credenciales,
    st.secrets["auth_cookie"]["name"],
    st.secrets["auth_cookie"]["key"],
    st.secrets["auth_cookie"]["expiry_days"],
)


# ---------------------------------------------------------------------------
# 2. Cambiar mi contraseña
# ---------------------------------------------------------------------------
def cambiar_mi_password(usuario: str):
    with st.expander("🔑 Cambiar mi contraseña"):
        actual = st.text_input("Contraseña actual", type="password", key="pw_actual")
        nueva = st.text_input("Contraseña nueva", type="password", key="pw_nueva")
        repetir = st.text_input("Repite la nueva", type="password", key="pw_rep")

        if st.button("Guardar contraseña nueva", key="btn_pw"):
            registro = ds.obtener_usuario(usuario)
            if registro is None:
                st.error("No se encontró tu usuario.")
                return
            if not ds.password_correcta(actual, registro["password_hash"]):
                st.error("La contraseña actual no es correcta.")
                return
            if len(nueva) < 8:
                st.error("La contraseña nueva debe tener al menos 8 caracteres.")
                return
            if nueva != repetir:
                st.error("Las dos contraseñas nuevas no coinciden.")
                return
            try:
                ds.cambiar_password(usuario, nueva)
                st.success(
                    "✅ Contraseña actualizada. Se usará la próxima vez que inicies sesión."
                )
            except Exception as e:
                st.error("No se pudo cambiar la contraseña.")
                st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 3. Administración de usuarios (solo admin)
# ---------------------------------------------------------------------------
def panel_usuarios():
    st.subheader("👥 Usuarios del sistema")

    # expanded=True a propósito: si se cierra al enviar, los mensajes de
    # error quedan escondidos adentro y el usuario cree que no pasó nada.
    with st.expander("➕ Crear usuario nuevo", expanded=True):
        with st.form("form_usuario", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                nuevo_usuario = st.text_input(
                    "Usuario *",
                    placeholder="ej: joperaciones",
                    help="Sin espacios, tildes ni ñ. Es solo para iniciar sesión; "
                         "el nombre completo va en el campo Nombre.",
                )
                nombre = st.text_input("Nombre *")
                apellido = st.text_input("Apellido")
            with c2:
                email = st.text_input("Correo")
                rol = st.selectbox("Rol *", ds.ROLES, index=0)
                sede = st.selectbox("Sede (informativo)", ["—"] + ds.SEDES)

            password = st.text_input(
                "Contraseña temporal *",
                help="La persona podrá cambiarla al entrar.",
            )
            crear = st.form_submit_button("Crear usuario", type="primary")

        if crear:
            u = nuevo_usuario.strip().lower()
            if not u or not nombre.strip() or not password:
                st.error("Usuario, nombre y contraseña temporal son obligatorios.")
            elif " " in u:
                st.error("El usuario no puede llevar espacios.")
            elif len(password) < 8:
                st.error("La contraseña temporal debe tener al menos 8 caracteres.")
            elif ds.obtener_usuario(u):
                st.error(f"El usuario «{u}» ya existe.")
            else:
                try:
                    ds.crear_usuario(
                        u, nombre.strip(), apellido.strip(), email.strip(),
                        password, [rol], None if sede == "—" else sede,
                    )
                    st.success(f"✅ Usuario «{u}» creado con rol {rol}.")
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo crear el usuario.")
                    st.caption(f"Detalle técnico: {e}")

    # --- Lista de usuarios -------------------------------------------------
    usuarios = ds.listar_usuarios()
    if not usuarios:
        st.info("No hay usuarios.")
        return

    df = pd.DataFrame(usuarios)
    df["Rol"] = df["roles"].apply(lambda r: ", ".join(r or []))
    vista = df[["usuario", "nombre", "apellido", "email", "Rol", "sede", "activo"]].rename(
        columns={
            "usuario": "Usuario", "nombre": "Nombre", "apellido": "Apellido",
            "email": "Correo", "sede": "Sede", "activo": "Activo",
        }
    )
    st.dataframe(vista, hide_index=True, use_container_width=True)

    # --- Activar / desactivar ---------------------------------------------
    st.markdown("##### Activar o desactivar acceso")
    st.caption(
        "Desactivar impide el ingreso, pero conserva el historial de la persona. "
        "Es lo correcto cuando alguien deja la empresa."
    )
    c1, c2 = st.columns([2, 1])
    with c1:
        objetivo = st.selectbox("Usuario", [u["usuario"] for u in usuarios])
    with c2:
        registro = next(u for u in usuarios if u["usuario"] == objetivo)
        nuevo_estado = not registro["activo"]
        etiqueta = "Activar" if nuevo_estado else "Desactivar"
        if st.button(f"{etiqueta} «{objetivo}»", use_container_width=True):
            try:
                ds.activar_usuario(objetivo, nuevo_estado)
                st.success(f"Usuario «{objetivo}» {etiqueta.lower()}do.")
                st.rerun()
            except Exception as e:
                st.error("No se pudo cambiar el estado.")
                st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 4. Panel del Jefe
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
# 5. Registro de firma
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
# 6. Procesos por lote
# ---------------------------------------------------------------------------
def procesar_aprobacion(ids, registro, usuario):
    barra = st.progress(0.0, text="Preparando...")
    firma = ds.descargar_firma(registro["ruta_firma"])
    ok, errores = [], []

    for i, id_cot in enumerate(ids, start=1):
        cot = ds.obtener_cotizacion(id_cot)
        etiqueta = cot["numero_odc"] if cot else id_cot
        barra.progress(i / len(ids), text=f"Firmando {etiqueta} ({i} de {len(ids)})...")
        try:
            original = ds.descargar_pdf(cot["pdf_original_url"])
            firmado = pdf_utils.generar_pdf_firmado(
                original, cot, firma, registro["nombre_completo"]
            )
            url = ds.subir_pdf_firmado(firmado, cot["numero_odc"])
            ds.aprobar_cotizacion(cot["id"], usuario, url)
            ok.append(etiqueta)
        except Exception as e:
            errores.append((etiqueta, str(e)))

    barra.empty()
    return ok, errores


def procesar_rechazo(ids, usuario, motivo):
    ok, errores = [], []
    for id_cot in ids:
        cot = ds.obtener_cotizacion(id_cot)
        etiqueta = cot["numero_odc"] if cot else id_cot
        try:
            ds.rechazar_cotizacion(id_cot, usuario, motivo)
            ok.append(etiqueta)
        except Exception as e:
            errores.append((etiqueta, str(e)))
    return ok, errores


# ---------------------------------------------------------------------------
# 7. Panel de la Junta
# ---------------------------------------------------------------------------
def panel_junta(usuario: str, nombre: str):
    st.subheader("🏛️ Panel de la Junta Directiva")

    registro = ds.obtener_registro_firma(usuario)
    registrar_firma(usuario, nombre, ya_tiene=registro is not None)

    if registro is None:
        st.info("Registra tu firma arriba para habilitar la aprobación.")
        return

    st.divider()

    if st.session_state.get("confirmar_aprobar"):
        pantalla_confirmacion(registro, usuario)
        return

    sede_filtro = st.radio("Sede", ["Todas"] + ds.SEDES, horizontal=True, key="sede_junta")
    sede = None if sede_filtro == "Todas" else sede_filtro

    pendientes = ds.listar_cotizaciones(sede=sede, estatus="por_aprobar")

    total_monto = sum(float(c["monto"]) for c in pendientes)
    m1, m2, m3 = st.columns(3)
    m1.metric("Pendientes de aprobación", len(pendientes))
    m2.metric("Monto total por aprobar", f"US$ {total_monto:,.2f}")
    m3.metric("Sede", sede_filtro)

    if not pendientes:
        st.success("No hay cotizaciones pendientes. 🎉")
        return

    st.markdown("#### Selecciona las cotizaciones a firmar")
    st.caption(
        "Marca la casilla de cada cotización. Puedes abrir el PDF antes de decidir. "
        "Al final, un solo botón las firma todas."
    )

    df = pd.DataFrame(pendientes)
    df["Aprobar"] = False

    vista = df[[
        "Aprobar", "numero_odc", "fecha_cotizacion", "sede", "area",
        "proveedor", "descripcion", "monto", "pdf_original_url", "id",
    ]].rename(columns={
        "numero_odc": "N° OdC", "fecha_cotizacion": "Fecha", "sede": "Sede",
        "area": "Área", "proveedor": "Proveedor", "descripcion": "Descripción",
        "monto": "Monto (USD)", "pdf_original_url": "PDF",
    })

    editada = st.data_editor(
        vista,
        hide_index=True,
        use_container_width=True,
        column_order=[
            "Aprobar", "N° OdC", "Fecha", "Sede", "Área",
            "Proveedor", "Descripción", "Monto (USD)", "PDF",
        ],
        column_config={
            "Aprobar": st.column_config.CheckboxColumn("☑", width="small"),
            "Monto (USD)": st.column_config.NumberColumn(format="$ %.2f"),
            "PDF": st.column_config.LinkColumn(display_text="Abrir"),
            "Descripción": st.column_config.TextColumn(width="medium"),
        },
        disabled=[
            "N° OdC", "Fecha", "Sede", "Área",
            "Proveedor", "Descripción", "Monto (USD)", "PDF",
        ],
        key="editor_junta",
    )

    seleccionadas = editada[editada["Aprobar"] == True]  # noqa: E712
    ids = seleccionadas["id"].tolist()
    monto_sel = float(seleccionadas["Monto (USD)"].sum()) if ids else 0.0

    st.markdown(f"**Seleccionadas: {len(ids)}**  ·  Monto: **US$ {monto_sel:,.2f}**")

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button(
            f"✅ Firmar y aprobar ({len(ids)})",
            type="primary", disabled=not ids, use_container_width=True,
        ):
            st.session_state["confirmar_aprobar"] = ids
            st.session_state["confirmar_monto"] = monto_sel
            st.rerun()

    with c2:
        with st.expander("❌ Rechazar las seleccionadas"):
            motivo = st.text_input("Motivo del rechazo (se aplica a todas)")
            if st.button("Rechazar", disabled=not ids):
                if not motivo.strip():
                    st.error("Escribe el motivo del rechazo.")
                else:
                    ok, errores = procesar_rechazo(ids, usuario, motivo.strip())
                    if ok:
                        st.warning(f"Rechazadas: {', '.join(ok)}")
                    for etiqueta, err in errores:
                        st.error(f"{etiqueta}: {err}")
                    st.rerun()


def pantalla_confirmacion(registro, usuario):
    ids = st.session_state["confirmar_aprobar"]
    monto = st.session_state.get("confirmar_monto", 0.0)

    st.warning(
        f"### ⚠️ Confirmar firma\n\n"
        f"Vas a **aprobar y firmar {len(ids)} cotización(es)** "
        f"por un total de **US$ {monto:,.2f}**.\n\n"
        f"Cada una recibirá tu firma y el acta de aprobación. "
        f"Esta acción no se deshace desde la app."
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Sí, firmar todas", type="primary", use_container_width=True):
            ok, errores = procesar_aprobacion(ids, registro, usuario)
            st.session_state.pop("confirmar_aprobar", None)
            st.session_state.pop("confirmar_monto", None)
            if ok:
                st.success(f"✅ Firmadas y aprobadas: {', '.join(ok)}")
            for etiqueta, err in errores:
                st.error(f"No se pudo firmar {etiqueta}.")
                st.caption(f"Detalle técnico: {err}")
            if not errores:
                st.balloons()
            st.button("Volver al panel")
    with c2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state.pop("confirmar_aprobar", None)
            st.session_state.pop("confirmar_monto", None)
            st.rerun()


# ---------------------------------------------------------------------------
# 8. Tabla general
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
        "numero_odc": "N° OdC", "fecha_cotizacion": "Fecha", "sede": "Sede",
        "area": "Área", "proveedor": "Proveedor", "monto": "Monto (USD)",
        "Estatus": "Estatus", "pdf_original_url": "PDF original",
        "pdf_firmado_url": "PDF firmado",
    }
    vista = df[list(columnas.keys())].rename(columns=columnas)

    st.dataframe(
        vista, use_container_width=True, hide_index=True,
        column_config={
            "Monto (USD)": st.column_config.NumberColumn(format="$ %.2f"),
            "PDF original": st.column_config.LinkColumn(display_text="Abrir"),
            "PDF firmado": st.column_config.LinkColumn(display_text="Descargar"),
        },
    )
    st.caption(f"Total: {len(vista)} cotización(es).")


# ---------------------------------------------------------------------------
# 9. Pantalla principal
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
        st.divider()
        cambiar_mi_password(usuario)

    es_admin = "admin" in roles
    es_junta = "junta" in roles

    if es_junta:
        panel_junta(usuario, nombre)
        st.divider()
        tabla_cotizaciones(usuario, ver_todo=True)
    elif es_admin or "jefe" in roles:
        if es_admin:
            pestañas = st.tabs(["📋 Cotizaciones", "👥 Usuarios"])
            with pestañas[0]:
                panel_jefe(usuario)
                st.divider()
                tabla_cotizaciones(usuario, ver_todo=True)
            with pestañas[1]:
                panel_usuarios()
        else:
            panel_jefe(usuario)
            st.divider()
            tabla_cotizaciones(usuario, ver_todo=False)
    else:
        st.warning("Tu usuario no tiene un rol asignado. Avisa al administrador.")
