"""
App de Cotizaciones - Terminales de Cruceros (Panamá y Colón)
=============================================================
PASO 9: cierre del ciclo.

  - El jefe marca "ejecutado" y adjunta respaldos (reporte, fotos).
  - Rol administrativo: ve lo firmado/ejecutado y baja los archivos.
  - Cada panel muestra SOLO lo que su rol necesita; el resto va a
    Historial, con filtros. Lo ejecutado se archiva.
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

st.set_page_config(page_title="Cotizaciones · Terminales de Cruceros",
                   page_icon="⚓", layout="wide")


# ---------------------------------------------------------------------------
# 0. Identidad visual
# ---------------------------------------------------------------------------
ESTILOS = """
<style>
  .titulo-app {
    font-size: 1.55rem; font-weight: 700; color: #14264F;
    margin: 0; text-align: center; line-height: 1.15;
  }
  .subtitulo-app {
    font-size: .70rem; color: #5A6B87; letter-spacing: .16em;
    text-transform: uppercase; text-align: center; margin-top: .3rem;
  }
  .regla-marca {
    height: 3px; border: 0; border-radius: 2px; margin: .9rem 0 1.3rem 0;
    background: linear-gradient(90deg, #14264F 0%, #2F5E6B 55%, #61904C 100%);
  }
  [data-testid="stMetric"] {
    background: #F2F5F9; border: 1px solid #E3E9F2;
    border-radius: 12px; padding: 14px 16px;
  }
  [data-testid="stMetricValue"] { color: #14264F; font-weight: 700; }
</style>
"""


def encabezado():
    st.markdown(ESTILOS, unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2.6, 1], vertical_alignment="center")
    with c1:
        ruta = pdf_utils.resolver_logo("Panamá")
        if ruta:
            st.image(ruta, width=95)
    with c2:
        st.markdown(
            '<div class="titulo-app">Cotizaciones</div>'
            '<div class="subtitulo-app">Terminales de cruceros · Panamá y Colón</div>',
            unsafe_allow_html=True,
        )
    with c3:
        ruta = pdf_utils.resolver_logo("Colón")
        if ruta:
            st.image(ruta, width=185)
    st.markdown('<hr class="regla-marca">', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 1. Login
# ---------------------------------------------------------------------------
credenciales = ds.cargar_usuarios_para_login()

if not credenciales["usernames"]:
    encabezado()
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
# 2. Filtros y tabla (se reutilizan en varios paneles)
# ---------------------------------------------------------------------------
def aplicar_filtros(filas, clave: str, estatus_posibles, sedes=None):
    """Dibuja el panel de filtros y devuelve las filas ya filtradas."""
    if not filas:
        return pd.DataFrame()

    df = pd.DataFrame(filas)

    with st.expander("🔎 Filtros", expanded=False):
        c1, c2, c3 = st.columns(3)
        f_sede = c1.multiselect("Sede", sedes or ds.SEDES, key=f"fsede_{clave}")
        f_area = c2.multiselect("Área", ds.AREAS, key=f"farea_{clave}")
        f_estatus = c3.multiselect(
            "Estatus",
            [ds.ETIQUETA_ESTATUS[e] for e in estatus_posibles],
            key=f"fest_{clave}",
        )

        c4, c5 = st.columns([2, 1])
        texto = c4.text_input(
            "Buscar", placeholder="N° OdC, proveedor o descripción",
            key=f"ftxt_{clave}",
        )
        rango = c5.date_input(
            "Fecha de cotización (desde / hasta)", value=(), key=f"ffec_{clave}"
        )

    if f_sede:
        df = df[df["sede"].isin(f_sede)]
    if f_area:
        df = df[df["area"].isin(f_area)]
    if f_estatus:
        claves = [k for k, v in ds.ETIQUETA_ESTATUS.items() if v in f_estatus]
        df = df[df["estatus"].isin(claves)]

    if texto:
        t = texto.lower()
        campos = ["numero_odc", "proveedor", "descripcion"]
        mascara = False
        for campo in campos:
            mascara = mascara | df[campo].fillna("").str.lower().str.contains(t)
        df = df[mascara]

    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        fechas = pd.to_datetime(df["fecha_cotizacion"], errors="coerce").dt.date
        df = df[(fechas >= rango[0]) & (fechas <= rango[1])]

    return df


def mostrar_tabla(df, respaldos=None):
    """Tabla de cotizaciones lista para leer."""
    if df.empty:
        st.info("No hay cotizaciones que coincidan.")
        return

    df = df.copy()
    for col in ["pdf_firmado_url", "pdf_expediente_url", "observaciones", "motivo_rechazo"]:
        if col not in df.columns:
            df[col] = None

    df["Estatus"] = df["estatus"].map(ds.ETIQUETA_ESTATUS).fillna(df["estatus"])
    if respaldos is not None:
        df["Respaldos"] = df["id"].map(lambda i: respaldos.get(i, 0))

    columnas = {
        "numero_odc": "N° OdC", "fecha_cotizacion": "Fecha", "sede": "Sede",
        "area": "Área", "proveedor": "Proveedor", "monto": "Monto (USD)",
        "Estatus": "Estatus", "pdf_original_url": "PDF original",
        "pdf_firmado_url": "PDF firmado",
        "pdf_expediente_url": "Expediente",
    }
    if respaldos is not None:
        columnas["Respaldos"] = "Respaldos"

    vista = df[list(columnas.keys())].rename(columns=columnas)

    st.dataframe(
        vista, use_container_width=True, hide_index=True,
        column_config={
            "Monto (USD)": st.column_config.NumberColumn(format="$ %.2f"),
            "PDF original": st.column_config.LinkColumn(display_text="Abrir"),
            "PDF firmado": st.column_config.LinkColumn(display_text="Descargar"),
            "Expediente": st.column_config.LinkColumn(
                "Expediente", display_text="📎 Completo"
            ),
        },
    )
    total = float(df["monto"].sum())
    st.caption(f"{len(vista)} cotización(es) · Monto total: US$ {total:,.2f}")


def ver_respaldos(df):
    """Selector para consultar los archivos adjuntos de una cotización."""
    if df.empty:
        return

    st.markdown("##### 📎 Respaldos de una orden")
    opciones = {
        f"{f['numero_odc']} · {f['proveedor']}": f["id"]
        for _, f in df.iterrows()
    }
    elegida = st.selectbox("Orden", list(opciones.keys()), key="sel_respaldos")
    archivos = ds.listar_respaldos(opciones[elegida])

    if not archivos:
        st.caption("Esta orden todavía no tiene respaldos adjuntos.")
        return

    for a in archivos:
        st.markdown(f"- [{a['nombre_archivo']}]({a['url']})")


# ---------------------------------------------------------------------------
# 3. Cambiar mi contraseña
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
                st.success("✅ Contraseña actualizada. Se usará en tu próximo ingreso.")
            except Exception as e:
                st.error("No se pudo cambiar la contraseña.")
                st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 4. Usuarios (solo admin)
# ---------------------------------------------------------------------------
def panel_usuarios(usuario_actual: str):
    st.subheader("👥 Usuarios del sistema")

    # expanded=True a propósito: si se cierra al enviar, los mensajes de
    # error quedan escondidos adentro y parece que "no pasó nada".
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
                sedes_nuevo = st.multiselect(
                    "Sedes *", ds.SEDES, default=ds.SEDES,
                    help="A qué terminales tiene acceso. Puede ser una o las dos.",
                )

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
            elif not sedes_nuevo:
                st.error("Debes asignar al menos una sede.")
            elif len(password) < 8:
                st.error("La contraseña temporal debe tener al menos 8 caracteres.")
            elif ds.obtener_usuario(u):
                st.error(f"El usuario «{u}» ya existe.")
            else:
                try:
                    ds.crear_usuario(
                        u, nombre.strip(), apellido.strip(), email.strip(),
                        password, [rol], sedes_nuevo,
                    )
                    st.success(
                        f"✅ Usuario «{u}» creado con rol {rol} · "
                        f"{', '.join(sedes_nuevo)}."
                    )
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo crear el usuario.")
                    st.caption(f"Detalle técnico: {e}")

    usuarios = ds.listar_usuarios()
    if not usuarios:
        st.info("No hay usuarios.")
        return

    df = pd.DataFrame(usuarios)
    df["Rol"] = df["roles"].apply(lambda r: ", ".join(r or []))
    df["Sedes"] = df["sedes"].apply(lambda s: ", ".join(s or []))
    vista = df[["usuario", "nombre", "apellido", "email", "Rol", "Sedes", "activo"]].rename(
        columns={"usuario": "Usuario", "nombre": "Nombre", "apellido": "Apellido",
                 "email": "Correo", "activo": "Activo"}
    )
    st.dataframe(vista, hide_index=True, use_container_width=True)

    # --- Cambiar sedes -----------------------------------------------------
    with st.expander("🏢 Cambiar las sedes de un usuario"):
        quien = st.selectbox(
            "Usuario", [u["usuario"] for u in usuarios], key="sel_sedes"
        )
        actuales = next(u for u in usuarios if u["usuario"] == quien).get("sedes") or []
        nuevas = st.multiselect(
            "Sedes", ds.SEDES,
            default=[s for s in ds.SEDES if s in actuales],
            key="ms_sedes",
        )
        if st.button("Guardar sedes", key="btn_sedes"):
            if not nuevas:
                st.error("Debe tener al menos una sede.")
            else:
                try:
                    ds.actualizar_sedes(quien, nuevas)
                    st.success(f"«{quien}» ahora tiene acceso a: {', '.join(nuevas)}.")
                    st.rerun()
                except Exception as e:
                    st.error("No se pudieron guardar las sedes.")
                    st.caption(f"Detalle técnico: {e}")

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

    # --- Eliminar (solo usuarios que nunca actuaron) -----------------------
    with st.expander("🗑️ Eliminar un usuario"):
        st.caption(
            "Solo se puede borrar a quien nunca subió, aprobó ni ejecutó nada "
            "(por ejemplo, un usuario de prueba). Si ya actuó, su rastro debe "
            "conservarse: usa Desactivar."
        )

        borrar = st.selectbox(
            "Usuario a eliminar",
            [u["usuario"] for u in usuarios],
            key="sel_borrar",
        )

        es_admin_objetivo = "admin" in (
            next(u for u in usuarios if u["usuario"] == borrar).get("roles") or []
        )

        # Tres candados
        if borrar == usuario_actual:
            st.warning("No puedes eliminar tu propio usuario.")
        elif es_admin_objetivo and ds.contar_admins_activos() <= 1:
            st.warning("Es el único administrador activo. Si lo borras, nadie podrá "
                       "gestionar usuarios.")
        elif ds.usuario_tiene_historial(borrar):
            st.info(
                f"«{borrar}» ya tiene actividad registrada, así que no se puede "
                f"eliminar. Desactívalo con el control de arriba: pierde el acceso "
                f"y su historial queda intacto."
            )
        else:
            confirmo = st.checkbox(
                f"Entiendo que eliminar «{borrar}» no se puede deshacer.",
                key="chk_borrar",
            )
            if st.button("Eliminar usuario", disabled=not confirmo):
                try:
                    ds.eliminar_usuario(borrar)
                    st.success(f"Usuario «{borrar}» eliminado.")
                    st.rerun()
                except Exception as e:
                    st.error("No se pudo eliminar el usuario.")
                    st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 5. Nueva cotización
# ---------------------------------------------------------------------------
def formulario_cotizacion(usuario: str, sedes):
    st.subheader("➕ Nueva cotización")

    if not sedes:
        st.warning("Tu usuario no tiene ninguna sede asignada. Avisa al administrador.")
        return

    with st.form("form_cotizacion", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            numero_odc = st.text_input("N° de OdC *", placeholder="Ej: RB-0069")
            sede = st.selectbox("Sede *", sedes)
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
                "sede": sede, "area": area,
                "proveedor": proveedor.strip(),
                "descripcion": descripcion.strip(),
                "monto": float(monto),
                "observaciones": observaciones.strip() or None,
                "estatus": "por_aprobar",
                "pdf_original_url": url_pdf,
                "subido_por": usuario,
            })
        st.success(f"✅ Cotización {numero_odc.strip()} enviada a la Junta.")
        st.toast("Cotización enviada", icon="✅")
    except Exception as e:
        st.error("No se pudo guardar la cotización.")
        st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 6. Marcar ejecutado + respaldos
# ---------------------------------------------------------------------------
def panel_ejecutar(usuario: str, ver_todo: bool, sedes):
    st.subheader("🔧 Registrar trabajo ejecutado")

    firmadas = ds.listar_cotizaciones(
        subido_por=None if ver_todo else usuario,
        estatus="aprobado_firmado",
        sedes_en=sedes,
    )

    if not firmadas:
        st.info("No hay órdenes firmadas pendientes de ejecución.")
        return

    opciones = {
        f"{c['numero_odc']} · {c['proveedor']} · US$ {float(c['monto']):,.2f}": c
        for c in firmadas
    }
    etiqueta = st.selectbox("Orden a cerrar", list(opciones.keys()), key="sel_ejecutar")
    cot = opciones[etiqueta]

    st.caption(
        f"Sede {cot['sede']} · Área {cot['area']} · "
        f"Aprobada por {cot.get('aprobado_por', '—')}"
    )

    nota = st.text_area(
        "Nota de ejecución (opcional)",
        placeholder="Ej: trabajo concluido el 12/07, recibido conforme por el supervisor.",
        key="nota_ejec",
    )
    adjuntos = st.file_uploader(
        "Respaldos: reporte del proveedor, fotos, actas de entrega",
        accept_multiple_files=True,
        type=["pdf", "png", "jpg", "jpeg"],
        key="adj_ejec",
        help="Solo PDF y fotos. Si tienes un Word o Excel, guárdalo como PDF antes "
             "de subirlo para que quede dentro del expediente.",
    )

    if st.button("Marcar como ejecutada", type="primary"):
        try:
            # 1. Guardar cada respaldo (y conservar el contenido en memoria,
            #    así no hay que volver a bajarlo para armar el expediente)
            archivos = []
            if adjuntos:
                barra = st.progress(0.0, text="Subiendo respaldos...")
                for i, archivo in enumerate(adjuntos, start=1):
                    ds.subir_respaldo(cot["id"], archivo, usuario)
                    archivos.append({"nombre": archivo.name,
                                     "contenido": archivo.getvalue()})
                    barra.progress(i / len(adjuntos), text=f"Subiendo {archivo.name}...")
                barra.empty()

            # 2. Cerrar la orden
            ds.marcar_ejecutado(cot["id"], usuario, nota.strip() or None)

            # 3. Armar el expediente: cotización + acta firmada + respaldos
            with st.spinner("Armando el expediente..."):
                datos = {**cot,
                         "ejecutado_por": usuario,
                         "nota_ejecucion": nota.strip() or None}
                firmado = ds.descargar_archivo(cot["pdf_firmado_url"])
                expediente = pdf_utils.generar_expediente(firmado, datos, archivos)
                url = ds.subir_expediente(expediente, cot["numero_odc"])
                ds.guardar_expediente(cot["id"], url)

            st.success(
                f"✅ {cot['numero_odc']} ejecutada. Expediente generado"
                + (f" con {len(archivos)} respaldo(s)." if archivos else ".")
            )
            st.rerun()
        except Exception as e:
            st.error("No se pudo cerrar la orden.")
            st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 7. Registro de firma
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
            "¿Cómo quieres registrarla?", ["Dibujarla", "Subir una imagen"],
            horizontal=True, key="modo_firma",
        )

        imagen_final = None

        if modo == "Dibujarla":
            lienzo = st_canvas(
                fill_color="rgba(0,0,0,0)", stroke_width=3, stroke_color="#000000",
                background_color="#FFFFFF", height=170, width=340,
                drawing_mode="freedraw", key="lienzo_firma",
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
                type=["png", "jpg", "jpeg"], key="upload_firma",
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
# 8. Procesos por lote
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
# 9. Junta: pendientes
# ---------------------------------------------------------------------------
def panel_junta(usuario: str, nombre: str, sedes):
    registro = ds.obtener_registro_firma(usuario)
    registrar_firma(usuario, nombre, ya_tiene=registro is not None)

    if registro is None:
        st.info("Registra tu firma arriba para habilitar la aprobación.")
        return

    if not sedes:
        st.warning("Tu usuario no tiene ninguna sede asignada. Avisa al administrador.")
        return

    if st.session_state.get("confirmar_aprobar"):
        pantalla_confirmacion(registro, usuario)
        return

    # Si solo aprueba una sede, no tiene sentido ofrecerle un filtro
    if len(sedes) == 1:
        sede_filtro = sedes[0]
        st.caption(f"Apruebas cotizaciones de: **{sede_filtro}**")
    else:
        sede_filtro = st.radio(
            "Sede", ["Todas"] + sedes, horizontal=True, key="sede_junta"
        )

    if sede_filtro == "Todas":
        pendientes = ds.listar_cotizaciones(sedes_en=sedes, estatus="por_aprobar")
    else:
        pendientes = ds.listar_cotizaciones(sede=sede_filtro, estatus="por_aprobar")

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
        vista, hide_index=True, use_container_width=True,
        column_order=["Aprobar", "N° OdC", "Fecha", "Sede", "Área",
                      "Proveedor", "Descripción", "Monto (USD)", "PDF"],
        column_config={
            "Aprobar": st.column_config.CheckboxColumn("☑", width="small"),
            "Monto (USD)": st.column_config.NumberColumn(format="$ %.2f"),
            "PDF": st.column_config.LinkColumn(display_text="Abrir"),
            "Descripción": st.column_config.TextColumn(width="medium"),
        },
        disabled=["N° OdC", "Fecha", "Sede", "Área", "Proveedor",
                  "Descripción", "Monto (USD)", "PDF"],
        key="editor_junta",
    )

    seleccionadas = editada[editada["Aprobar"] == True]  # noqa: E712
    ids = seleccionadas["id"].tolist()
    monto_sel = float(seleccionadas["Monto (USD)"].sum()) if ids else 0.0

    st.markdown(f"**Seleccionadas: {len(ids)}**  ·  Monto: **US$ {monto_sel:,.2f}**")

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button(f"✅ Firmar y aprobar ({len(ids)})", type="primary",
                     disabled=not ids, use_container_width=True):
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
                st.toast(
                    f"{len(ok)} cotización(es) firmada(s)", icon="✅"
                )
            st.button("Volver al panel")
    with c2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state.pop("confirmar_aprobar", None)
            st.session_state.pop("confirmar_monto", None)
            st.rerun()


# ---------------------------------------------------------------------------
# 10. Historial (consulta con filtros)
# ---------------------------------------------------------------------------
def panel_historial(usuario=None, clave="hist", sedes=None):
    st.subheader("🗂️ Historial")
    st.caption("Todo lo que ya pasó por el sistema. Usa los filtros para encontrar algo puntual.")

    filas = ds.listar_cotizaciones(subido_por=usuario, sedes_en=sedes)
    if not filas:
        st.info("Todavía no hay cotizaciones registradas.")
        return

    df = aplicar_filtros(filas, clave, list(ds.ETIQUETA_ESTATUS.keys()), sedes)
    mostrar_tabla(df, respaldos=ds.contar_respaldos())
    if not df.empty:
        ver_respaldos(df)


def panel_regenerar():
    """
    Rehace el expediente de una orden.

    Sirve para: rescatar órdenes que se cerraron antes de que existiera el
    expediente, y rehacerlo si algo falló al generarlo la primera vez.
    """
    st.markdown("##### 🧩 Regenerar expediente")
    st.caption(
        "Vuelve a armar el PDF completo (cotización + acta firmada + respaldos) "
        "de una orden ya firmada."
    )

    candidatas = [
        c for c in ds.listar_cotizaciones(estatus_en=["aprobado_firmado", "ejecutado"])
        if c.get("pdf_firmado_url")
    ]
    if not candidatas:
        st.caption("No hay órdenes firmadas todavía.")
        return

    def etiqueta(c):
        falta = "" if c.get("pdf_expediente_url") else "  ·  ⚠️ sin expediente"
        return f"{c['numero_odc']} · {c['proveedor']} · {ds.ETIQUETA_ESTATUS[c['estatus']]}{falta}"

    opciones = {etiqueta(c): c for c in candidatas}
    elegida = st.selectbox("Orden", list(opciones.keys()), key="sel_regen")
    cot = opciones[elegida]

    if st.button("Regenerar expediente", key="btn_regen"):
        try:
            with st.spinner("Armando el expediente..."):
                firmado = ds.descargar_archivo(cot["pdf_firmado_url"])

                archivos = []
                for r in ds.listar_respaldos(cot["id"]):
                    archivos.append({
                        "nombre": r["nombre_archivo"],
                        "contenido": ds.descargar_archivo(r["url"]),
                    })

                expediente = pdf_utils.generar_expediente(firmado, cot, archivos)
                url = ds.subir_expediente(expediente, cot["numero_odc"])
                ds.guardar_expediente(cot["id"], url)

            st.success(
                f"✅ Expediente de {cot['numero_odc']} regenerado"
                + (f" con {len(archivos)} respaldo(s)." if archivos else
                   " (esta orden no tiene respaldos adjuntos).")
            )
            st.rerun()
        except Exception as e:
            st.error("No se pudo regenerar el expediente.")
            st.caption(f"Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# 11. Panel administrativo (solo lectura)
# ---------------------------------------------------------------------------
def panel_administrativo(sedes):
    st.subheader("💳 Órdenes firmadas")
    st.caption(
        "Órdenes aprobadas por la Junta. Descarga el **Expediente** para tener en un "
        "solo PDF la cotización, el acta firmada y los respaldos del trabajo."
    )

    filas = ds.listar_cotizaciones(
        estatus_en=["aprobado_firmado", "ejecutado"], sedes_en=sedes
    )
    if not filas:
        st.info("Todavía no hay órdenes firmadas.")
        return

    firmadas = [f for f in filas if f["estatus"] == "aprobado_firmado"]
    ejecutadas = [f for f in filas if f["estatus"] == "ejecutado"]

    m1, m2, m3 = st.columns(3)
    m1.metric("Firmadas, sin ejecutar", len(firmadas))
    m2.metric("Ejecutadas", len(ejecutadas))
    m3.metric(
        "Monto ejecutado",
        f"US$ {sum(float(f['monto']) for f in ejecutadas):,.2f}",
    )

    df = aplicar_filtros(filas, "admvo", ["aprobado_firmado", "ejecutado"], sedes)
    mostrar_tabla(df, respaldos=ds.contar_respaldos())
    if not df.empty:
        ver_respaldos(df)


# ---------------------------------------------------------------------------
# 12. Pantalla principal
# ---------------------------------------------------------------------------
encabezado()

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
    es_administrativo = "administrativo" in roles
    es_jefe = "jefe" in roles

    # Sedes que esta persona puede ver y tocar. El admin ve las dos.
    sedes = ds.sedes_de_usuario(usuario, roles)

    with st.sidebar:
        st.caption(f"Sedes: {', '.join(sedes) if sedes else '—'}")

    if es_junta:
        t1, t2 = st.tabs(["🟡 Pendientes", "🗂️ Historial"])
        with t1:
            panel_junta(usuario, nombre, sedes)
        with t2:
            panel_historial(clave="junta", sedes=sedes)

    elif es_admin:
        t1, t2, t3, t4 = st.tabs(
            ["➕ Nueva", "🔧 Ejecutar", "🗂️ Historial", "👥 Usuarios"]
        )
        with t1:
            formulario_cotizacion(usuario, sedes)
        with t2:
            panel_ejecutar(usuario, ver_todo=True, sedes=sedes)
        with t3:
            panel_historial(clave="admin", sedes=sedes)
            st.divider()
            panel_regenerar()
        with t4:
            panel_usuarios(usuario)

    elif es_administrativo:
        panel_administrativo(sedes)

    elif es_jefe:
        t1, t2, t3 = st.tabs(["➕ Nueva", "🔧 Ejecutar", "🗂️ Mis cotizaciones"])
        with t1:
            formulario_cotizacion(usuario, sedes)
        with t2:
            panel_ejecutar(usuario, ver_todo=False, sedes=sedes)
        with t3:
            panel_historial(usuario=usuario, clave="jefe", sedes=sedes)

    else:
        st.warning("Tu usuario no tiene un rol asignado. Avisa al administrador.")
