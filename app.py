import streamlit as st
import sqlite3
import pandas as pd
import os
from datetime import date

# -------------------------------------------------------------
# CONFIGURACIÓN DE CARPETAS Y BASE DE DATOS
# -------------------------------------------------------------
BASE_DIR = os.getcwd()
DOCS_DIR = os.path.join(BASE_DIR, 'documentos')
DB_PATH = os.path.join(BASE_DIR, 'embarques.db')

if not os.path.exists(DOCS_DIR):
    os.makedirs(DOCS_DIR)

# PINs de Acceso
PINS = {
    "1212": {"dept": "Compras", "role": "admin"},
    "1010": {"dept": "Administración", "role": "admon"},
    "1111": {"dept": "Almacén", "role": "almacen"}
}

NAVIERAS = ["CMA CGM", "HAPAG-LLOYD", "MAERSK", "ONE", "MSC", "COSCO", "EVERGREEN", "OTRO"]

ESTATUS_LISTA = [
    "En Producción",
    "En POL",
    "En Tránsito",
    "En Aduanas",
    "Entregado"
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS embarques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen TEXT, destino TEXT, fabricante TEXT,
            num_invoice TEXT UNIQUE, agente_carga TEXT, agente_aduanas TEXT,
            consignatario TEXT, producto TEXT, num_bl TEXT, naviera TEXT,
            num_contenedor TEXT, eta DATE, estatus TEXT,
            path_packing TEXT, path_invoice TEXT, path_flete TEXT, path_bl TEXT
        )
    ''')
    c.execute("PRAGMA table_info(embarques)")
    columns = [column[1] for column in c.fetchall()]
    if 'naviera' not in columns:
        c.execute("ALTER TABLE embarques ADD COLUMN naviera TEXT")
    conn.commit()
    conn.close()

init_db()

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

# Función para validar rutas de archivos de forma 100% segura
def has_valid_file(path_val):
    if pd.isna(path_val) or path_val is None:
        return False
    path_str = str(path_val).strip()
    if path_str in ['', 'None', 'nan', 'NaT']:
        return False
    return os.path.exists(path_str)

# Función para parsear fechas de forma 100% segura
def safe_parse_date(val):
    if pd.isna(val) or str(val).strip() in ['', 'nan', 'NaT', 'None']:
        return date.today()
    try:
        parsed = pd.to_datetime(val)
        if pd.isna(parsed):
            return date.today()
        return parsed.date()
    except Exception:
        return date.today()

# Configuración de página
st.set_page_config(page_title="Control de Embarques", layout="wide")

# Variables de Estado de Sesión
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "user_dept" not in st.session_state:
    st.session_state.user_dept = None
if "editing_invoice" not in st.session_state:
    st.session_state.editing_invoice = None

# --- PANTALLA LOGIN ---
if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center;'>🚢 Sistema de Control de Embarques</h1>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center; color: gray;'>Ingrese su PIN de acceso departamental</h4>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            pin_input = st.text_input("PIN de Acceso", type="password", max_chars=4)
            submit_login = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
            
            if submit_login:
                if pin_input in PINS:
                    st.session_state.authenticated = True
                    st.session_state.user_role = PINS[pin_input]["role"]
                    st.session_state.user_dept = PINS[pin_input]["dept"]
                    st.rerun()
                else:
                    st.error("❌ PIN incorrecto.")

# --- PANTALLA SISTEMA ---
else:
    st.sidebar.title("🚢 Menú Principal")
    st.sidebar.markdown(f"**Usuario:** {st.session_state.user_dept}")
    
    role = st.session_state.user_role
    
    # Definición de opciones simplificada por rol
    if role == "admin":  # Compras
        options = [
            "📋 Control de Embarques", 
            "📊 Carga Masiva (Excel/CSV)", 
            "➕ Cargar Nuevo Embarque", 
            "✏️ Editar / Actualizar Embarque"
        ]
    else:  # Almacén y Administración solo requieren la vista centralizada
        options = ["📋 Control de Embarques"]

    menu = st.sidebar.radio("Navegación", options)

    st.sidebar.markdown("---")
    if st.sidebar.button("🔒 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_role = None
        st.session_state.user_dept = None
        st.session_state.editing_invoice = None
        st.rerun()

    conn = sqlite3.connect(DB_PATH)

    # --- VISTA ÚNICA / PRINCIPAL: CONTROL DE EMBARQUES ---
    if menu == "📋 Control de Embarques":
        st.title("📋 Control General de Embarques")
        st.caption("Visualización interactiva y gestión de archivos en tiempo real")
        
        df = pd.read_sql_query("SELECT * FROM embarques", conn)
        
        if df.empty:
            st.info("No hay embarques registrados aún.")
        else:
            def highlight_status(val):
                val_clean = str(val).strip().lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
                if val_clean == 'entregado':
                    return 'background-color: #F8D7DA; color: #721C24; font-weight: bold;'
                elif 'transito' in val_clean:
                    return 'background-color: #D4EDDA; color: #155724; font-weight: bold;'
                elif 'aduana' in val_clean:
                    return 'background-color: #FFF3CD; color: #856404; font-weight: bold;'
                return ''

            df_display = df[['num_invoice', 'num_contenedor', 'num_bl', 'naviera', 'fabricante', 'producto', 'origen', 'destino', 'eta', 'estatus']].copy()
            df_display.columns = ['N° Invoice', 'Contenedor', 'N° BL', 'Línea Naviera', 'Fabricante', 'Producto', 'Origen', 'Destino', 'ETA (Arribo)', 'Estatus']

            styled_df = df_display.style.map(highlight_status, subset=['Estatus'])

            st.info("💡 **Tip:** Haz clic sobre cualquier fila de la tabla para seleccionar un embarque y descargar sus documentos abajo.")
            
            # Tabla Interactiva
            event = st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="tabla_interactiva"
            )

            selected_rows = event.selection.get("rows", [])
            if selected_rows:
                row_idx = selected_rows[0]
                selected_invoice = df_display.iloc[row_idx]['N° Invoice']
                row_data = df[df['num_invoice'] == selected_invoice].iloc[0]

                st.markdown("---")
                st.success(f"📌 Embarque Seleccionado: **Invoice {selected_invoice}** | Contenedor: **{row_data['num_contenedor']}** | ETA: **{row_data['eta']}**")

                # ACCIONES DINÁMICAS POR ROL

                # 1. ROL ALMACÉN -> Solo Packing List
                if role == "almacen":
                    st.subheader("📦 Descarga de Packing List")
                    if has_valid_file(row_data['path_packing']):
                        with open(row_data['path_packing'], "rb") as f:
                            st.download_button(
                                label=f"⬇️ Descargar Packing List ({selected_invoice})",
                                data=f,
                                file_name=os.path.basename(row_data['path_packing']),
                                mime="application/octet-stream",
                                type="primary",
                                key=f"main_pack_{selected_invoice}"
                            )
                    else:
                        st.warning("⚠️ No se ha adjuntado el Packing List para esta Invoice aún.")

                # 2. ROL ADMINISTRACIÓN -> Todo el Expediente Digital
                elif role == "admon":
                    st.subheader("💼 Expediente Digital del Embarque")
                    docs = [
                        ("Packing List", row_data['path_packing']),
                        ("Factura Comercial (Invoice)", row_data['path_invoice']),
                        ("Factura de Flete", row_data['path_flete']),
                        ("Bill of Lading (BL)", row_data['path_bl'])
                    ]
                    
                    col_d1, col_d2 = st.columns(2)
                    for idx, (label, path) in enumerate(docs):
                        col_target = col_d1 if idx % 2 == 0 else col_d2
                        with col_target:
                            if has_valid_file(path):
                                with open(path, "rb") as f:
                                    st.download_button(
                                        label=f"⬇️ Descargar {label}",
                                        data=f,
                                        file_name=os.path.basename(path),
                                        mime="application/octet-stream",
                                        key=f"main_admon_{label}_{selected_invoice}"
                                    )
                            else:
                                st.caption(f"❌ {label}: No cargado")

                # 3. ROL COMPRAS / ADMIN -> Edición
                elif role == "admin":
                    if st.button(f"✏️ Desplegar Formulario de Edición Rápida ({selected_invoice})", type="primary"):
                        st.session_state.editing_invoice = selected_invoice

            # Formulario de Edición para Compras (Admin)
            if role == "admin" and st.session_state.editing_invoice:
                st.markdown("---")
                st.subheader(f"🛠️ Editando Embarque: {st.session_state.editing_invoice}")
                
                row_data = df[df['num_invoice'] == st.session_state.editing_invoice].iloc[0]
                
                with st.form("form_quick_edit"):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.text_input("Número de Invoice", value=str(row_data['num_invoice']), disabled=True)
                        fabricante_e = st.text_input("Fabricante / Proveedor", value=str(row_data['fabricante'] or ''))
                        producto_e = st.text_input("Descripción del Producto", value=str(row_data['producto'] or ''))
                        origen_e = st.text_input("Origen", value=str(row_data['origen'] or ''))
                        destino_e = st.text_input("Destino", value=str(row_data['destino'] or ''))
                        
                    with col2:
                        num_bl_e = st.text_input("Número de BL", value=str(row_data['num_bl'] or ''))
                        nav_val = str(row_data['naviera']) if row_data['naviera'] in NAVIERAS else NAVIERAS[0]
                        naviera_e = st.selectbox("Línea Naviera", NAVIERAS, index=NAVIERAS.index(nav_val))
                        num_contenedor_e = st.text_input("Número de Contenedor", value=str(row_data['num_contenedor'] or ''))
                        agente_carga_e = st.text_input("Agente de Carga", value=str(row_data['agente_carga'] or ''))
                        agente_aduanas_e = st.text_input("Agente de Aduanas", value=str(row_data['agente_aduanas'] or ''))
                        
                    with col3:
                        consignatario_e = st.text_input("Consignatario", value=str(row_data['consignatario'] or ''))
                        fecha_v = safe_parse_date(row_data['eta'])
                        eta_e = st.date_input("Estimado de Arribo (ETA)", value=fecha_v)
                        
                        est_v = str(row_data['estatus']) if row_data['estatus'] in ESTATUS_LISTA else ESTATUS_LISTA[0]
                        estatus_e = st.selectbox("Estatus Actualizado", ESTATUS_LISTA, index=ESTATUS_LISTA.index(est_v))
                    
                    st.markdown("### Actualizar / Reemplazar Documentos (Opcional)")
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        q_file_pack = st.file_uploader("Nuevo Packing List", type=["pdf", "xlsx"], key="q_pack")
                        q_file_inv = st.file_uploader("Nueva Factura Comercial", type=["pdf"], key="q_inv")
                    with col_f2:
                        q_file_fle = st.file_uploader("Nueva Factura Flete", type=["pdf"], key="q_fle")
                        q_file_bl = st.file_uploader("Nuevo BL", type=["pdf"], key="q_bl")

                    submit_q_edit = st.form_submit_button("💾 Guardar Cambios", type="primary", use_container_width=True)
                    
                if submit_q_edit:
                    p_pack = save_file(q_file_pack, st.session_state.editing_invoice, "packing") or row_data['path_packing']
                    p_inv = save_file(q_file_inv, st.session_state.editing_invoice, "invoice") or row_data['path_invoice']
                    p_fle = save_file(q_file_fle, st.session_state.editing_invoice, "flete") or row_data['path_flete']
                    p_bl = save_file(q_file_bl, st.session_state.editing_invoice, "bl") or row_data['path_bl']
                    
                    c = conn.cursor()
                    c.execute('''
                        UPDATE embarques SET
                            origen = ?, destino = ?, fabricante = ?, agente_carga = ?,
                            agente_aduanas = ?, consignatario = ?, producto = ?, num_bl = ?,
                            naviera = ?, num_contenedor = ?, eta = ?, estatus = ?,
                            path_packing = ?, path_invoice = ?, path_flete = ?, path_bl = ?
                        WHERE num_invoice = ?
                    ''', (origen_e, destino_e, fabricante_e, agente_carga_e,
                          agente_aduanas_e, consignatario_e, producto_e, num_bl_e,
                          naviera_e, num_contenedor_e, str(eta_e), estatus_e,
                          p_pack, p_inv, p_fle, p_bl, st.session_state.editing_invoice))
                    conn.commit()
                    st.session_state.editing_invoice = None
                    st.success("✅ ¡Embarque actualizado con éxito!")
                    st.rerun()

    # --- VISTA 2: CARGA MASIVA EXCEL / CSV ---
    elif menu == "📊 Carga Masiva (Excel/CSV)":
        st.title("📊 Carga Masiva de Embarques")
        st.caption("Actualiza o inserta múltiples embarques subiendo una hoja de cálculo.")

        sample_data = pd.DataFrame([{
            "num_invoice": "INV-1001", "num_bl": "BL-998877", "num_contenedor": "MSCU1234567",
            "naviera": "MSC", "fabricante": "Tech Corp", "producto": "Lámparas LED",
            "origen": "China", "destino": "Venezuela", "eta": "2026-08-15",
            "estatus": "En Tránsito", "agente_carga": "DHL", "agente_aduanas": "Aduanas C.A.",
            "consignatario": "Industrias Orgatek"
        }])
        
        csv_sample = sample_data.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar Plantilla de Ejemplo (CSV)", csv_sample, "plantilla_embarques.csv", "text/csv")

        st.markdown("---")
        uploaded_file = st.file_uploader("Selecciona tu archivo Excel (.xlsx) o CSV", type=["xlsx", "csv"])

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_upload = pd.read_csv(uploaded_file)
                else:
                    df_upload = pd.read_excel(uploaded_file)

                df_upload.columns = df_upload.columns.str.strip().str.lower()
                col_map = {
                    'invoice': 'num_invoice', 'empresa': 'fabricante', 'agente': 'agente_carga',
                    'ag aduana': 'agente_aduanas', 'consignee': 'consignatario', 'estimado': 'eta',
                    'org /bl / booking': 'num_bl'
                }
                df_upload.rename(columns=col_map, inplace=True)

                st.markdown("### Vista previa de los datos a importar:")
                st.dataframe(df_upload.head(10), use_container_width=True)

                if 'num_invoice' not in df_upload.columns:
                    st.error("❌ El archivo debe contener obligatoriamente la columna `num_invoice` o `INVOICE`.")
                else:
                    if st.button("🚀 Procesar e Importar a la Base de Datos", type="primary"):
                        c = conn.cursor()
                        registros_actualizados = 0
                        registros_nuevos = 0

                        for _, row in df_upload.iterrows():
                            invoice = str(row.get('num_invoice', '')).strip()
                            if not invoice or invoice == 'nan':
                                continue

                            bl = str(row.get('num_bl', '')) if pd.notna(row.get('num_bl')) else ''
                            contenedor = str(row.get('num_contenedor', '')) if pd.notna(row.get('num_contenedor')) else ''
                            naviera = str(row.get('naviera', '')) if pd.notna(row.get('naviera')) else ''
                            fabricante = str(row.get('fabricante', '')) if pd.notna(row.get('fabricante')) else ''
                            producto = str(row.get('producto', '')) if pd.notna(row.get('producto')) else ''
                            origen = str(row.get('origen', 'China')) if pd.notna(row.get('origen')) else 'China'
                            destino = str(row.get('destino', 'Venezuela')) if pd.notna(row.get('destino')) else 'Venezuela'
                            eta = str(row.get('eta', '')) if pd.notna(row.get('eta')) else ''
                            estatus = str(row.get('estatus', 'En Producción')) if pd.notna(row.get('estatus')) else 'En Producción'
                            agente_carga = str(row.get('agente_carga', '')) if pd.notna(row.get('agente_carga')) else ''
                            agente_aduanas = str(row.get('agente_aduanas', '')) if pd.notna(row.get('agente_aduanas')) else ''
                            consignatario = str(row.get('consignatario', '')) if pd.notna(row.get('consignatario')) else ''

                            c.execute("SELECT id FROM embarques WHERE num_invoice = ?", (invoice,))
                            exists = c.fetchone()

                            if exists:
                                c.execute('''
                                    UPDATE embarques SET
                                        num_bl = ?, num_contenedor = ?, naviera = ?, fabricante = ?,
                                        producto = ?, origen = ?, destino = ?, eta = ?, estatus = ?,
                                        agente_carga = ?, agente_aduanas = ?, consignatario = ?
                                    WHERE num_invoice = ?
                                ''', (bl, contenedor, naviera, fabricante, producto, origen, destino, eta, estatus, agente_carga, agente_aduanas, consignatario, invoice))
                                registros_actualizados += 1
                            else:
                                c.execute('''
                                    INSERT INTO embarques (
                                        num_invoice, num_bl, num_contenedor, naviera, fabricante,
                                        producto, origen, destino, eta, estatus, agente_carga,
                                        agente_aduanas, consignatario
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (invoice, bl, contenedor, naviera, fabricante, producto, origen, destino, eta, estatus, agente_carga, agente_aduanas, consignatario))
                                registros_nuevos += 1

                        conn.commit()
                        st.success(f"✅ Procesamiento completado: {registros_nuevos} embarques creados, {registros_actualizados} actualizados.")
            except Exception as e:
                st.error(f"Error al leer el archivo: {e}")

    # --- VISTA 3: REGISTRO MANUAL ---
    elif menu == "➕ Cargar Nuevo Embarque":
        st.title("➕ Registrar Nuevo Embarque Manual")
        
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
                    try:
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
                    except sqlite3.IntegrityError:
                        st.error(f"❌ La Invoice {num_invoice} ya existe en la base de datos.")

    # --- VISTA 4: EDITAR EMBARQUES ---
    elif menu == "✏️ Editar / Actualizar Embarque":
        st.title("✏️ Editar Embarque Existente")
        df = pd.read_sql_query("SELECT * FROM embarques", conn)
        
        if df.empty:
            st.info("No hay embarques para editar.")
        else:
            invoices_list = list(df['num_invoice'].unique())
            selected_invoice = st.selectbox("Selecciona la Invoice a modificar:", invoices_list)
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
                    naviera_edit = st.selectbox("Línea Naviera", NAVIERAS, index=NAVIERAS.index(nav_val))
                    num_contenedor_edit = st.text_input("Número de Contenedor", value=str(row['num_contenedor'] or ''))
                    agente_carga_edit = st.text_input("Agente de Carga", value=str(row['agente_carga'] or ''))
                    agente_aduanas_edit = st.text_input("Agente de Aduanas", value=str(row['agente_aduanas'] or ''))
                    
                with col3:
                    consignatario_edit = st.text_input("Consignatario", value=str(row['consignatario'] or ''))
                    fecha_val = safe_parse_date(row['eta'])
                    eta_edit = st.date_input("Estimado de Arribo (ETA)", value=fecha_val)
                    
                    est_val = str(row['estatus']) if row['estatus'] in ESTATUS_LISTA else ESTATUS_LISTA[0]
                    estatus_edit = st.selectbox("Estatus Actualizado", ESTATUS_LISTA, index=ESTATUS_LISTA.index(est_val))
                
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

    conn.close()
