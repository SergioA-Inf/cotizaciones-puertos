"""
App de Cotizaciones - Terminales de Cruceros (Amador / Panamá y Colón)
=====================================================================
PASO 3: esqueleto con login.

Por ahora la app SOLO valida el ingreso y muestra el rol del usuario.
En los próximos pasos construimos los paneles reales (jefe / junta).

Las contraseñas NO viven en este código: viven en los "Secrets" de
Streamlit Cloud, así que nunca quedan expuestas en GitHub.
"""

import streamlit as st
import streamlit_authenticator as stauth

st.set_page_config(page_title="Cotizaciones Puertos", page_icon="📋", layout="wide")


# ---------------------------------------------------------------------------
# 1. Construir la lista de usuarios a partir de los Secrets de Streamlit.
#    En los Secrets cada usuario se ve así:
#       [credentials.sergio]
#       first_name = "Sergio"
#       password   = "..."
#       roles      = ["admin"]
# ---------------------------------------------------------------------------
def cargar_credenciales():
    credenciales = {"usernames": {}}
    for usuario, datos in st.secrets["credentials"].items():
        credenciales["usernames"][usuario] = {
            "first_name": datos.get("first_name", ""),
            "last_name": datos.get("last_name", ""),
            "email": datos.get("email", ""),
            "password": datos["password"],          # se cifra automáticamente
            "roles": list(datos.get("roles", [])),
        }
    return credenciales


credenciales = cargar_credenciales()

authenticator = stauth.Authenticate(
    credenciales,
    st.secrets["auth_cookie"]["name"],
    st.secrets["auth_cookie"]["key"],
    st.secrets["auth_cookie"]["expiry_days"],
)


# ---------------------------------------------------------------------------
# 2. Formulario de login.
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
    # -----------------------------------------------------------------------
    # 3. Usuario autenticado: saludo, rol y botón de salir.
    # -----------------------------------------------------------------------
    nombre = st.session_state.get("name", "")
    usuario = st.session_state.get("username", "")
    roles = st.session_state.get("roles", []) or []

    with st.sidebar:
        st.write(f"**Sesión:** {nombre}")
        st.caption(f"Usuario: {usuario}")
        st.caption(f"Rol: {', '.join(roles) if roles else '—'}")
        authenticator.logout("Cerrar sesión", location="sidebar")

    st.success(f"Bienvenido, {nombre}.")

    # Ruteo por rol. Por ahora solo un aviso; los paneles llegan en los
    # próximos pasos. Esto nos confirma que los roles se leen bien.
    if "admin" in roles:
        st.subheader("Panel de Administración")
        st.write("Aquí verás y gestionarás todas las cotizaciones de ambos puertos.")
    elif "junta" in roles:
        st.subheader("Panel de la Junta Directiva")
        st.write("Aquí revisarás y aprobarás o rechazarás las cotizaciones.")
    elif "jefe" in roles:
        st.subheader("Panel de Jefe de Área")
        st.write("Aquí subirás cotizaciones y descargarás las ya firmadas.")
    else:
        st.warning("Tu usuario no tiene un rol asignado. Avisa al administrador.")

    st.divider()
    st.caption("Esqueleto funcionando ✅ — el siguiente paso es el panel del jefe.")
