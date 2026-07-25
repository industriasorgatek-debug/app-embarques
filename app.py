import streamlit as st
import sqlite3
import pandas as pd
import os

# -------------------------------------------------------------
# CONFIGURACIÓN DE CARPETAS (Adaptado para la Nube / GitHub)
# -------------------------------------------------------------
BASE_DIR = os.getcwd()  # Guarda en la carpeta actual del servidor
DOCS_DIR = os.path.join(BASE_DIR, 'documentos')
DB_PATH = os.path.join(BASE_DIR, 'embarques.db')

# Crear carpeta de documentos si no existe
if not os.path.exists(DOCS_DIR):
    os.makedirs(DOCS_DIR)

# Configuración de Códigos de Acceso (PINs)
PINS = {
    "1212": {"dept": "Compras", "role": "admin"},
    "1010": {"dept": "Administración", "role": "admon"},
    "1111": {"dept": "Almacén", "role": "almacen"}
}

NAVIERAS = ["CMA CGM", "HAPAG-LLOYD", "MAERSK", "ONE", "MSC", "COSCO", "EVERGREEN", "OTRO"]
ESTATUS_LISTA = ["En Puerto Origen", "En Tránsito", "En Aduana", "En Almacén", "Entregado"]

# Inicializar Base de Datos y migrar si es necesario
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS embarques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen TEXT, destino TEXT, fabricante TEXT,
            num_invoice TEXT, agente_carga TEXT, agente_aduanas TEXT,
            consignatario TEXT, producto TEXT, num_bl TEXT, naviera TEXT,
            num_contenedor TEXT, eta DATE, estatus TEXT,
            path_packing TEXT, path_invoice TEXT, path_flete TEXT, path_bl TEXT
        )
    ''')
    
    # Migración por seguridad
    c.execute("PRAGMA table_info(embarques)")
    columns = [column[1] for column in c.fetchall()]
    if 'naviera' not in columns:
        c.execute("ALTER TABLE embarques ADD COLUMN naviera TEXT")
        
    conn.commit()
    conn.close()

init_db()

# Guardar archivo PDF
def save_file(file, num_invoice, doc_type):
    if file is None:
        return None
    ext = file.name.split('.')[-1]
    safe_invoice = "".join(c for c in num_invoice if c.isalnum() or c in ('-', '_'))
    filename = f"INV_{safe_invoice}_{doc_type}.{ext}"
    filepath = os.path.join(DOCS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file.getbuffer())
    return filepath

# Configuración visual
st.set_page_config(page_title="Control de Embarques", layout="wide")

# Estado de sesión
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "user_dept" not in st.session_state:
    st.session_state.user_dept = None

# --- PANTALLA PRINCIPAL DE LOGIN ---
if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center;'>🚢 Sistema de Control de Embarques</h1>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center; color: gray;'>Por favor ingrese su PIN de acceso departamental</h4>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            pin_input = st.text_input("PIN de Acceso", type="password", max_chars=4, help="Ingrese su código de 4 dígitos")
            submit_login = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
            
            if submit_login:
                if pin_input in PINS:
                    st.session_state.authenticated = True
                    st.session_state.user_role = PINS[pin_input]["role"]
                    st.session_state.user_dept = PINS[pin_input]["dept"]
                    st.rerun()
                else:
                    st.error("❌ PIN incorrecto. Verifique con su departamento.")

# --- PANTALLA DENTRO DEL SISTEMA (AUTENTICADO) ---
else:
    st.sidebar.title("🚢 Menú Principal")
    st.sidebar.markdown(f"**Usuario:** {st.session_state.user_dept}")
    
    role = st.session_state.user_role
    options = []
    
    if role == "admin":  # Compras
        options = ["📋 Control de Embarques", "➕ Cargar Nuevo Embarque", "✏️ Editar / Actualizar Embarque", "📦 Zona Almacén", "💼 Zona Administración"]
    elif role == "admon":  # Administración
        options = ["📋 Control de Embarques", "💼 Zona Administración"]
    elif role == "almacen":  # Almacén
        options = ["📋 Control de Embarques", "📦 Zona Almacén"]
        
    menu = st.sidebar.radio("Navegación", options)
    
    st.sidebar.markdown("---")
    if st.sidebar.button("🔒 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_role = None
        st.session_state.user_dept = None
        st.rerun()

    conn = sqlite3.connect(DB_PATH)

    # --- VISTA 1: CONTROL DE EMBARQUES (GENERAL) ---
    if menu == "📋 Control de Embarques":
        st.title("📋 Control General de Embarques")
        st.caption("Visualización en tiempo real del estatus de la carga")
        
        df = pd.read_sql_query("SELECT * FROM embarques", conn)
        
        if df.empty:
            st.info("No hay embarques registrados aún en la base de datos.")
        else:
            df_display = df[['num_invoice', 'num_contenedor', 'num_bl', 'naviera', 'fabricante', 'producto', 'origen', 'destino', 'eta', 'estatus']].copy()
            df_display.columns = ['N° Invoice', 'Contenedor', 'N° BL', 'Línea Naviera', 'Fabricante', 'Producto', 'Origen', 'Destino', 'ETA (Arribo)', 'Estatus']
            st.dataframe(df_display, use_container_width=True)

    # --- VISTA 2: REGISTRO DE EMBARQUES (COMPRAS) ---
    elif menu == "➕ Cargar Nuevo Embarque":
        st.title("➕ Registrar Nuevo Embarque")
        
        with st.form("form_embarque", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                num_invoice = st.text_input("Número de Invoice *")
                fabricante = st.text_input("Fabricante / Proveedor")
                producto = st.text_input("Descripción del Producto")
                origen = st.text_input("Origen", value="China")
                destino = st.text_input("Destino", value="Venezuela")
                
            with col2:
                num_bl = st.text_input("Número de BL *")
                naviera = st.selectbox("Línea Naviera", NAVIERAS)
                num_contenedor = st.text_input("Número de Contenedor")
                agente_carga = st.text_input("Agente de Carga Asignado")
                agente_aduanas = st.text_input("Agente de Aduanas")
                
            with col3:
                consignatario = st.text_input("Consignatario")
                eta = st.date_input("Estimado de Arribo (ETA)")
                estatus = st.selectbox("Estatus Inicial", ESTATUS_LISTA)
            
            st.markdown("### Adjuntar Documentación (PDF/Excel)")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                file_packing = st.file_uploader("Packing List (Para Almacén)", type=["pdf", "xlsx"])
                file_invoice = st.file_uploader("Factura Comercial (Invoice)", type=["pdf"])
            with col_f2:
                file_flete = st.file_uploader("Factura de Flete", type=["pdf"])
                file_bl = st.file_uploader("Documento BL", type=["pdf"])
                
            submitted = st.form_submit_button("Guardar y Publicar Embarque")
            
            if submitted:
                if not num_invoice or not num_bl:
                    st.error("El N° de Invoice y N° de BL son obligatorios.")
                else:
                    p_pack = save_file(file_packing, num_invoice, "packing")
                    p_inv = save_file(file_invoice, num_invoice, "invoice")
                    p_fle = save_file(file_flete, num_invoice, "flete")
                    p_bl = save_file(file_bl, num_invoice, "bl")
                    
                    c = conn.cursor()
                    c.execute('''
                        INSERT INTO embarques (
                            origen, destino, fabricante, num_invoice, agente_carga,
                            agente_aduanas, consignatario, producto, num_bl, naviera, num_contenedor,
                            eta, estatus, path_packing, path_invoice, path_flete, path_bl
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (origen, destino, fabricante, num_invoice, agente_carga,
                          agente_aduanas, consignatario, producto, num_bl, naviera, num_contenedor,
                          str(eta), estatus, p_pack, p_inv, p_fle, p_bl))
                    conn.commit()
                    st.success(f"Embarque con Invoice {num_invoice} registrado exitosamente.")

    # --- VISTA 3: EDITAR EMBARQUES (COMPRAS) ---
    elif menu == "✏️ Editar / Actualizar Embarque":
        st.title("✏️ Editar Embarque Existente")
        
        df = pd.read_sql_query("SELECT * FROM embarques", conn)
        
        if df.empty:
            st.info("No hay embarques para editar.")
        else:
            selected_invoice = st.selectbox("Selecciona la Invoice a modificar:", df['num_invoice'].unique())
            row = df[df['num_invoice'] == selected_invoice].iloc[0]
            
            with st.form("form_editar_embarque"):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    num_invoice_edit = st.text_input("Número de Invoice", value=str(row['num_invoice']), disabled=True)
                    fabricante_edit = st.text_input("Fabricante / Proveedor", value=str(row['fabricante'] or ''))
                    producto_edit = st.text_input("Descripción del Producto", value=str(row['producto'] or ''))
                    origen_edit = st.text_input("Origen", value=str(row['origen'] or ''))
                    destino_edit = st.text_input("Destino", value=str(row['destino'] or ''))
                    
                with col2:
                    num_bl_edit = st.text_input("Número de BL", value=str(row['num_bl'] or ''))
                    nav_val = str(row['naviera']) if row['naviera'] in NAVIERAS else NAVIERAS[0]
                    nav_index = NAVIERAS.index(nav_val)
                    naviera_edit = st.selectbox("Línea Naviera", NAVIERAS, index=nav_index)
                    num_contenedor_edit = st.text_input("Número de Contenedor", value=str(row['num_contenedor'] or ''))
                    agente_carga_edit = st.text_input("Agente de Carga", value=str(row['agente_carga'] or ''))
                    agente_aduanas_edit = st.text_input("Agente de Aduanas", value=str(row['agente_aduanas'] or ''))
                    
                with col3:
                    consignatario_edit = st.text_input("Consignatario", value=str(row['consignatario'] or ''))
                    
                    try:
                        fecha_val = pd.to_datetime(row['eta']).date()
                    except:
                        fecha_val = pd.to_datetime("today").date()
                    eta_edit = st.date_input("Estimado de Arribo (ETA)", value=fecha_val)
                    
                    est_val = str(row['estatus']) if row['estatus'] in ESTATUS_LISTA else ESTATUS_LISTA[0]
                    est_index = ESTATUS_LISTA.index(est_val)
                    estatus_edit = st.selectbox("Estatus Actualizado", ESTATUS_LISTA, index=est_index)
                
                st.markdown("---")
                st.markdown("### Actualizar / Reemplazar Documentos (Opcional)")
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    new_file_packing = st.file_uploader("Nuevo Packing List", type=["pdf", "xlsx"], key="edit_pack")
                    new_file_invoice = st.file_uploader("Nueva Factura Comercial", type=["pdf"], key="edit_inv")
                with col_f2:
                    new_file_flete = st.file_uploader("Nueva Factura Flete", type=["pdf"], key="edit_fle")
                    new_file_bl = st.file_uploader("Nuevo BL", type=["pdf"], key="edit_bl")

                submit_edit = st.form_submit_button("💾 Guardar Cambios en Embarque")
                
                if submit_edit:
                    p_pack = save_file(new_file_packing, selected_invoice, "packing") or row['path_packing']
                    p_inv = save_file(new_file_invoice, selected_invoice, "invoice") or row['path_invoice']
                    p_fle = save_file(new_file_flete, selected_invoice, "flete") or row['path_flete']
                    p_bl = save_file(new_file_bl, selected_invoice, "bl") or row['path_bl']
                    
                    c = conn.cursor()
                    c.execute('''
                        UPDATE embarques SET
                            origen = ?, destino = ?, fabricante = ?, agente_carga = ?,
                            agente_aduanas = ?, consignatario = ?, producto = ?, num_bl = ?,
                            naviera = ?, num_contenedor = ?, eta = ?, estatus = ?,
                            path_packing = ?, path_invoice = ?, path_flete = ?, path_bl = ?
                        WHERE num_invoice = ?
                    ''', (origen_edit, destino_edit, fabricante_edit, agente_carga_edit,
                          agente_aduanas_edit, consignatario_edit, producto_edit, num_bl_edit,
                          naviera_edit, num_contenedor_edit, str(eta_edit), estatus_edit,
                          p_pack, p_inv, p_fle, p_bl, selected_invoice))
                    conn.commit()
                    st.success(f"✅ ¡Embarque Invoice {selected_invoice} actualizado con éxito!")

    # --- VISTA 4: ZONA ALMACÉN ---
    elif menu == "📦 Zona Almacén":
        st.title("📦 Zona Almacén - Descarga de Packing Lists")
        df = pd.read_sql_query("SELECT * FROM embarques", conn)
        
        if df.empty:
            st.info("No hay embarques registrados.")
        else:
            selected_invoice = st.selectbox("Selecciona por Número de Invoice:", df['num_invoice'].unique())
            row = df[df['num_invoice'] == selected_invoice].iloc[0]
            
            st.markdown(f"**Contenedor:** {row['num_contenedor']} | **ETA (Llegada):** {row['eta']} | **Producto:** {row['producto']}")
            
            if row['path_packing'] and os.path.exists(row['path_packing']):
                with open(row['path_packing'], "rb") as f:
                    st.download_button(
                        label=f"⬇️ Descargar Packing List de Invoice {selected_invoice}",
                        data=f,
                        file_name=os.path.basename(row['path_packing']),
                        mime="application/octet-stream"
                    )
            else:
                st.warning("⚠️ No se ha adjuntado el Packing List para esta Invoice aún.")

    # --- VISTA 5: ZONA ADMINISTRACIÓN ---
    elif menu == "💼 Zona Administración":
        st.title("💼 Zona Administración - Expedientes de Carga")
        df = pd.read_sql_query("SELECT * FROM embarques", conn)
        
        if df.empty:
            st.info("No hay embarques registrados.")
        else:
            selected_invoice = st.selectbox("Selecciona por Número de Invoice:", df['num_invoice'].unique())
            row = df[df['num_invoice'] == selected_invoice].iloc[0]
            
            naviera_val = row['naviera'] if 'naviera' in row and row['naviera'] else "No especificada"
            st.markdown(f"**Contenedor:** {row['num_contenedor']} | **BL N°:** {row['num_bl']} | **Naviera:** {naviera_val}")
            
            docs = [
                ("Packing List", row['path_packing']),
                ("Factura Comercial (Invoice)", row['path_invoice']),
                ("Factura de Flete", row['path_flete']),
                ("Bill of Lading (BL)", row['path_bl'])
            ]
            
            st.markdown("#### Documentos Disponibles:")
            for label, path in docs:
                if path and os.path.exists(path):
                    with open(path, "rb") as f:
                        st.download_button(
                            label=f"⬇️ Descargar {label}",
                            data=f,
                            file_name=os.path.basename(path),
                            mime="application/octet-stream",
                            key=f"admon_{label}_{selected_invoice}"
                        )
                else:
                    st.caption(f"❌ {label}: No cargado")

    conn.close()
