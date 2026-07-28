import streamlit as st
import sqlite3
import pandas as pd
import os
import io
import urllib.parse
import zipfile
from datetime import date

# -------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA
# -------------------------------------------------------------
st.set_page_config(page_title="Control de Embarques", layout="wide")

# Importación para la generación del PDF
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# -------------------------------------------------------------
# CONFIGURACIÓN DE CARPETAS Y BASE DE DATOS
# -------------------------------------------------------------
BASE_DIR = os.getcwd()
DOCS_DIR = os.path.join(BASE_DIR, 'documentos')
PAYMENTS_DIR = os.path.join(BASE_DIR, 'comprobantes_pagos')
DB_PATH = os.path.join(BASE_DIR, 'embarques.db')

for folder in [DOCS_DIR, PAYMENTS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# PINs de Acceso
PINS = {
    "1212": {"dept": "Compras", "role": "admin"},
    "1010": {"dept": "Administración", "role": "admon"},
    "1111": {"dept": "Almacén", "role": "almacen"}
}

NAVIERAS = ["CMA CGM", "HAPAG-LLOYD", "MAERSK", "ONE", "MSC", "COSCO", "EVERGREEN", "OTRO"]

ESTATUS_LISTA = [
    "Pendiente Pago",
    "En Producción",
    "En Tránsito 1",
    "En Tránsito 2",
    "En Tránsito 3",
    "En Aduanas",
    "Entregado"
]

BANCOS_LISTA = [
    "SAFRA BANK",
    "BANESCO PANAMA",
    "BANESCO USA",
    "SISTEMA SIMKIN",
    "CONVENIO RMB",
    "OTRO USD"
]

TIPO_PAGO_LISTA = [
    "Pago a Fábrica",
    "Pago a Freight Forwarder"
]

TIPOS_DOCS_COMPRAS = [
    "Certificado de Origen",
    "Manifiesto de Exportación",
    "Seguro de Carga",
    "DUA Draft",
    "RECA",
    "Fotos de Embarque",
    "Fotos de Descarga",
    "Otro Documento"
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Tabla Principal de Embarques
    c.execute('''
        CREATE TABLE IF NOT EXISTS embarques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen TEXT, destino TEXT, fabricante TEXT,
            num_invoice TEXT UNIQUE, agente_carga TEXT, agente_aduanas TEXT,
            consignatario TEXT, producto TEXT, num_bl TEXT, naviera TEXT,
            num_contenedor TEXT, eta DATE, estatus TEXT,
            path_packing TEXT, path_invoice TEXT, path_flete TEXT, path_bl TEXT,
            monto_factura REAL DEFAULT 0.0
        )
    ''')
    
    # Tabla Relacional de Pagos
    c.execute('''
        CREATE TABLE IF NOT EXISTS pagos_embarques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_invoice TEXT,
            tipo_pago TEXT,
            banco TEXT,
            monto REAL,
            fecha_pago DATE,
            referencia TEXT,
            path_comprobante TEXT,
            FOREIGN KEY (num_invoice) REFERENCES embarques(num_invoice)
        )
    ''')

    # Tabla Relacional de Documentos Dinámicos (Expediente Anexo)
    c.execute('''
        CREATE TABLE IF NOT EXISTS documentos_embarque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_invoice TEXT,
            tipo_documento TEXT,
            nombre_archivo TEXT,
            path_archivo TEXT,
            fecha_subida DATE,
            subido_por TEXT,
            FOREIGN KEY (num_invoice) REFERENCES embarques(num_invoice)
        )
    ''')

    c.execute("PRAGMA table_info(embarques)")
    columns = [column[1] for column in c.fetchall()]
    if 'naviera' not in columns:
        c.execute("ALTER TABLE embarques ADD COLUMN naviera TEXT")
    if 'monto_factura' not in columns:
        c.execute("ALTER TABLE embarques ADD COLUMN monto_factura REAL DEFAULT 0.0")
        
    conn.commit()
    conn.close()

init_db()

def save_file(file, num_invoice, doc_type, is_payment=False):
    if file is None:
        return None
    ext = file.name.split('.')[-1]
    safe_invoice = "".join(c for c in num_invoice if c.isalnum() or c in ('-', '_'))
    
    target_dir = PAYMENTS_DIR if is_payment else DOCS_DIR
    filename = f"PAY_{safe_invoice}_{doc_type}.{ext}" if is_payment else f"INV_{safe_invoice}_{doc_type}.{ext}"
    filepath = os.path.join(target_dir, filename)
    
    with open(filepath, "wb") as f:
        f.write(file.getbuffer())
    return filepath

def save_extra_file(file, num_invoice, doc_type):
    if file is None:
        return None, None
    safe_invoice = "".join(c for c in num_invoice if c.isalnum() or c in ('-', '_'))
    safe_doc_type = "".join(c for c in doc_type if c.isalnum() or c in ('-', '_'))
    filename = f"ANX_{safe_invoice}_{safe_doc_type}_{file.name}"
    filepath = os.path.join(DOCS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file.getbuffer())
    return filepath, file.name

def has_valid_file(path_val):
    if pd.isna(path_val) or path_val is None:
        return False
    path_str = str(path_val).strip()
    if path_str in ['', 'None', 'nan', 'NaT']:
        return False
    return os.path.exists(path_str)

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

def generar_zip_expediente(num_invoice, row_data, conn):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        core_docs = [
            ('Packing_List', row_data['path_packing']),
            ('Factura_Comercial', row_data['path_invoice']),
            ('Factura_Flete', row_data['path_flete']),
            ('Bill_of_Lading', row_data['path_bl'])
        ]
        for label, path in core_docs:
            if has_valid_file(path):
                zip_file.write(path, arcname=f"Principales/{label}_{os.path.basename(path)}")
        
        c = conn.cursor()
        c.execute("SELECT tipo_documento, path_archivo, nombre_archivo FROM documentos_embarque WHERE num_invoice = ?", (num_invoice,))
        extra_docs = c.fetchall()
        for tipo, path, name in extra_docs:
            if has_valid_file(path):
                safe_tipo = "".join(c for c in tipo if c.isalnum() or c in ('_', '-')).replace(' ', '_')
                zip_file.write(path, arcname=f"Anexos/{safe_tipo}/{name}")
                
    buffer.seek(0)
    return buffer

# -------------------------------------------------------------
# FUNCIONES DE TRACKING Y VISIBILIDAD LOGÍSTICA
# -------------------------------------------------------------
def get_tracking_info(naviera, num_contenedor, num_bl):
    cont = str(num_contenedor).strip().upper() if pd.notna(num_contenedor) else ""
    bl = str(num_bl).strip().upper() if pd.notna(num_bl) else ""
    nav = str(naviera).strip().upper() if pd.notna(naviera) else ""
    
    # Preferimos el Contenedor para rastreo naviero, si no existe usamos el BL
    ref = cont if cont and cont not in ['NONE', 'NAN', ''] else bl
    if not ref or ref in ['NONE', 'NAN', '']:
        return None, None, "⚠️ Sin Contenedor / BL asignado"

    encoded_ref = urllib.parse.quote(ref)
    
    # MSC
    if "MSC" in nav:
        url, label = f"https://www.msc.com/en/track-a-shipment?number={encoded_ref}", "🌐 Rastrear en MSC"
    
    # MAERSK
    elif "MAERSK" in nav:
        url, label = f"https://www.maersk.com/tracking/{encoded_ref}", "🌐 Rastrear en Maersk"
    
    # CMA CGM (URL actualizada para el nuevo portal de envíos)
    elif "CMA" in nav:
        url, label = f"https://www.cma-cgm.com/ebusiness/tracking/search?Reference={encoded_ref}", "🌐 Rastrear en CMA CGM"
    
    # HAPAG-LLOYD (URL actualizada de la Suite de Rastreo)
    elif "HAPAG" in nav:
        url, label = f"https://www.hapag-lloyd.com/en/online-business/track/tracking-beta.html?container={encoded_ref}", "🌐 Rastrear en Hapag-Lloyd"
    
    # ONE LINE
    elif "ONE" in nav:
        url, label = f"https://ecomm.one-line.com/one-ecom/cargo-tracking?searchType=C&number={encoded_ref}", "🌐 Rastrear en ONE Line"
    
    # COSCO SHIPPING
    elif "COSCO" in nav:
        url, label = f"https://lines.coscoshipping.com/ebusiness/cargo-tracking?type=CONTAINER_NO&number={encoded_ref}", "🌐 Rastrear en COSCO"
    
    # EVERGREEN
    elif "EVERGREEN" in nav:
        url, label = f"https://www.shipmentlink.com/tms/servlet/TDB1_CargoTracking.do?sel_type=CONTAINER&cntr_no={encoded_ref}", "🌐 Portal Evergreen"
    
    # OTRAS / DEFAULT (Rastreador Universal SeaRates)
    else:
        url, label = f"https://www.searates.com/container/tracking/?container={encoded_ref}", "🌐 Rastrear en SeaRates"

    return url, label, f"Ref: `{ref}` ({nav})"

def get_eta_status(eta_val, estatus_val):
    if pd.isna(eta_val) or str(eta_val).strip() in ['', 'None', 'nan', 'NaT']:
        return "⚪ **ETA:** No especificada", "info"
    
    eta_date = safe_parse_date(eta_val)
    today = date.today()
    diff = (eta_date - today).days
    estatus_clean = str(estatus_val).strip()

    if estatus_clean == "Entregado":
        return f"✅ **Estatus:** ENTREGADO el {eta_date.strftime('%d/%m/%Y')}", "success"
    elif diff < 0:
        return f"🚨 **¡EMBARQUE ATRASADO POR {abs(diff)} DÍA(S)!** (ETA era el {eta_date.strftime('%d/%m/%Y')})", "error"
    elif diff == 0:
        return f"🟡 **¡ARRIBO ESTIMADO HOY!** ({eta_date.strftime('%d/%m/%Y')})", "warning"
    elif diff <= 3:
        return f"🟡 **Arribo Inminente:** Faltan solo **{diff} día(s)** ({eta_date.strftime('%d/%m/%Y')})", "warning"
    else:
        return f"🟢 **Arribo a Tiempo:** Faltan **{diff} días** ({eta_date.strftime('%d/%m/%Y')})", "info"

def render_timeline(estatus_actual):
    st.caption("📍 **LÍNEA DE TIEMPO Y PROGRESO DEL EMBARQUE**")
    fases = [
        ("Pendiente Pago", "💳"), ("En Producción", "🏭"),
        ("En Tránsito", "🚢"), ("En Aduanas", "🛃"), ("Entregado", "📦")
    ]
    mapa_estatus = {
        "Pendiente Pago": 0, "En Producción": 1,
        "En Tránsito 1": 2, "En Tránsito 2": 2, "En Tránsito 3": 2,
        "En Aduanas": 3, "Entregado": 4
    }
    idx_actual = mapa_estatus.get(str(estatus_actual).strip(), 0)
    cols = st.columns(5)
    for i, (nombre_fase, icono) in enumerate(fases):
        with cols[i]:
            if i < idx_actual: st.success(f"✓ {icono} {nombre_fase}")
            elif i == idx_actual: st.info(f"📍 {icono} **{nombre_fase}**")
            else: st.caption(f"⚪ {icono} {nombre_fase}")

def generar_pdf_embarque(row_data, df_pagos):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#0F172A'))
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Heading2'], fontSize=11, leading=14, textColor=colors.HexColor('#0369A1'))
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=8.5, leading=11)
    header_cell_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=8.5, leading=11, textColor=colors.white, fontName='Helvetica-Bold')

    elements = [
        Paragraph(f"🚢 FICHA TÉCNICA DE EMBARQUE — INVOICE: {row_data['num_invoice']}", title_style),
        Paragraph(f"Generado el: {date.today().strftime('%d/%m/%Y')} | Departamento de Compras", body_style),
        Spacer(1, 10),
        Paragraph("📦 Datos Logísticos del Embarque", subtitle_style),
        Spacer(1, 4)
    ]

    data_logistica = [
        [Paragraph("<b>Estatus Actual:</b>", body_style), str(row_data['estatus']), Paragraph("<b>Línea Naviera:</b>", body_style), str(row_data['naviera'])],
        [Paragraph("<b>N° Contenedor:</b>", body_style), str(row_data['num_contenedor']), Paragraph("<b>N° BL:</b>", body_style), str(row_data['num_bl'])],
        [Paragraph("<b>Origen:</b>", body_style), str(row_data['origen']), Paragraph("<b>Destino:</b>", body_style), str(row_data['destino'])],
        [Paragraph("<b>ETA (Arribo):</b>", body_style), str(row_data['eta']), Paragraph("<b>Producto:</b>", body_style), str(row_data['producto'])]
    ]

    t1 = Table(data_logistica, colWidths=[110, 150, 110, 150])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.extend([t1, Spacer(1, 10), Paragraph("👥 Proveedor y Agentes Asignados", subtitle_style), Spacer(1, 4)])

    data_agentes = [
        [Paragraph("<b>Fabricante / Proveedor:</b>", body_style), str(row_data['fabricante'])],
        [Paragraph("<b>Consignatario:</b>", body_style), str(row_data['consignatario'])],
        [Paragraph("<b>Agente de Carga (FF):</b>", body_style), str(row_data['agente_carga'])],
        [Paragraph("<b>Agente de Aduanas:</b>", body_style), str(row_data['agente_aduanas'])]
    ]

    t2 = Table(data_agentes, colWidths=[150, 370])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.extend([t2, Spacer(1, 10), Paragraph("💰 Resumen Financiero (Fábrica y Flete)", subtitle_style), Spacer(1, 4)])

    monto_factura = float(row_data['monto_factura']) if pd.notna(row_data['monto_factura']) else 0.0
    df_fabrica = df_pagos[df_pagos['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos.empty else pd.DataFrame()
    monto_abonado_fabrica = df_fabrica['monto'].sum() if not df_fabrica.empty else 0.0
    saldo_pendiente_fabrica = monto_factura - monto_abonado_fabrica

    df_flete = df_pagos[df_pagos['tipo_pago'] == 'Pago a Freight Forwarder'] if not df_pagos.empty else pd.DataFrame()
    monto_flete_pagado = df_flete['monto'].sum() if not df_flete.empty else 0.0
    
    estatus_curr = str(row_data['estatus']).strip()
    if estatus_curr in ['Entregado', 'Pendiente Pago']:
        estado_flete_str = "No Aplica / Pagado"
    elif not df_flete.empty:
        estado_flete_str = "🟢 Flete Pagado"
    else:
        estado_flete_str = "PENDIENTE"

    data_finanzas = [
        [Paragraph("<b>FÁBRICA — Factura:</b>", body_style), f"${monto_factura:,.2f}",
         Paragraph("<b>Abonado:</b>", body_style), f"${monto_abonado_fabrica:,.2f}",
         Paragraph("<b>Saldo Pendiente:</b>", body_style), f"${saldo_pendiente_fabrica:,.2f}"],
        
        [Paragraph("<b>FLETE — Agente:</b>", body_style), Paragraph(str(row_data['agente_carga'] or 'N/A'), body_style),
         Paragraph("<b>Estatus:</b>", body_style), estado_flete_str,
         Paragraph("<b>Total Pagado Flete:</b>", body_style), f"${monto_flete_pagado:,.2f}"]
    ]

    t3 = Table(data_finanzas, colWidths=[100, 80, 80, 90, 90, 80])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E0F2FE')),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#FEF3C7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.extend([t3, Spacer(1, 10), Paragraph("<b>Historial Unificado de Pagos Registrados (Fábrica y Flete):</b>", body_style), Spacer(1, 4)])

    if df_pagos.empty:
        elements.append(Paragraph("<i>No existen pagos registrados para este embarque.</i>", body_style))
    else:
        table_data_pagos = [[Paragraph("Tipo Pago", header_cell_style), Paragraph("Banco", header_cell_style), Paragraph("Monto ($)", header_cell_style), Paragraph("Fecha", header_cell_style), Paragraph("Referencia", header_cell_style)]]
        for _, p in df_pagos.iterrows():
            table_data_pagos.append([
                Paragraph(str(p['tipo_pago']), body_style),
                Paragraph(str(p['banco']), body_style),
                Paragraph(f"${p['monto']:,.2f}", body_style),
                Paragraph(str(p['fecha_pago']), body_style),
                Paragraph(str(p['referencia']), body_style)
            ])
        t_pagos = Table(table_data_pagos, colWidths=[120, 100, 90, 80, 130])
        t_pagos.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_pagos)

    doc.build(elements)
    buffer.seek(0)
    return buffer

# Variables de Sesión
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "user_role" not in st.session_state: st.session_state.user_role = None
if "user_dept" not in st.session_state: st.session_state.user_dept = None
if "editing_invoice" not in st.session_state: st.session_state.editing_invoice = None

# --- LOGIN ---
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
    st.stop()

# --- NAVEGACIÓN ---
st.sidebar.title("🚢 Menú Principal")
st.sidebar.markdown(f"**Usuario:** {st.session_state.user_dept}")

role = st.session_state.user_role 

if role == "admin":
    options = [
        "📋 Control de Embarques", 
        "💳 Módulo de Pagos Internacionales",
        "📊 Carga Masiva (Excel/CSV)", 
        "➕ Cargar Nuevo Embarque", 
        "✏️ Editar / Actualizar Embarque"
    ]
else:
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

# --- VISTA 1: CONTROL DE EMBARQUES ---
if menu == "📋 Control de Embarques":
    st.title("📋 Control General de Embarques")
    st.caption("Visualización interactiva, búsqueda en tiempo real y gestión de archivos")
    
    df = pd.read_sql_query("SELECT * FROM embarques", conn)
    df_pagos_all = pd.read_sql_query("SELECT num_invoice, tipo_pago FROM pagos_embarques", conn)
    
    if df.empty:
        st.info("No hay embarques registrados aún.")
    else:
        invoices_con_pago_ff = df_pagos_all[df_pagos_all['tipo_pago'] == 'Pago a Freight Forwarder']['num_invoice'].unique() if not df_pagos_all.empty else []

        def check_pago_ff(row):
            estatus = str(row['estatus']).strip()
            inv = row['num_invoice']
            if estatus in ['Entregado', 'Pendiente Pago']:
                return '✅ No Aplica / Pagado'
            elif inv in invoices_con_pago_ff:
                return '🟢 Flete Pagado'
            else:
                return '⚠️ PENDIENTE FLETE'

        df['pago_flete_status'] = df.apply(check_pago_ff, axis=1)

        with st.expander("🔍 **Buscador y Filtros Avanzados**", expanded=True):
            col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1, 1, 1])
            with col_f1: search_term = st.text_input("🔎 Búsqueda Global", placeholder="Escribe N° Invoice, Contenedor, BL, Fabricante o Producto...", key="search_global")
            with col_f2: filtro_estatus = st.selectbox("Estatus del Embarque", ["Todos"] + ESTATUS_LISTA, index=0)
            with col_f3: filtro_naviera = st.selectbox("Línea Naviera", ["Todas"] + NAVIERAS, index=0)
            with col_f4: filtro_flete = st.selectbox("Estado del Flete", ["Todos", "⚠️ PENDIENTE FLETE", "🟢 Flete Pagado", "✅ No Aplica / Pagado"], index=0) if role == "admin" else "Todos"

        df_filtered = df.copy()

        if search_term:
            term = search_term.lower().strip()
            mask = (
                df_filtered['num_invoice'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['num_contenedor'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['num_bl'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['fabricante'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['producto'].astype(str).str.lower().str.contains(term, na=False)
            )
            df_filtered = df_filtered[mask]

        if filtro_estatus != "Todos": df_filtered = df_filtered[df_filtered['estatus'] == filtro_estatus]
        if filtro_naviera != "Todas": df_filtered = df_filtered[df_filtered['naviera'] == filtro_naviera]
        if role == "admin" and filtro_flete != "Todos": df_filtered = df_filtered[df_filtered['pago_flete_status'] == filtro_flete]

        st.caption(f"📊 Mostrando **{len(df_filtered)}** de **{len(df)}** embarque(s) registrado(s).")

        if df_filtered.empty:
            st.warning("⚠️ No se encontraron embarques que coincidan con los criterios de búsqueda.")
        else:
            def highlight_status(val):
                val_clean = str(val).strip().lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
                if val_clean == 'entregado': return 'background-color: #F8D7DA; color: #721C24; font-weight: bold;'
                elif 'pendiente pago' in val_clean: return 'background-color: #E2E8F0; color: #334155; font-weight: bold;'
                elif 'produccion' in val_clean: return 'background-color: #E0F2FE; color: #0369A1; font-weight: bold;'
                elif 'transito 1' in val_clean: return 'background-color: #E2E8F0; color: #475569; font-weight: bold;'
                elif 'transito 2' in val_clean: return 'background-color: #D4EDDA; color: #155724; font-weight: bold;'
                elif 'transito 3' in val_clean: return 'background-color: #FEF3C7; color: #92400E; font-weight: bold;'
                elif 'aduana' in val_clean: return 'background-color: #FFF3CD; color: #856404; font-weight: bold;'
                return ''

            def highlight_flete(val):
                if 'PENDIENTE' in str(val): return 'background-color: #FFE1A8; color: #854D0E; font-weight: bold;'
                elif 'Pagado' in str(val): return 'background-color: #D1FAE5; color: #065F46; font-weight: bold;'
                return ''

            cols_to_show = ['num_invoice', 'num_contenedor', 'num_bl', 'naviera', 'fabricante', 'producto', 'origen', 'destino', 'eta', 'estatus'] + (['pago_flete_status'] if role == "admin" else [])
            cols_names = ['N° Invoice', 'Contenedor', 'N° BL', 'Línea Naviera', 'Fabricante', 'Producto', 'Origen', 'Destino', 'ETA (Arribo)', 'Estatus'] + (['Estado Flete'] if role == "admin" else [])

            df_display = df_filtered[cols_to_show].copy()
            df_display.columns = cols_names

            styled_df = df_display.style.map(highlight_status, subset=['Estatus'])
            if role == "admin": styled_df = styled_df.map(highlight_flete, subset=['Estado Flete'])

            st.info("💡 **Tip:** Haz clic sobre cualquier fila para seleccionar un embarque y ver sus detalles.")
            
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

                render_timeline(row_data['estatus'])

                eta_msg, eta_type = get_eta_status(row_data['eta'], row_data['estatus'])
                if eta_type == "error": st.error(eta_msg)
                elif eta_type == "warning": st.warning(eta_msg)
                elif eta_type == "success": st.success(eta_msg)
                else: st.info(eta_msg)

# TRACKING DIRECTO
st.markdown("##### 📡 Rastreo de Carga en Tiempo Real")
url_track, label_track, info_ref = get_tracking_info(row_data['naviera'], row_data['num_contenedor'], row_data['num_bl'])
ref_val = row_data['num_contenedor'] if pd.notna(row_data['num_contenedor']) and str(row_data['num_contenedor']).strip() not in ['', 'None', 'nan'] else row_data['num_bl']

st.caption(f"Línea Naviera: **{row_data['naviera'] or 'No especificada'}** | {info_ref}")

c_track1, c_track2 = st.columns(2)

with c_track1:
    if url_track:
        st.link_button(label=label_track, url=url_track, type="primary", use_container_width=True)
    else:
        st.button("🚫 Sin datos para rastrear", disabled=True, use_container_width=True)

with c_track2:
    if ref_val and str(ref_val).strip() not in ['', 'None', 'nan']:
        # Rastreador universal como respaldo 100% garantizado
        url_searates = f"https://www.searates.com/container/tracking/?container={urllib.parse.quote(str(ref_val).strip())}"
        st.link_button(label="🔍 Rastreo Universal (SeaRates)", url=url_searates, type="secondary", use_container_width=True)


                # =============================================================
                # 1. ROL ALMACÉN (ACCESO DOCUMENTAL Y OPERATIVO RESTRINGIDO)
                # =============================================================
                if role == "almacen":
                    st.subheader("📦 Módulo de Gestión de Almacén")
                    
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

                    if row_data['estatus'] == "En Aduanas":
                        st.markdown("---")
                        st.info("💡 **Acción disponible:** Puede marcar este embarque como 'Entregado' al recibirlo en almacén.")
                        if st.button("✅ Marcar como ENTREGADO", type="primary"):
                            c = conn.cursor()
                            c.execute("UPDATE embarques SET estatus = 'Entregado' WHERE num_invoice = ?", (selected_invoice,))
                            conn.commit()
                            st.success("¡Estatus actualizado a 'Entregado' con éxito!")
                            st.rerun()

                    st.markdown("---")
                    if row_data['estatus'] == "Entregado":
                        st.subheader("📸 Cargar Fotos / Reporte de Descarga")
                        with st.form(f"form_almacen_upload_{selected_invoice}"):
                            uploaded_descarga_files = st.file_uploader(
                                "Subir Fotos o Reporte de Descarga (Múltiples archivos permitidos)", 
                                accept_multiple_files=True,
                                key=f"upload_almacen_files_{selected_invoice}"
                            )
                            sub_almacen = st.form_submit_button("📤 Subir Fotos de Descarga", type="primary")
                            if sub_almacen and uploaded_descarga_files:
                                c = conn.cursor()
                                for f_up in uploaded_descarga_files:
                                    f_path, f_name = save_extra_file(f_up, selected_invoice, "Fotos de Descarga")
                                    c.execute('''
                                        INSERT INTO documentos_embarque (num_invoice, tipo_documento, nombre_archivo, path_archivo, fecha_subida, subido_por)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                    ''', (selected_invoice, "Fotos de Descarga", f_name, f_path, str(date.today()), "Almacén"))
                                conn.commit()
                                st.success("✅ Fotos/Archivos de descarga guardados con éxito.")
                                st.rerun()
                    else:
                        st.info("🔒 **Carga de Fotos de Descarga Inactiva:** La opción para subir fotos se habilitará cuando el embarque sea marcado como **'Entregado'**.")

                    df_fotos_almacen = pd.read_sql_query(
                        "SELECT * FROM documentos_embarque WHERE num_invoice = ? AND tipo_documento = 'Fotos de Descarga'", 
                        conn, params=(selected_invoice,)
                    )
                    if not df_fotos_almacen.empty:
                        st.markdown("##### 📸 Fotos y Reportes de Descarga Registrados:")
                        for idx_f, f_row in df_fotos_almacen.iterrows():
                            c_f1, c_f2, c_f3 = st.columns([3, 2, 1])
                            c_f1.write(f"📄 {f_row['nombre_archivo']}")
                            c_f2.caption(f"📅 {f_row['fecha_subida']}")
                            with c_f3:
                                if has_valid_file(f_row['path_archivo']):
                                    with open(f_row['path_archivo'], "rb") as f_img:
                                        st.download_button(
                                            label="⬇️ Descargar",
                                            data=f_img,
                                            file_name=f_row['nombre_archivo'],
                                            mime="application/octet-stream",
                                            key=f"dl_alm_{f_row['id']}"
                                        )

                # =============================================================
                # 2. ROL ADMINISTRACIÓN (4 DOCUMENTOS PRINCIPALES SOLAMENTE)
                # =============================================================
                elif role == "admon":
                    st.subheader("💼 Expediente Digital del Embarque")
                    docs_principales = [
                        ("Packing List", row_data['path_packing']),
                        ("Factura Comercial (Invoice)", row_data['path_invoice']),
                        ("Factura de Flete", row_data['path_flete']),
                        ("Bill of Lading (BL)", row_data['path_bl'])
                    ]
                    col_d1, col_d2 = st.columns(2)
                    for idx, (label, path) in enumerate(docs_principales):
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

                # =============================================================
                # 3. ROL COMPRAS (ADMINISTRADOR COMPLETO)
                # =============================================================
                elif role == "admin":
                    # Alertas de Flete
                    es_omito_flete = (str(row_data['estatus']).strip() in ["Entregado", "Pendiente Pago"])
                    tiene_pago_ff = selected_invoice in invoices_con_pago_ff
                    if not es_omito_flete and not tiene_pago_ff:
                        st.warning(f"⚠️ **ALERTA DE FLETE:** Este embarque se encuentra **'{row_data['estatus']}'** y **AÚN NO TIENE REGISTRADO EL PAGO AL FREIGHT FORWARDER**.")
                    elif tiene_pago_ff:
                        st.success("🟢 **Flete Registrado:** El pago al Freight Forwarder ya fue registrado correctamente.")

                    st.subheader("💼 Expediente Digital del Embarque (Documentos Principales)")
                    docs_principales = [
                        ("Packing List", row_data['path_packing']),
                        ("Factura Comercial (Invoice)", row_data['path_invoice']),
                        ("Factura de Flete", row_data['path_flete']),
                        ("Bill of Lading (BL)", row_data['path_bl'])
                    ]
                    col_d1, col_d2 = st.columns(2)
                    for idx, (label, path) in enumerate(docs_principales):
                        col_target = col_d1 if idx % 2 == 0 else col_d2
                        with col_target:
                            if has_valid_file(path):
                                with open(path, "rb") as f:
                                    st.download_button(
                                        label=f"⬇️ Descargar {label}",
                                        data=f,
                                        file_name=os.path.basename(path),
                                        mime="application/octet-stream",
                                        key=f"main_admin_{label}_{selected_invoice}"
                                    )
                            else:
                                st.caption(f"❌ {label}: No cargado")

                    st.markdown("---")
                    
                    # -------------------------------------------------------------
                    # EXPEDIENTE ANEXO PLEGABLE Y COMPACTO (MEJORA DE UX)
                    # -------------------------------------------------------------
                    df_extra_docs = pd.read_sql_query("SELECT * FROM documentos_embarque WHERE num_invoice = ?", conn, params=(selected_invoice,))
                    cant_anexos = len(df_extra_docs)
                    
                    with st.expander(f"📁 **Expediente Anexo y Documentación Adicional** ({cant_anexos} archivo(s) cargado(s))", expanded=False):
                        st.markdown("##### ➕ Adjuntar Nuevos Documentos")
                        with st.form(f"form_extra_docs_{selected_invoice}"):
                            c_exp1, c_exp2 = st.columns(2)
                            with c_exp1:
                                tipo_doc_sel = st.selectbox("Tipo / Categoría de Documento *", TIPOS_DOCS_COMPRAS, key=f"sel_tipo_doc_{selected_invoice}")
                            with c_exp2:
                                extra_files = st.file_uploader("Seleccionar Archivo(s) *", accept_multiple_files=True, key=f"uploader_extra_{selected_invoice}")

                            btn_subir_extra = st.form_submit_button("📤 Guardar Documentos en Expediente", type="primary", use_container_width=True)

                            if btn_subir_extra:
                                if not extra_files:
                                    st.error("❌ Debe seleccionar al menos un archivo.")
                                else:
                                    c = conn.cursor()
                                    for ef in extra_files:
                                        e_path, e_name = save_extra_file(ef, selected_invoice, tipo_doc_sel)
                                        c.execute('''
                                            INSERT INTO documentos_embarque (num_invoice, tipo_documento, nombre_archivo, path_archivo, fecha_subida, subido_por)
                                            VALUES (?, ?, ?, ?, ?, ?)
                                        ''', (selected_invoice, tipo_doc_sel, e_name, e_path, str(date.today()), st.session_state.user_dept))
                                    conn.commit()
                                    st.success(f"✅ ¡{len(extra_files)} documento(s) adjuntado(s) exitosamente como '{tipo_doc_sel}'!")
                                    st.rerun()

                        st.divider()

                        # Listado de Anexos
                        if not df_extra_docs.empty:
                            st.markdown("##### 📄 Archivos Anexos Registrados en este Embarque:")
                            for idx_doc, doc_row in df_extra_docs.iterrows():
                                c_doc1, c_doc2, c_doc3, c_doc4 = st.columns([2, 3, 2, 1])
                                c_doc1.write(f"🏷️ **{doc_row['tipo_documento']}**")
                                c_doc2.write(f"📄 {doc_row['nombre_archivo']}")
                                c_doc3.caption(f"📅 {doc_row['fecha_subida']} ({doc_row['subido_por']})")
                                
                                with c_doc4:
                                    if has_valid_file(doc_row['path_archivo']):
                                        with open(doc_row['path_archivo'], "rb") as f_ex:
                                            st.download_button(
                                                label="⬇️ Descargar",
                                                data=f_ex,
                                                file_name=doc_row['nombre_archivo'],
                                                mime="application/octet-stream",
                                                key=f"dl_extra_{doc_row['id']}"
                                            )
                                    else:
                                        st.caption("Archivo no hallado")
                                    
                                    if st.button("🗑️", key=f"del_extra_{doc_row['id']}", help="Eliminar este archivo"):
                                        c = conn.cursor()
                                        c.execute("DELETE FROM documentos_embarque WHERE id = ?", (doc_row['id'],))
                                        conn.commit()
                                        st.success("Documento eliminado.")
                                        st.rerun()
                                st.divider()
                        else:
                            st.info("No hay documentos anexos adjuntados para este embarque aún.")

                        # Botón Descarga ZIP
                        st.markdown("##### 📦 Descarga Masiva del Expediente")
                        zip_buffer = generar_zip_expediente(selected_invoice, row_data, conn)
                        st.download_button(
                            label=f"📦 Descargar Expediente COMPLETO en .ZIP ({selected_invoice})",
                            data=zip_buffer,
                            file_name=f"Expediente_Completo_{selected_invoice}.zip",
                            mime="application/zip",
                            type="primary",
                            use_container_width=True,
                            key=f"btn_zip_{selected_invoice}"
                        )

                    # BALANCE FINANCIERO FÁBRICA
                    st.markdown("---")
                    st.subheader(f"💰 Balance Financiero de Fábrica ({selected_invoice})")
                    df_pagos_emb = pd.read_sql_query("SELECT * FROM pagos_embarques WHERE num_invoice = ?", conn, params=(selected_invoice,))
                    df_pagos_fabrica = df_pagos_emb[df_pagos_emb['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos_emb.empty else pd.DataFrame()
                    
                    monto_total_pagado_fabrica = df_pagos_fabrica['monto'].sum() if not df_pagos_fabrica.empty else 0.0
                    monto_factura = float(row_data['monto_factura']) if pd.notna(row_data['monto_factura']) else 0.0
                    saldo_pendiente = monto_factura - monto_total_pagado_fabrica

                    m1, m2 = st.columns(2)
                    m1.metric("Monto Total Factura (Fábrica)", f"${monto_factura:,.2f} USD")
                    m2.metric("Total Abonado a Fábrica", f"${monto_total_pagado_fabrica:,.2f} USD")
                    
                    if saldo_pendiente <= 0 and monto_factura > 0:
                        st.success("🟢 **Saldo Pendiente Fábrica:** $0.00 USD — ¡PAGADO COMPLETAMENTE!")
                    elif saldo_pendiente > 0:
                        st.error(f"🔴 **Saldo Pendiente por Pagar a Fábrica:** ${saldo_pendiente:,.2f} USD")
                    else:
                        st.info("⚪ **Saldo Pendiente por Pagar a Fábrica:** $0.00 USD")

                    st.markdown("---")
                    if df_pagos_emb.empty:
                        st.info("No se han registrado pagos o abonos para este embarque.")
                    else:
                        st.markdown("##### 📄 Historial de Pagos y Comprobantes Registrados:")
                        for idx, p_row in df_pagos_emb.iterrows():
                            c_p1, c_p2, c_p3, c_p4 = st.columns([2, 2, 2, 2])
                            badge = "🏭" if p_row['tipo_pago'] == 'Pago a Fábrica' else "🚢"
                            c_p1.write(f"**Tipo:** {badge} {p_row['tipo_pago']}")
                            c_p2.write(f"**Banco:** {p_row['banco']}")
                            c_p3.write(f"**Monto:** ${p_row['monto']:,.2f} USD")
                            c_p4.write(f"**Ref:** {p_row['referencia']} ({p_row['fecha_pago']})")
                            
                            if has_valid_file(p_row['path_comprobante']):
                                with open(p_row['path_comprobante'], "rb") as f_comp:
                                    st.download_button(label=f"📄 Ver Comprobante #{p_row['referencia']}", data=f_comp, file_name=os.path.basename(p_row['path_comprobante']), mime="application/octet-stream", key=f"dl_pago_{p_row['id']}")
                            st.divider()

                    st.markdown("---")
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        if st.button(f"✏️ Desplegar Edición Rápida ({selected_invoice})", type="primary", use_container_width=True):
                            st.session_state.editing_invoice = selected_invoice

                    with col_b2:
                        pdf_data = generar_pdf_embarque(row_data, df_pagos_emb)
                        st.download_button(label=f"📄 Imprimir Ficha PDF ({selected_invoice})", data=pdf_data, file_name=f"Ficha_Embarque_{selected_invoice}.pdf", mime="application/pdf", type="secondary", use_container_width=True, key=f"btn_pdf_{selected_invoice}")

        # FORMULARIO DE EDICIÓN RÁPIDA
        if role == "admin" and st.session_state.editing_invoice:
            st.markdown("---")
            st.subheader(f"🛠️ Editando Embarque: {st.session_state.editing_invoice}")
            row_data = df[df['num_invoice'] == st.session_state.editing_invoice].iloc[0]
            
            with st.form("form_quick_edit"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.text_input("Número de Invoice", value=str(row_data['num_invoice']), disabled=True)
                    fabricante_e = st.text_input("Fabricante / Proveedor", value=str(row_data['fabricante'] or ''))
                    monto_factura_e = st.number_input("Monto Total Factura ($ USD)", min_value=0.0, value=float(row_data['monto_factura'] or 0.0), step=100.0, format="%.2f")
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
                        path_packing = ?, path_invoice = ?, path_flete = ?, path_bl = ?,
                        monto_factura = ?
                    WHERE num_invoice = ?
                ''', (origen_e, destino_e, fabricante_e, agente_carga_e,
                      agente_aduanas_e, consignatario_e, producto_e, num_bl_e,
                      naviera_e, num_contenedor_e, str(eta_e), estatus_e,
                      p_pack, p_inv, p_fle, p_bl, monto_factura_e, st.session_state.editing_invoice))
                conn.commit()
                st.session_state.editing_invoice = None
                st.success("✅ ¡Embarque actualizado con éxito!")
                st.rerun()

# --- MENÚ 2: PAGOS INTERNACIONALES ---
elif "Pagos Internacionales" in menu:
    st.title("💳 Registro y Control de Pagos Internacionales")
    st.caption("Módulo exclusivo para Compras: Administra, modifica y elimina transferencias realizadas")

    df_emb = pd.read_sql_query("SELECT num_invoice, fabricante, num_contenedor, monto_factura, estatus FROM embarques", conn)
    
    if df_emb.empty:
        st.warning("⚠️ Primero debe registrar al menos un embarque para asignarle pagos.")
    else:
        invoices_map = {row['num_invoice']: f"{row['num_invoice']} - {row['fabricante']} (Contenedor: {row['num_contenedor']})" for _, row in df_emb.iterrows()}
        tab_nuevo, tab_editar = st.tabs(["➕ Registrar Nuevo Pago", "✏️ Editar / Eliminar Pago Existente"])

        with tab_nuevo:
            st.subheader("➕ Registrar Nuevo Abono / Pago")
            with st.form("form_registrar_pago", clear_on_submit=True):
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    selected_inv_key = st.selectbox("Seleccione Embarque / Invoice *", list(invoices_map.keys()), format_func=lambda x: invoices_map[x], key="new_pago_inv")
                    tipo_pago = st.selectbox("Tipo de Pago *", TIPO_PAGO_LISTA, key="new_pago_tipo")
                    banco_pago = st.selectbox("Banco / Plataforma de Origen *", BANCOS_LISTA, key="new_pago_banco")
                    monto_pago = st.number_input("Monto del Abono ($ USD) *", min_value=0.01, step=100.0, format="%.2f", key="new_pago_monto")
                with col_p2:
                    fecha_pago = st.date_input("Fecha de Transferencia", value=date.today(), key="new_pago_fecha")
                    num_ref = st.text_input("Número de Referencia / Comprobante *", key="new_pago_ref")
                    file_comprobante = st.file_uploader("Subir Comprobante (JPG, PNG, PDF) *", type=["png", "jpg", "jpeg", "pdf"], key="new_pago_file")

                submit_pago = st.form_submit_button("💳 Registrar Pago / Abono", type="primary", use_container_width=True)

                if submit_pago:
                    if not num_ref or file_comprobante is None or monto_pago <= 0:
                        st.error("❌ Todos los campos marcados con (*) son obligatorios, incluyendo el comprobante.")
                    else:
                        ref_clean = "".join(c for c in num_ref if c.isalnum() or c in ('-', '_'))
                        file_path_pago = save_file(file_comprobante, f"{selected_inv_key}_{ref_clean}", "COMPROBANTE", is_payment=True)
                        
                        c = conn.cursor()
                        c.execute('''
                            INSERT INTO pagos_embarques (num_invoice, tipo_pago, banco, monto, fecha_pago, referencia, path_comprobante)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (selected_inv_key, tipo_pago, banco_pago, monto_pago, str(fecha_pago), num_ref, file_path_pago))
                        
                        if tipo_pago == "Pago a Fábrica":
                            c.execute("SELECT estatus FROM embarques WHERE num_invoice = ?", (selected_inv_key,))
                            estatus_actual = c.fetchone()[0]
                            if estatus_actual == "Pendiente Pago":
                                c.execute("UPDATE embarques SET estatus = 'En Producción' WHERE num_invoice = ?", (selected_inv_key,))
                                st.info("ℹ️ **Estatus Actualizado:** El embarque cambió automáticamente de 'Pendiente Pago' a **'En Producción'**.")

                        conn.commit()
                        st.success(f"✅ Pago ({tipo_pago}) de ${monto_pago:,.2f} USD registrado con éxito para la Invoice {selected_inv_key}.")
                        st.rerun()

        with tab_editar:
            st.subheader("🛠️ Modificar o Eliminar un Pago Registrado")
            df_all_pagos = pd.read_sql_query("SELECT * FROM pagos_embarques ORDER BY id DESC", conn)

            if df_all_pagos.empty:
                st.info("No hay pagos registrados para modificar.")
            else:
                pagos_map = {row['id']: f"ID #{row['id']} | Inv: {row['num_invoice']} | [{row['tipo_pago']}] | Ref: {row['referencia']} | Monto: ${row['monto']:,.2f} USD" for _, row in df_all_pagos.iterrows()}
                selected_pago_id = st.selectbox("Selecciona el pago que deseas modificar o eliminar:", list(pagos_map.keys()), format_func=lambda x: pagos_map[x])
                pago_row = df_all_pagos[df_all_pagos['id'] == selected_pago_id].iloc[0]

                with st.form("form_edit_pago"):
                    st.info(f"Editando Registro de Pago **ID #{selected_pago_id}** (Invoice: **{pago_row['num_invoice']}**)")
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        tipo_pago_edit = st.selectbox("Tipo de Pago", TIPO_PAGO_LISTA, index=TIPO_PAGO_LISTA.index(pago_row['tipo_pago']) if pago_row['tipo_pago'] in TIPO_PAGO_LISTA else 0)
                        banco_pago_edit = st.selectbox("Banco de Origen", BANCOS_LISTA, index=BANCOS_LISTA.index(pago_row['banco']) if pago_row['banco'] in BANCOS_LISTA else 0)
                        monto_pago_edit = st.number_input("Monto del Abono ($ USD)", min_value=0.01, value=float(pago_row['monto']), step=100.0, format="%.2f")
                    with col_e2:
                        fecha_pago_edit = st.date_input("Fecha del Pago", value=safe_parse_date(pago_row['fecha_pago']))
                        num_ref_edit = st.text_input("Número de Referencia", value=str(pago_row['referencia'] or ''))
                        file_comp_edit = st.file_uploader("Reemplazar Comprobante (Opcional)", type=["png", "jpg", "jpeg", "pdf"])

                    col_b1, col_b2 = st.columns(2)
                    with col_b1: submit_pago_edit = st.form_submit_button("💾 Guardar Cambios en Pago", type="primary", use_container_width=True)
                    with col_b2: delete_pago = st.form_submit_button("🗑️ ELIMINAR ESTE PAGO", type="secondary", use_container_width=True)

                if submit_pago_edit:
                    if not num_ref_edit or monto_pago_edit <= 0:
                        st.error("❌ El monto debe ser mayor a 0 y la referencia no puede estar vacía.")
                    else:
                        new_path = save_file(file_comp_edit, f"{pago_row['num_invoice']}_{num_ref_edit}", "COMPROBANTE", is_payment=True) or pago_row['path_comprobante']
                        c = conn.cursor()
                        c.execute('''
                            UPDATE pagos_embarques SET tipo_pago = ?, banco = ?, monto = ?, fecha_pago = ?, referencia = ?, path_comprobante = ? WHERE id = ?
                        ''', (tipo_pago_edit, banco_pago_edit, monto_pago_edit, str(fecha_pago_edit), num_ref_edit, new_path, selected_pago_id))
                        conn.commit()
                        st.success(f"✅ ¡El pago ID #{selected_pago_id} ha sido actualizado correctamente!")
                        st.rerun()

                if delete_pago:
                    c = conn.cursor()
                    c.execute("DELETE FROM pagos_embarques WHERE id = ?", (selected_pago_id,))
                    conn.commit()
                    st.warning(f"🗑️ El pago ID #{selected_pago_id} ha sido eliminado.")
                    st.rerun()

        st.markdown("---")
        st.subheader("📊 Historial General de Pagos Registrados")
        df_all_pagos = pd.read_sql_query("SELECT * FROM pagos_embarques ORDER BY id DESC", conn)
        if df_all_pagos.empty:
            st.info("No se registra ningún pago en el sistema.")
        else:
            st.dataframe(df_all_pagos[['id', 'num_invoice', 'tipo_pago', 'banco', 'monto', 'fecha_pago', 'referencia']], use_container_width=True, hide_index=True)

# --- MENÚ 3: CARGA MASIVA ---
elif menu == "📊 Carga Masiva (Excel/CSV)" and role == "admin":
    st.title("📊 Carga Masiva de Embarques")
    sample_data = pd.DataFrame([{
        "num_invoice": "INV-1001", "num_bl": "BL-998877", "num_contenedor": "MSCU1234567",
        "naviera": "MSC", "fabricante": "Tech Corp", "producto": "Lámparas LED",
        "origen": "China", "destino": "Venezuela", "eta": "2026-08-15",
        "estatus": "Pendiente Pago", "agente_carga": "DHL", "agente_aduanas": "Aduanas C.A.",
        "consignatario": "Industrias Orgatek", "monto_factura": 25000.00
    }])
    csv_sample = sample_data.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Descargar Plantilla de Ejemplo (CSV)", csv_sample, "plantilla_embarques.csv", "text/csv")
    st.markdown("---")
    uploaded_file = st.file_uploader("Selecciona tu archivo Excel (.xlsx) o CSV", type=["xlsx", "csv"])

    if uploaded_file is not None:
        try:
            df_upload = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            df_upload.columns = df_upload.columns.str.strip().str.lower()
            col_map = {'invoice': 'num_invoice', 'empresa': 'fabricante', 'agente': 'agente_carga', 'ag aduana': 'agente_aduanas', 'consignee': 'consignatario', 'estimado': 'eta', 'org /bl / booking': 'num_bl', 'monto': 'monto_factura'}
            df_upload.rename(columns=col_map, inplace=True)
            st.dataframe(df_upload.head(10), use_container_width=True)

            if 'num_invoice' in df_upload.columns and st.button("🚀 Procesar e Importar a Base de Datos", type="primary"):
                c = conn.cursor()
                n_up, n_new = 0, 0
                for _, row in df_upload.iterrows():
                    inv = str(row.get('num_invoice', '')).strip()
                    if not inv or inv == 'nan': continue
                    bl = str(row.get('num_bl', '')) if pd.notna(row.get('num_bl')) else ''
                    cont = str(row.get('num_contenedor', '')) if pd.notna(row.get('num_contenedor')) else ''
                    nav = str(row.get('naviera', '')) if pd.notna(row.get('naviera')) else ''
                    fab = str(row.get('fabricante', '')) if pd.notna(row.get('fabricante')) else ''
                    prod = str(row.get('producto', '')) if pd.notna(row.get('producto')) else ''
                    ori = str(row.get('origen', 'China')) if pd.notna(row.get('origen')) else 'China'
                    des = str(row.get('destino', 'Venezuela')) if pd.notna(row.get('destino')) else 'Venezuela'
                    eta = str(row.get('eta', '')) if pd.notna(row.get('eta')) else ''
                    est = str(row.get('estatus', 'Pendiente Pago')) if pd.notna(row.get('estatus')) else 'Pendiente Pago'
                    ag_c = str(row.get('agente_carga', '')) if pd.notna(row.get('agente_carga')) else ''
                    ag_a = str(row.get('agente_aduanas', '')) if pd.notna(row.get('agente_aduanas')) else ''
                    cons = str(row.get('consignatario', '')) if pd.notna(row.get('consignatario')) else ''
                    monto = float(row.get('monto_factura', 0.0)) if pd.notna(row.get('monto_factura')) else 0.0

                    c.execute("SELECT id FROM embarques WHERE num_invoice = ?", (inv,))
                    if c.fetchone():
                        c.execute('''UPDATE embarques SET num_bl=?, num_contenedor=?, naviera=?, fabricante=?, producto=?, origen=?, destino=?, eta=?, estatus=?, agente_carga=?, agente_aduanas=?, consignatario=?, monto_factura=? WHERE num_invoice=?''', (bl, cont, nav, fab, prod, ori, des, eta, est, ag_c, ag_a, cons, monto, inv))
                        n_up += 1
                    else:
                        c.execute('''INSERT INTO embarques (num_invoice, num_bl, num_contenedor, naviera, fabricante, producto, origen, destino, eta, estatus, agente_carga, agente_aduanas, consignatario, monto_factura) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (inv, bl, cont, nav, fab, prod, ori, des, eta, est, ag_c, ag_a, cons, monto))
                        n_new += 1
                conn.commit()
                st.success(f"✅ Éxito: {n_new} nuevos registros, {n_up} actualizados.")
        except Exception as e:
            st.error(f"Error procesando archivo: {e}")

# --- MENÚ 4: REGISTRO MANUAL ---
elif menu == "➕ Cargar Nuevo Embarque" and role == "admin":
    st.title("➕ Registrar Nuevo Embarque Manual")
    with st.form("form_embarque", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            num_invoice = st.text_input("Número de Invoice *")
            fabricante = st.text_input("Fabricante / Proveedor")
            monto_factura = st.number_input("Monto Total Factura ($ USD)", min_value=0.0, step=100.0, format="%.2f")
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
            estatus = st.selectbox("Estatus Inicial", ESTATUS_LISTA, index=0)
        
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
                    c.execute('''INSERT INTO embarques (origen, destino, fabricante, num_invoice, agente_carga, agente_aduanas, consignatario, producto, num_bl, naviera, num_contenedor, eta, estatus, path_packing, path_invoice, path_flete, path_bl, monto_factura) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (origen, destino, fabricante, num_invoice, agente_carga, agente_aduanas, consignatario, producto, num_bl, naviera, num_contenedor, str(eta), estatus, p_pack, p_inv, p_fle, p_bl, monto_factura))
                    conn.commit()
                    st.success(f"Embarque Invoice {num_invoice} registrado en estatus '{estatus}'.")
                except sqlite3.IntegrityError:
                    st.error(f"❌ La Invoice {num_invoice} ya existe.")

# --- MENÚ 5: EDITAR EMBARQUE ---
elif menu == "✏️ Editar / Actualizar Embarque" and role == "admin":
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
                monto_factura_edit = st.number_input("Monto Total Factura ($ USD)", min_value=0.0, value=float(row['monto_factura'] or 0.0), step=100.0, format="%.2f")
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
                c.execute('''UPDATE embarques SET origen=?, destino=?, fabricante=?, agente_carga=?, agente_aduanas=?, consignatario=?, producto=?, num_bl=?, naviera=?, num_contenedor=?, eta=?, estatus=?, path_packing=?, path_invoice=?, path_flete=?, path_bl=?, monto_factura=? WHERE num_invoice=?''', (origen_edit, destino_edit, fabricante_edit, agente_carga_edit, agente_aduanas_edit, consignatario_edit, producto_edit, num_bl_edit, naviera_edit, num_contenedor_edit, str(eta_edit), estatus_edit, p_pack, p_inv, p_fle, p_bl, monto_factura_edit, selected_invoice))
                conn.commit()
                st.success(f"✅ Embarque Invoice {selected_invoice} actualizado.")

conn.close()
