import streamlit as st
import pandas as pd
import io
import urllib.parse
import zipfile
import requests
from datetime import date, datetime
from supabase import create_client, Client

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
# CONEXIÓN A SUPABASE
# -------------------------------------------------------------
SUPABASE_URL = "https://drletxlyrnraprqierrr.supabase.co"
SUPABASE_KEY = "sb_publishable_4ZcWovp88QQvCRgMBNFqWQ_UbKLOH2v"

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# -------------------------------------------------------------
# FUNCIONES DE CONFIGURACIÓN GLOBAL Y CATÁLOGOS
# -------------------------------------------------------------
def get_maintenance_mode():
    try:
        res = supabase.table("app_config").select("value").eq("key", "modo_mantenimiento").execute()
        if res.data and len(res.data) > 0:
            val = str(res.data[0].get("value", "")).lower().strip()
            return val in ["true", "1", "yes", "si"]
    except Exception:
        pass
    return False

def set_maintenance_mode(is_active: bool):
    try:
        val_str = "true" if is_active else "false"
        supabase.table("app_config").upsert({"key": "modo_mantenimiento", "value": val_str}).execute()
    except Exception as e:
        st.error(f"Error actualizando Modo Mantenimiento en Supabase: {e}")

# Funciones de consulta de catálogos
def get_catalogo_proveedores(tipo_filtro=None):
    try:
        query = supabase.table("catalogo_proveedores").select("*")
        if tipo_filtro:
            query = query.eq("tipo", tipo_filtro)
        res = query.order("nombre").execute()
        return res.data if res.data else []
    except Exception:
        return []

def get_catalogo_consignatarios():
    try:
        res = supabase.table("catalogo_consignatarios").select("*").order("nombre").execute()
        return res.data if res.data else []
    except Exception:
        return []

def get_catalogo_productos():
    try:
        res = supabase.table("catalogo_productos").select("*").order("categoria").execute()
        return res.data if res.data else []
    except Exception:
        return []

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
    "CIERRE HISTÓRICO / SINC. DEUDA",
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

CATEGORIAS_PRODUCTOS = [
    "Preforma PET",
    "Resina PET",
    "Tapa / Cap",
    "Polietileno / Film",
    "Maquinaria / Repuesto",
    "Otro Producto"
]

# Inicializar Variables de Sesión
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "user_role" not in st.session_state: st.session_state.user_role = None
if "user_dept" not in st.session_state: st.session_state.user_dept = None
if "editing_invoice" not in st.session_state: st.session_state.editing_invoice = None
if "preselected_pago_invoice" not in st.session_state: st.session_state.preselected_pago_invoice = None
if "pending_nav_menu" not in st.session_state: st.session_state.pending_nav_menu = None

modo_mantenimiento_activo = get_maintenance_mode()

# =============================================================
# 🔒 PANTALLA DE BLOQUEO DE MANTENIMIENTO
# =============================================================
if modo_mantenimiento_activo and st.session_state.user_role != "admin":
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #EAB308;'>🛠️ SISTEMA EN MANTENIMIENTO</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center; color: gray;'>Plataforma en actualización programada.</h3>", unsafe_allow_html=True)
    st.warning("ℹ️ **Acceso Pausado:** Por favor reintente más tarde.")
    
    with st.expander("🔑 Acceso SOLO Administrador"):
        with st.form("form_maint_login"):
            admin_pin = st.text_input("PIN de Compras", type="password", max_chars=4)
            submit_admin_maint = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
            if submit_admin_maint:
                if admin_pin == "1212":
                    st.session_state.authenticated = True
                    st.session_state.user_role = "admin"
                    st.session_state.user_dept = "Compras"
                    st.rerun()
                else:
                    st.error("❌ Solo el Departamento de Compras puede ingresar durante el mantenimiento.")
    st.stop()

# -------------------------------------------------------------
# FUNCIONES AUXILIARES Y GESTIÓN DE ARCHIVOS
# -------------------------------------------------------------
def clean_url(val):
    if pd.isna(val) or str(val).strip().lower() in ['', 'none', 'nan', 'nat']:
        return None
    return str(val).strip()

def ensure_bucket_exists(bucket_name="documentos"):
    try:
        supabase.storage.create_bucket(bucket_name, options={"public": True})
    except Exception:
        pass

def upload_file_to_supabase(file_obj, num_invoice, prefix, bucket="documentos"):
    if file_obj is None:
        return None
    try:
        safe_invoice = "".join(c for c in str(num_invoice) if c.isalnum() or c in ('-', '_'))
        clean_filename = "".join(c for c in file_obj.name if c.isalnum() or c in ('.', '_', '-'))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        storage_path = f"{prefix}_{safe_invoice}_{timestamp}_{clean_filename}"
        
        file_bytes = file_obj.getvalue()
        content_type = file_obj.type or "application/octet-stream"
        
        ensure_bucket_exists(bucket)
        
        supabase.storage.from_(bucket).upload(
            path=storage_path, 
            file=file_bytes, 
            file_options={"content-type": content_type}
        )
        return supabase.storage.from_(bucket).get_public_url(storage_path)
    except Exception as e:
        err_msg = str(e)
        if "Bucket not found" in err_msg:
            try:
                supabase.storage.create_bucket(bucket, options={"public": True})
                supabase.storage.from_(bucket).upload(
                    path=storage_path, 
                    file=file_bytes, 
                    file_options={"content-type": content_type}
                )
                return supabase.storage.from_(bucket).get_public_url(storage_path)
            except Exception as e2:
                st.error(f"🚨 El bucket '{bucket}' no existe en tu Supabase. Error: {e2}")
                return None
        else:
            st.error(f"🚨 Error al subir archivo '{file_obj.name}': {e}")
            return None

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

def generar_excel_embarques(df_data):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_data.to_excel(writer, index=False, sheet_name='Embarques')
    buffer.seek(0)
    return buffer

def generar_zip_expediente(num_invoice, row_data):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        core_docs = [
            ('Packing_List', row_data.get('path_packing')),
            ('Factura_Comercial', row_data.get('path_invoice')),
            ('Factura_Flete', row_data.get('path_flete')),
            ('Bill_of_Lading', row_data.get('path_bl'))
        ]
        for label, url in core_docs:
            url_clean = clean_url(url)
            if url_clean and url_clean.startswith('http'):
                try:
                    r = requests.get(url_clean, timeout=10)
                    if r.status_code == 200:
                        fname = url_clean.split('/')[-1]
                        zip_file.writestr(f"Principales/{label}_{fname}", r.content)
                except Exception:
                    pass
        
        try:
            res_anx = supabase.table("documentos_embarque").select("*").eq("num_invoice", num_invoice).execute()
            if res_anx.data:
                for doc in res_anx.data:
                    d_url = clean_url(doc.get("path_archivo"))
                    d_tipo = str(doc.get("tipo_documento", "Anexo")).replace(' ', '_')
                    d_nombre = doc.get("nombre_archivo", "archivo")
                    if d_url and d_url.startswith('http'):
                        try:
                            r = requests.get(d_url, timeout=10)
                            if r.status_code == 200:
                                zip_file.writestr(f"Anexos/{d_tipo}/{d_nombre}", r.content)
                        except Exception:
                            pass
        except Exception:
            pass
            
    buffer.seek(0)
    return buffer

# -------------------------------------------------------------
# TRACKING Y VISIBILIDAD LOGÍSTICA
# -------------------------------------------------------------
def get_tracking_info(naviera, num_contenedor, num_bl):
    cont = str(num_contenedor).strip().upper() if pd.notna(num_contenedor) else ""
    bl = str(num_bl).strip().upper() if pd.notna(num_bl) else ""
    nav = str(naviera).strip().upper() if pd.notna(naviera) else ""
    
    # Prioridad: Usar N° de BL primero. Si no existe, usar el N° de Contenedor como alternativa.
    if bl and bl not in ['NONE', 'NAN', '']:
        ref = bl
        is_bl = True
    elif cont and cont not in ['NONE', 'NAN', '']:
        ref = cont
        is_bl = False
    else:
        return None, None, "⚠️ Sin BL / Contenedor asignado"

    encoded_ref = urllib.parse.quote(ref)
    
    if "MSC" in nav:
        url, label = f"https://www.msc.com/en/track-a-shipment?number={encoded_ref}", "🌐 Rastrear en MSC"
    elif "MAERSK" in nav:
        url, label = f"https://www.maersk.com/tracking/{encoded_ref}", "🌐 Rastrear en Maersk"
    elif "CMA" in nav:
        # Enlace conector directo de Track-Trace con autorrelleno de BL
        tt_type = "bol" if is_bl else "container"
        url, label = f"https://connect.track-trace.com/{tt_type}/{encoded_ref}", "🌐 Rastrear CMA CGM en Track-Trace"
    elif "HAPAG" in nav:
        path = "track-by-booking-bl.html?bl=" if is_bl else "track-by-container.html?container="
        url, label = f"https://www.hapag-lloyd.com/en/online-business/track/{path}{encoded_ref}", "🌐 Rastrear en Hapag-Lloyd"
    elif "ONE" in nav:
        stype = "B" if is_bl else "C"
        url, label = f"https://ecomm.one-line.com/one-ecom/cargo-tracking?searchType={stype}&number={encoded_ref}", "🌐 Rastrear en ONE Line"
    elif "COSCO" in nav:
        stype = "BL_NO" if is_bl else "CONTAINER_NO"
        url, label = f"https://lines.coscoshipping.com/ebusiness/cargo-tracking?type={stype}&number={encoded_ref}", "🌐 Rastrear en COSCO"
    elif "EVERGREEN" in nav:
        tt_type = "bol" if is_bl else "container"
        url, label = f"https://connect.track-trace.com/{tt_type}/{encoded_ref}", "🌐 Rastrear Evergreen en Track-Trace"
    else:
        tt_type = "bol" if is_bl else "container"
        url, label = f"https://connect.track-trace.com/{tt_type}/{encoded_ref}", "🌐 Rastrear en Track-Trace"

    tipo_lbl = "BL" if is_bl else "Contenedor"
    return url, label, f"Ref: `{ref}` ({tipo_lbl} - {nav})"

def get_eta_status(eta_val, estatus_val, row_data=None):
    if pd.isna(eta_val) or str(eta_val).strip() in ['', 'None', 'nan', 'NaT']:
        return "⚪ **ETA:** No especificada", "info"
    
    eta_date = safe_parse_date(eta_val)
    today = date.today()
    diff = (eta_date - today).days
    estatus_clean = str(estatus_val).strip()

    if estatus_clean == "Entregado":
        dias_ad = 0
        fecha_ent_str = today.strftime('%d/%m/%Y')
        
        if row_data is not None:
            val_dias = row_data.get('dias_en_aduana')
            if pd.notna(val_dias) and str(val_dias).strip() not in ['', 'None', 'nan']:
                try:
                    dias_ad = int(float(val_dias))
                except Exception:
                    dias_ad = 0
            else:
                fecha_ent = safe_parse_date(row_data.get('fecha_entrega'))
                dias_ad = max(0, (fecha_ent - eta_date).days)
            
            fecha_ent_str = safe_parse_date(row_data.get('fecha_entrega')).strftime('%d/%m/%Y')

        return f"✅ **Estatus:** ENTREGADO el {fecha_ent_str} (Permaneció **{dias_ad} día(s)** en Aduana/Puerto)", "success"
    elif diff < 0:
        dias_en_puerto = abs(diff)
        return f"⚓ **Carga en Puerto / Aduana hace {dias_en_puerto} día(s)** (Arribó el {eta_date.strftime('%d/%m/%Y')})", "warning"
    elif diff == 0:
        return f"🟡 **¡ARRIBO EN PUERTO ESTIMADO HOY!** ({eta_date.strftime('%d/%m/%Y')})", "warning"
    elif diff <= 3:
        return f"🟡 **Arribo Inminente:** Faltan solo **{diff} día(s)** en tránsito ({eta_date.strftime('%d/%m/%Y')})", "warning"
    else:
        return f"🟢 **En Tránsito:** Arribo estimado en **{diff} días** ({eta_date.strftime('%d/%m/%Y')})", "info"

def render_timeline(estatus_actual):
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

def generar_pdf_embarque(row_data, df_pagos, df_notas=None):
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

    eta_dt = safe_parse_date(row_data.get('eta'))
    estatus_curr = str(row_data.get('estatus', '')).strip()

    if estatus_curr == "Entregado":
        dias_ad_val = row_data.get('dias_en_aduana')
        if pd.isna(dias_ad_val) or dias_ad_val is None:
            f_ent = safe_parse_date(row_data.get('fecha_entrega', date.today()))
            dias_ad_str = f"{max(0, (f_ent - eta_dt).days)} día(s)"
        else:
            dias_ad_str = f"{int(dias_ad_val)} día(s)"
    else:
        today = date.today()
        diff_days = (today - eta_dt).days
        dias_ad_str = f"{diff_days} día(s) (En Proceso / Tránsito)" if diff_days > 0 else "0 días (En camino)"

    data_logistica = [
        [Paragraph("<b>Estatus Actual:</b>", body_style), estatus_curr, Paragraph("<b>Línea Naviera:</b>", body_style), str(row_data.get('naviera', ''))],
        [Paragraph("<b>N° Contenedor:</b>", body_style), str(row_data.get('num_contenedor', '')), Paragraph("<b>N° BL:</b>", body_style), str(row_data.get('num_bl', ''))],
        [Paragraph("<b>Origen:</b>", body_style), str(row_data.get('origen', '')), Paragraph("<b>Destino:</b>", body_style), str(row_data.get('destino', ''))],
        [Paragraph("<b>ETA (Arribo):</b>", body_style), str(row_data.get('eta', '')), Paragraph("<b>Producto:</b>", body_style), str(row_data.get('producto', ''))],
        [Paragraph("<b>Días en Aduana / Puerto:</b>", body_style), dias_ad_str, Paragraph("<b>Fecha Entrega:</b>", body_style), str(row_data.get('fecha_entrega') or 'Pendiente')]
    ]

    t1 = Table(data_logistica, colWidths=[120, 140, 110, 150])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.extend([t1, Spacer(1, 10), Paragraph("👥 Proveedor y Agentes Asignados", subtitle_style), Spacer(1, 4)])

    data_agentes = [
        [Paragraph("<b>Fabricante / Proveedor:</b>", body_style), str(row_data.get('fabricante', ''))],
        [Paragraph("<b>Consignatario:</b>", body_style), str(row_data.get('consignatario', ''))],
        [Paragraph("<b>Agente de Carga (FF):</b>", body_style), str(row_data.get('agente_carga', ''))],
        [Paragraph("<b>Agente de Aduanas:</b>", body_style), str(row_data.get('agente_aduanas', ''))]
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

    monto_factura = float(row_data['monto_factura']) if pd.notna(row_data.get('monto_factura')) else 0.0
    df_fabrica = df_pagos[df_pagos['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos.empty else pd.DataFrame()
    monto_abonado_fabrica = df_fabrica['monto'].sum() if not df_fabrica.empty else 0.0
    saldo_pendiente_fabrica = max(0.0, monto_factura - monto_abonado_fabrica)

    df_flete = df_pagos[df_pagos['tipo_pago'] == 'Pago a Freight Forwarder'] if not df_pagos.empty else pd.DataFrame()
    monto_flete_pagado = df_flete['monto'].sum() if not df_flete.empty else 0.0
    
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
        
        [Paragraph("<b>FLETE — Agente:</b>", body_style), Paragraph(str(row_data.get('agente_carga') or 'N/A'), body_style),
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
    elements.extend([t3, Spacer(1, 10), Paragraph("<b>Historial Unificado de Pagos Registrados:</b>", body_style), Spacer(1, 4)])

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

    elements.extend([Spacer(1, 10), Paragraph("💬 Observaciones y Bitácora de Novedades (Compras y Almacén)", subtitle_style), Spacer(1, 4)])
    if df_notas is not None and not df_notas.empty:
        table_notas_data = [[Paragraph("Fecha / Hora", header_cell_style), Paragraph("Usuario / Rol", header_cell_style), Paragraph("Comentario / Observación", header_cell_style)]]
        for _, n in df_notas.iterrows():
            rol_lbl = "🛒 Compras" if n.get('rol') == 'admin' else ("📦 Almacén" if n.get('rol') == 'almacen' else "💼 Admon")
            table_notas_data.append([
                Paragraph(str(n.get('fecha_hora', '')), body_style),
                Paragraph(f"{rol_lbl} ({n.get('usuario', '')})", body_style),
                Paragraph(str(n.get('comentario', '')), body_style)
            ])
        t_notas = Table(table_notas_data, colWidths=[100, 110, 310])
        t_notas.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#334155')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_notas)
    else:
        elements.append(Paragraph("<i>No se registran observaciones adicionales en la bitácora de este embarque.</i>", body_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- LOGIN NORMAL ---
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

# --- NAVEGACIÓN Y MENÚ ---
st.sidebar.title("🚢 Menú Principal")
st.sidebar.markdown(f"**Usuario:** {st.session_state.user_dept}")

role = st.session_state.user_role 

if role == "admin":
    options = [
        "📊 Dashboard General",
        "📋 Control de Embarques", 
        "⚙️ Catálogos Maestros",
        "💳 Módulo de Pagos Internacionales",
        "📊 Carga Masiva (Excel/CSV)", 
        "➕ Cargar Nuevo Embarque", 
        "✏️ Editar / Actualizar Embarque"
    ]
else:
    options = [
        "📊 Dashboard General",
        "📋 Control de Embarques"
    ]

if st.session_state.pending_nav_menu is not None:
    st.session_state.nav_menu = st.session_state.pending_nav_menu
    st.session_state.pending_nav_menu = None

menu = st.sidebar.radio("Navegación", options, key="nav_menu")

# INTERRUPTOR DE MODO MANTENIMIENTO
if role == "admin":
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Control de Plataforma")
    
    mantenimiento_toggle = st.sidebar.toggle("🛠️ Activar Modo Mantenimiento", value=modo_mantenimiento_activo)
    
    if mantenimiento_toggle != modo_mantenimiento_activo:
        set_maintenance_mode(mantenimiento_toggle)
        if mantenimiento_toggle:
            st.sidebar.warning("🛠️ Mantenimiento ACTIVADO (Almacén y Admon Bloqueados)")
        else:
            st.sidebar.success("🟢 Mantenimiento DESACTIVADO (Acceso normal)")
        st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🔒 Cerrar Sesión", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.user_role = None
    st.session_state.user_dept = None
    st.session_state.editing_invoice = None
    st.session_state.preselected_pago_invoice = None
    st.session_state.pending_nav_menu = None
    st.rerun()

if role == "admin" and modo_mantenimiento_activo:
    st.warning("🚨 **MODO MANTENIMIENTO ACTIVADO GLOBALMENTE:** Almacén y Administración tienen el acceso bloqueado hasta que desactives el interruptor en el menú lateral.")

# =============================================================
# VISTA 0: 📊 DASHBOARD GENERAL
# =============================================================
if menu == "📊 Dashboard General":
    st.title(f"📊 Dashboard de Control — {st.session_state.user_dept}")
    st.caption("Visión analítica integrada en tiempo real basada en la información de Supabase")

    res_emb = supabase.table("embarques").select("*").execute()
    df_db = pd.DataFrame(res_emb.data) if res_emb.data else pd.DataFrame()

    res_pag = supabase.table("pagos_embarques").select("*").execute()
    df_pagos_db = pd.DataFrame(res_pag.data) if res_pag.data else pd.DataFrame()

    if df_db.empty:
        st.info("No hay datos registrados aún para generar indicadores en el Dashboard.")
    else:
        today = date.today()
        df_db['eta_dt'] = pd.to_datetime(df_db['eta'], errors='coerce')
        df_activas = df_db[df_db['estatus'] != 'Entregado']
        
        df_db['eta_month_year'] = df_db['eta_dt'].dt.strftime('%m/%Y')
        current_my = today.strftime('%m/%Y')
        df_entregadas_mes = df_db[(df_db['estatus'] == 'Entregado') & (df_db['eta_month_year'] == current_my)]

        if role == "admin":
            invoices_pago_ff = df_pagos_db[df_pagos_db['tipo_pago'] == 'Pago a Freight Forwarder']['num_invoice'].unique() if not df_pagos_db.empty else []
            
            monto_total_facturas = df_activas['monto_factura'].fillna(0).sum()
            df_pagos_fab = df_pagos_db[df_pagos_db['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos_db.empty else pd.DataFrame()
            total_abonado_fab = df_pagos_fab['monto'].sum() if not df_pagos_fab.empty else 0.0
            saldo_total_fabrica = max(0.0, monto_total_facturas - total_abonado_fab)

            fletes_pendientes_cnt = len(df_activas[~df_activas['num_invoice'].isin(invoices_pago_ff) & (~df_activas['estatus'].isin(['Entregado', 'Pendiente Pago']))])
            en_puerto_cnt = len(df_activas[(df_activas['eta_dt'].dt.date <= today)])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🚢 Cargas Activas", len(df_activas))
            m2.metric("⚓ En Puerto / Aduana", en_puerto_cnt)
            m3.metric("💰 Capital Facturado", f"${monto_total_facturas:,.2f} USD")
            m4.metric("🔴 Deuda Pendiente Fábricas", f"${saldo_total_fabrica:,.2f} USD")

            st.markdown("---")
            if fletes_pendientes_cnt > 0 or en_puerto_cnt > 0:
                st.subheader("🚨 Semáforo Operativo y Financiero")
                c_a1, c_a2 = st.columns(2)
                with c_a1:
                    if fletes_pendientes_cnt > 0:
                        st.warning(f"⚠️ **{fletes_pendientes_cnt} embarque(s) en tránsito** aún no registran pago de flete al Forwarder.")
                with c_a2:
                    if en_puerto_cnt > 0:
                        st.info(f"⚓ **{en_puerto_cnt} embarque(s)** se encuentran actualmente arribados en puerto o en proceso aduanal.")

            st.markdown("---")
            st.subheader("📊 Análisis Financiero y Logístico")
            c_g1, c_g2 = st.columns(2)
            
            with c_g1:
                st.markdown("##### 🏭 Saldo Pendiente por Proveedor / Fábrica")
                if not df_activas.empty:
                    df_fab = df_activas.groupby('fabricante')['monto_factura'].sum().reset_index()
                    st.bar_chart(df_fab, x='fabricante', y='monto_factura')
                else:
                    st.caption("Sin cargas activas.")

            with c_g2:
                st.markdown("##### 🏦 Desembolsos por Banco / Plataforma")
                if not df_pagos_db.empty:
                    df_bancos = df_pagos_db.groupby('banco')['monto'].sum().reset_index()
                    st.bar_chart(df_bancos, x='banco', y='monto')
                else:
                    st.caption("Sin pagos registrados.")

        elif role == "almacen":
            df_camino = df_db[df_db['estatus'].str.contains('Tránsito', na=False)]
            df_aduanas = df_db[df_db['estatus'] == 'En Aduanas']
            arribos_7d = df_activas[(df_activas['eta_dt'].dt.date >= today) & (df_activas['eta_dt'].dt.date <= today + pd.Timedelta(days=7))]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🚢 Cargas en Camino", len(df_camino))
            m2.metric("🛃 Cargas en Aduana", len(df_aduanas))
            m3.metric("📦 Entregadas este Mes", len(df_entregadas_mes))
            m4.metric("🟡 Arribos (Próx 7 Días)", len(arribos_7d))

            st.markdown("---")
            st.subheader("🗓️ Calendario de Arribos Próximos")
            if not arribos_7d.empty:
                st.dataframe(arribos_7d[['num_invoice', 'num_contenedor', 'fabricante', 'producto', 'eta', 'estatus']], use_container_width=True, hide_index=True)
            else:
                st.info("No hay arribos programados para los próximos 7 días.")

            st.markdown("---")
            st.subheader("📊 Embudo de Estatus de Cargas")
            df_estatus_cnt = df_activas['estatus'].value_counts().reset_index()
            df_estatus_cnt.columns = ['Estatus', 'Cantidad']
            st.bar_chart(df_estatus_cnt, x='Estatus', y='Cantidad')

        elif role == "admon":
            def check_expediente(row):
                has_pack = pd.notna(row.get('path_packing')) and clean_url(row.get('path_packing')) is not None
                has_inv = pd.notna(row.get('path_invoice')) and clean_url(row.get('path_invoice')) is not None
                has_fle = pd.notna(row.get('path_flete')) and clean_url(row.get('path_flete')) is not None
                has_bl = pd.notna(row.get('path_bl')) and clean_url(row.get('path_bl')) is not None
                return has_pack and has_inv and has_fle and has_bl

            df_activas['expediente_ok'] = df_activas.apply(check_expediente, axis=1)
            completo_cnt = len(df_activas[df_activas['expediente_ok']])

            m1, m2, m3 = st.columns(3)
            m1.metric("🚢 Total Cargas Activas", len(df_activas))
            m2.metric("📄 Expedientes Completos", f"{completo_cnt} de {len(df_activas)}")
            m3.metric("📦 Cargas Entregadas este Mes", len(df_entregadas_mes))

            st.markdown("---")
            st.subheader("📁 Estado Detallado de Expedientes (Documentación Base)")
            if not df_activas.empty:
                rep_docs = []
                for _, r in df_activas.iterrows():
                    faltantes = []
                    if pd.isna(r.get('path_packing')) or not clean_url(r.get('path_packing')): faltantes.append("Packing List")
                    if pd.isna(r.get('path_invoice')) or not clean_url(r.get('path_invoice')): faltantes.append("Factura Comercial")
                    if pd.isna(r.get('path_flete')) or not clean_url(r.get('path_flete')): faltantes.append("Factura Flete")
                    if pd.isna(r.get('path_bl')) or not clean_url(r.get('path_bl')): faltantes.append("BL")
                    if str(r.get('estatus')).strip() in ["En Tránsito 2", "En Tránsito 3", "En Aduanas"] and not r.get('solicitado_dua'): faltantes.append("DUA")

                    rep_docs.append({
                        "Invoice": r['num_invoice'],
                        "Consignatario": r.get('consignatario') or 'N/A',
                        "Estatus": r['estatus'],
                        "Estado Expediente": "🟢 COMPLETO" if len(faltantes) == 0 else "🔴 INCOMPLETO",
                        "Documentos / Trámites Faltantes": ", ".join(faltantes) if faltantes else "Ninguno (OK)"
                    })
                st.dataframe(pd.DataFrame(rep_docs), use_container_width=True, hide_index=True)
            else:
                st.info("No hay cargas activas para auditar expedientes.")

# =============================================================
# VISTA 1: 📋 CONTROL DE EMBARQUES (CON EXPORTACIÓN A EXCEL/CSV)
# =============================================================
elif menu == "📋 Control de Embarques":
    st.title("📋 Control General de Embarques")
    st.caption("Visualización interactiva en la nube, búsqueda en tiempo real, exportación de reportes y gestión documental")
    
    res_emb = supabase.table("embarques").select("*").execute()
    df = pd.DataFrame(res_emb.data) if res_emb.data else pd.DataFrame()
    
    res_pag = supabase.table("pagos_embarques").select("num_invoice, tipo_pago").execute()
    df_pagos_all = pd.DataFrame(res_pag.data) if res_pag.data else pd.DataFrame()
    
    if df.empty:
        st.info("No hay embarques registrados aún en la base de datos de Supabase.")
    else:
        invoices_con_pago_ff = df_pagos_all[df_pagos_all['tipo_pago'] == 'Pago a Freight Forwarder']['num_invoice'].unique() if not df_pagos_all.empty else []

        def check_pago_ff(row):
            estatus = str(row.get('estatus', '')).strip()
            inv = row.get('num_invoice', '')
            if estatus in ['Entregado', 'Pendiente Pago']:
                return '✅ No Aplica / Pagado'
            elif inv in invoices_con_pago_ff:
                return '🟢 Flete Pagado'
            else:
                return '⚠️ PENDIENTE FLETE'

        df['pago_flete_status'] = df.apply(check_pago_ff, axis=1)
        df['dua_badge'] = df.apply(lambda r: "🟢 Solicitado" if r.get('solicitado_dua') else "🟡 Pendiente", axis=1)
        df['reca_badge'] = df.apply(lambda r: "🟢 Solicitado" if r.get('solicitado_reca') else "🟡 Pendiente", axis=1)

        with st.expander("🔍 **Buscador y Filtros Avanzados**", expanded=True):
            col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1, 1, 1])
            with col_f1: search_term = st.text_input("🔎 Búsqueda Global", placeholder="Escribe N° Invoice, Contenedor, BL, Fabricante o Producto...", key="search_global")
            with col_f2: filtro_estatus = st.selectbox("Estatus del Embarque", ["Todos"] + ESTATUS_LISTA, index=0)
            with col_f3: filtro_naviera = st.selectbox("Línea Naviera", ["Todas"] + NAVIERAS, index=0)
            with col_f4: filtro_flete = st.selectbox("Estado del Flete", ["Todos", "⚠️ PENDIENTE FLETE", "🟢 Flete Pagado", "✅ No Aplica / Pagado"], index=0) if role == "admin" else "Todos"

        df_filtered = df.copy()
        df_filtered['eta_dt'] = pd.to_datetime(df_filtered['eta'], errors='coerce')
        df_filtered = df_filtered.sort_values(by='eta_dt', ascending=True, na_position='last')

        if filtro_estatus == "Todos" and not search_term.strip():
            df_filtered = df_filtered[df_filtered['estatus'] != 'Entregado']
        elif filtro_estatus != "Todos":
            df_filtered = df_filtered[df_filtered['estatus'] == filtro_estatus]

        if search_term:
            term = search_term.lower().strip()
            mask = (
                df_filtered['num_invoice'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['num_contenedor'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['num_bl'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['fabricante'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['producto'].astype(str).str.lower().str.contains(term, na=False) |
                df_filtered['estatus'].astype(str).str.lower().str.contains(term, na=False)
            )
            df_filtered = df_filtered[mask]

        if filtro_naviera != "Todas": df_filtered = df_filtered[df_filtered['naviera'] == filtro_naviera]
        if role == "admin" and filtro_flete != "Todos": df_filtered = df_filtered[df_filtered['pago_flete_status'] == filtro_flete]

        c_top1, c_top2 = st.columns([2, 1])
        with c_top1:
            st.caption(f"📊 Mostrando **{len(df_filtered)}** de **{len(df)}** embarque(s) registrado(s).")
        
        # BOTONES DE EXPORTACIÓN A EXCEL
        with c_top2:
            df_export = df_filtered.drop(columns=['eta_dt'], errors='ignore')
            excel_bytes = generar_excel_embarques(df_export)
            st.download_button(
                label="📊 Exportar a Excel (.xlsx)",
                data=excel_bytes,
                file_name=f"Reporte_Embarques_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

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

            cols_to_show = ['num_invoice', 'num_contenedor', 'num_bl', 'naviera', 'fabricante', 'producto', 'origen', 'destino', 'eta', 'estatus'] + (['pago_flete_status', 'dua_badge', 'reca_badge'] if role == "admin" else [])
            cols_names = ['N° Invoice', 'Contenedor', 'N° BL', 'Línea Naviera', 'Fabricante', 'Producto', 'Origen', 'Destino', 'ETA (Arribo)', 'Estatus'] + (['Estado Flete', 'DUA', 'RECA'] if role == "admin" else [])

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
                if 0 <= row_idx < len(df_display):
                    selected_invoice = df_display.iloc[row_idx]['N° Invoice']
                    row_matches = df[df['num_invoice'] == selected_invoice]
                    
                    if not row_matches.empty:
                        row_data = row_matches.iloc[0]

                        st.markdown("---")
                        st.success(f"📌 Embarque Seleccionado: **Invoice {selected_invoice}** | Contenedor: **{row_data['num_contenedor']}** | ETA: **{row_data['eta']}**")

                        if role == "admin":
                            es_omito_flete = (str(row_data['estatus']).strip() in ["Entregado", "Pendiente Pago"])
                            tiene_pago_ff = selected_invoice in invoices_con_pago_ff
                            if not es_omito_flete and not tiene_pago_ff:
                                st.warning(f"⚠️ **ALERTA DE FLETE:** Este embarque se encuentra **'{row_data['estatus']}'** y **AÚN NO TIENE REGISTRADO EL PAGO AL FREIGHT FORWARDER**.")

                        eta_msg, eta_type = get_eta_status(row_data['eta'], row_data['estatus'], row_data)
                        if eta_type == "error": st.error(eta_msg)
                        elif eta_type == "warning": st.warning(eta_msg)
                        elif eta_type == "success": st.success(eta_msg)
                        else: st.info(eta_msg)

                        if role == "admin":
                            with st.expander("📡 **Rastreo de Carga en Tiempo Real**", expanded=False):
                                url_track, label_track, info_ref = get_tracking_info(row_data['naviera'], row_data['num_contenedor'], row_data['num_bl'])
                                c_track1, c_track2 = st.columns([3, 1])
                                with c_track1: st.caption(f"Línea Naviera: **{row_data['naviera'] or 'No especificada'}** | {info_ref}")
                                with c_track2:
                                    if url_track: st.link_button(label=label_track, url=url_track, type="primary", use_container_width=True)
                                    else: st.button("🚫 Sin datos para rastrear", disabled=True, use_container_width=True)

                        with st.expander("📍 **LÍNEA DE TIEMPO Y PROGRESO DEL EMBARQUE**", expanded=False):
                            render_timeline(row_data['estatus'])

                        if role == "admin" and str(row_data.get('estatus')).strip() in ["En Tránsito 2", "En Tránsito 3", "En Aduanas", "Entregado"]:
                            sol_dua = bool(row_data.get('solicitado_dua', False))
                            f_dua = str(row_data.get('fecha_solicitud_dua') or '')
                            sol_reca = bool(row_data.get('solicitado_reca', False))
                            f_reca = str(row_data.get('fecha_solicitud_reca') or '')

                            with st.expander("📑 **CONTROL DE TRAMITACIÓN DE ADUANA (DUA) Y RECA**", expanded=True):
                                c_tr1, c_tr2 = st.columns(2)
                                with c_tr1:
                                    st.markdown("##### 1️⃣ Solicitud de Borrador DUA (Agente Aduana)")
                                    check_dua = st.checkbox("✅ Marcar como 'DUA Solicitada'", value=sol_dua, key=f"chk_dua_{selected_invoice}")
                                    if check_dua != sol_dua:
                                        now_str = datetime.now().strftime("%d/%m/%Y %H:%M") if check_dua else None
                                        supabase.table("embarques").update({"solicitado_dua": check_dua, "fecha_solicitud_dua": now_str}).eq("num_invoice", selected_invoice).execute()
                                        st.success("✅ Estado DUA actualizado.")
                                        st.rerun()

                                with c_tr2:
                                    st.markdown("##### 2️⃣ Solicitud de RECA (Exoneración)")
                                    check_reca = st.checkbox("✅ Marcar como 'RECA Solicitado'", value=sol_reca, key=f"chk_reca_{selected_invoice}")
                                    if check_reca != sol_reca:
                                        now_str = datetime.now().strftime("%d/%m/%Y %H:%M") if check_reca else None
                                        supabase.table("embarques").update({"solicitado_reca": check_reca, "fecha_solicitud_reca": now_str}).eq("num_invoice", selected_invoice).execute()
                                        st.success("✅ Estado RECA actualizado.")
                                        st.rerun()

                        with st.expander("💼 **Expediente Digital del Embarque (Documentos Principales)**", expanded=False):
                            if role == "almacen":
                                docs_principales = [("Packing List", row_data.get('path_packing'))]
                            else:
                                docs_principales = [
                                    ("Packing List", row_data.get('path_packing')),
                                    ("Factura Comercial (Invoice)", row_data.get('path_invoice')),
                                    ("Factura de Flete", row_data.get('path_flete')),
                                    ("Bill of Lading (BL)", row_data.get('path_bl'))
                                ]
                            col_d1, col_d2 = st.columns(2)
                            for idx, (label, url) in enumerate(docs_principales):
                                col_target = col_d1 if idx % 2 == 0 else col_d2
                                url_clean = clean_url(url)
                                with col_target:
                                    if url_clean and url_clean.startswith('http'):
                                        st.link_button(f"⬇️ Ver {label}", url_clean, use_container_width=True)
                                    else:
                                        st.caption(f"❌ {label}: No cargado")

                        if role == "admin":
                            res_anx = supabase.table("documentos_embarque").select("*").eq("num_invoice", selected_invoice).execute()
                            df_extra_docs = pd.DataFrame(res_anx.data) if res_anx.data else pd.DataFrame()
                            
                            with st.expander(f"📁 **Expediente Anexo y Documentación Adicional** ({len(df_extra_docs)} archivo(s))", expanded=False):
                                with st.form(f"form_extra_docs_{selected_invoice}"):
                                    c_exp1, c_exp2 = st.columns(2)
                                    with c_exp1: tipo_doc_sel = st.selectbox("Tipo de Documento *", TIPOS_DOCS_COMPRAS, key=f"sel_tipo_doc_{selected_invoice}")
                                    with c_exp2: extra_files = st.file_uploader("Seleccionar Archivo(s) *", accept_multiple_files=True, key=f"uploader_extra_{selected_invoice}")
                                    btn_subir_extra = st.form_submit_button("📤 Guardar Documentos", type="primary", use_container_width=True)

                                    if btn_subir_extra and extra_files:
                                        for ef in extra_files:
                                            e_url = upload_file_to_supabase(ef, selected_invoice, "ANX", bucket="documentos")
                                            supabase.table("documentos_embarque").insert({
                                                "num_invoice": selected_invoice, "tipo_documento": tipo_doc_sel,
                                                "nombre_archivo": ef.name, "path_archivo": e_url,
                                                "fecha_subida": str(date.today()), "subido_por": st.session_state.user_dept
                                            }).execute()
                                        st.success("✅ Archivos adjuntados.")
                                        st.rerun()

                                zip_buffer = generar_zip_expediente(selected_invoice, row_data)
                                st.download_button(
                                    label=f"📦 Descargar Expediente COMPLETO (.ZIP)",
                                    data=zip_buffer,
                                    file_name=f"Expediente_{selected_invoice}.zip",
                                    mime="application/zip",
                                    type="primary",
                                    use_container_width=True
                                )

                        if role == "almacen":
                            if row_data['estatus'] in ["En Aduanas", "En Tránsito 1", "En Tránsito 2", "En Tránsito 3"]:
                                if st.button("✅ Marcar como ENTREGADO", type="primary"):
                                    today_str = str(date.today())
                                    eta_date = safe_parse_date(row_data.get('eta'))
                                    dias_aduana_calc = max(0, (date.today() - eta_date).days)
                                    
                                    try:
                                        supabase.table("embarques").update({
                                            "estatus": "Entregado",
                                            "fecha_entrega": today_str,
                                            "dias_en_aduana": dias_aduana_calc
                                        }).eq("num_invoice", selected_invoice).execute()
                                    except Exception:
                                        try:
                                            supabase.table("embarques").update({
                                                "estatus": "Entregado",
                                                "fecha_entrega": today_str
                                            }).eq("num_invoice", selected_invoice).execute()
                                        except Exception:
                                            supabase.table("embarques").update({
                                                "estatus": "Entregado"
                                            }).eq("num_invoice", selected_invoice).execute()

                                    st.success(f"¡Estatus actualizado a 'Entregado'! ({dias_aduana_calc} días en aduana).")
                                    st.rerun()

                        res_p_emb = supabase.table("pagos_embarques").select("*").eq("num_invoice", selected_invoice).execute()
                        df_pagos_emb = pd.DataFrame(res_p_emb.data) if res_p_emb.data else pd.DataFrame()

                        if role == "admin":
                            with st.expander(f"💰 **BALANCE FINANCIERO Y PAGOS DE FÁBRICA ({selected_invoice})**", expanded=True):
                                df_pagos_fabrica = df_pagos_emb[df_pagos_emb['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos_emb.empty else pd.DataFrame()
                                monto_total_pagado_fabrica = df_pagos_fabrica['monto'].sum() if not df_pagos_fabrica.empty else 0.0
                                monto_factura = float(row_data['monto_factura']) if pd.notna(row_data.get('monto_factura')) else 0.0
                                saldo_pendiente = max(0.0, monto_factura - monto_total_pagado_fabrica)

                                m1, m2, m3 = st.columns(3)
                                m1.metric("Monto Total Factura", f"${monto_factura:,.2f} USD")
                                m2.metric("Total Abonado", f"${monto_total_pagado_fabrica:,.2f} USD")
                                m3.metric("Saldo Pendiente", f"${saldo_pendiente:,.2f} USD")
                                
                                if saldo_pendiente <= 0 and monto_factura > 0:
                                    st.success("🟢 **Saldo Pendiente Fábrica:** $0.00 USD — ¡PAGADO COMPLETAMENTE!")
                                else:
                                    st.error(f"🔴 **Saldo Pendiente por Pagar:** ${saldo_pendiente:,.2f} USD")

                                st.markdown("##### 🧾 Detalle de Pagos / Abonos Registrados:")
                                if not df_pagos_emb.empty:
                                    df_disp_pagos = df_pagos_emb[['fecha_pago', 'tipo_pago', 'banco', 'monto', 'referencia', 'path_comprobante']].copy()
                                    df_disp_pagos.columns = ['Fecha', 'Tipo de Pago', 'Banco / Origen', 'Monto ($ USD)', 'Referencia', 'Comprobante']
                                    df_disp_pagos['Monto ($ USD)'] = df_disp_pagos['Monto ($ USD)'].apply(lambda x: f"${float(x):,.2f}")
                                    
                                    st.dataframe(
                                        df_disp_pagos,
                                        column_config={
                                            "Comprobante": st.column_config.LinkColumn("Comprobante", display_text="📎 Ver Documento")
                                        },
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                else:
                                    st.info("ℹ️ No hay abonos registrados aún para esta Invoice.")

                        res_notas = supabase.table("notas_embarque").select("*").eq("num_invoice", selected_invoice).order("id", desc=True).execute()
                        df_notas_emb = pd.DataFrame(res_notas.data) if res_notas.data else pd.DataFrame()

                        if role == "admin":
                            col_b1, col_b2 = st.columns(2)
                            with col_b1:
                                if st.button(f"✏️ Editar Embarque ({selected_invoice})", type="primary", use_container_width=True):
                                    st.session_state.editing_invoice = selected_invoice
                            with col_b2:
                                pdf_data = generar_pdf_embarque(row_data, df_pagos_emb, df_notas_emb)
                                st.download_button(label=f"📄 Imprimir Ficha PDF", data=pdf_data, file_name=f"Ficha_{selected_invoice}.pdf", mime="application/pdf", use_container_width=True)

                        st.markdown("---")
                        with st.form(key=f"form_nota_{selected_invoice}", clear_on_submit=True):
                            nuevo_comentario = st.text_area("Agregar observación o comentario:", placeholder="Escriba aquí...", max_chars=400, height=80)
                            btn_guardar_nota = st.form_submit_button("💬 Guardar Comentario", type="primary")

                            if btn_guardar_nota and nuevo_comentario.strip():
                                fecha_hora_actual = datetime.now().strftime("%d/%m/%Y %H:%M")
                                supabase.table("notas_embarque").insert({
                                    "num_invoice": selected_invoice, "usuario": st.session_state.user_dept,
                                    "rol": role, "comentario": nuevo_comentario.strip(), "fecha_hora": fecha_hora_actual
                                }).execute()
                                st.success("✅ Comentario guardado.")
                                st.rerun()

                        if not df_notas_emb.empty:
                            st.markdown("##### 📜 Historial de Observaciones:")
                            for _, n_row in df_notas_emb.iterrows():
                                badge = "🛒 Compras" if n_row['rol'] == 'admin' else ("📦 Almacén" if n_row['rol'] == 'almacen' else "💼 Admon")
                                st.info(f"**{badge} ({n_row['usuario']})** — `{n_row['fecha_hora']}`\n\n💬 {n_row['comentario']}")

# =============================================================
# VISTA 2: ⚙️ MÓDULO DE CATÁLOGOS MAESTROS
# =============================================================
elif menu == "⚙️ Catálogos Maestros" and role == "admin":
    st.title("⚙️ Módulo de Catálogos Maestros")
    st.caption("Administra Proveedores (Fabricantes, Forwarders, Aduanas), Consignatarios y Catálogo Inteligente de Productos PET")

    tab_prov, tab_cons, tab_prod = st.tabs([
        "🏭 Proveedores y Agentes",
        "🏢 Consignatarios",
        "📦 Catálogo de Productos (PET/Resinas)"
    ])

    # TAB 1: PROVEEDORES Y AGENTES
    with tab_prov:
        st.subheader("🏭 Registro de Proveedores y Agentes Logísticos")
        
        with st.form("form_nuevo_proveedor", clear_on_submit=True):
            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                tipo_prov = st.selectbox("Tipo de Proveedor *", ["Fabricante", "Freight Forwarder", "Agente de Aduanas"])
                nombre_prov = st.text_input("Nombre / Razón Social *")
                rif_prov = st.text_input("RIF / NIT / Tax ID")
            with col_p2:
                contacto_prov = st.text_input("Persona de Contacto")
                telefono_prov = st.text_input("Teléfono / WhatsApp")
                email_prov = st.text_input("Correo Electrónico")
            with col_p3:
                direccion_prov = st.text_area("Dirección Física / País")
                notas_prov = st.text_area("Notas Adicionales")

            btn_save_prov = st.form_submit_button("💾 Guardar Proveedor en Catálogo", type="primary", use_container_width=True)

            if btn_save_prov:
                if not nombre_prov.strip():
                    st.error("❌ El nombre o razón social es obligatorio.")
                else:
                    supabase.table("catalogo_proveedores").insert({
                        "tipo": tipo_prov, "nombre": nombre_prov.strip(), "rif_id": rif_prov.strip(),
                        "contacto": contacto_prov.strip(), "telefono": telefono_prov.strip(),
                        "email": email_prov.strip(), "direccion": direccion_prov.strip(), "notas": notas_prov.strip()
                    }).execute()
                    st.success(f"✅ ¡Proveedor '{nombre_prov}' registrado exitosamente!")
                    st.rerun()

        st.markdown("---")
        st.subheader("📋 Lista de Proveedores Registrados")
        list_prov = get_catalogo_proveedores()
        if list_prov:
            df_prov = pd.DataFrame(list_prov)
            st.dataframe(df_prov[['id', 'tipo', 'nombre', 'rif_id', 'contacto', 'telefono', 'email', 'direccion']], use_container_width=True, hide_index=True)
            
            with st.expander("🗑️ Eliminar un Proveedor del Catálogo"):
                prov_id_del = st.selectbox("Seleccione el proveedor a eliminar:", [p['id'] for p in list_prov], format_func=lambda x: f"ID #{x} - {next(p['nombre'] for p in list_prov if p['id'] == x)}")
                if st.button("🗑️ Eliminar Proveedor", type="secondary"):
                    supabase.table("catalogo_proveedores").delete().eq("id", prov_id_del).execute()
                    st.warning("Proveedor eliminado del catálogo.")
                    st.rerun()
        else:
            st.info("Aún no hay proveedores registrados en el catálogo.")

    # TAB 2: CONSIGNATARIOS
    with tab_cons:
        st.subheader("🏢 Registro de Consignatarios")
        
        with st.form("form_nuevo_consignatario", clear_on_submit=True):
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                nombre_cons = st.text_input("Nombre / Razón Social Consignatario *")
                rif_cons = st.text_input("RIF / ID Fiscal")
                contacto_cons = st.text_input("Persona de Contacto")
            with col_c2:
                telefono_cons = st.text_input("Teléfono")
                email_cons = st.text_input("Correo Electrónico")
                direccion_cons = st.text_input("Dirección Fiscal / Entrega")

            btn_save_cons = st.form_submit_button("💾 Guardar Consignatario", type="primary", use_container_width=True)

            if btn_save_cons:
                if not nombre_cons.strip():
                    st.error("❌ El nombre del consignatario es obligatorio.")
                else:
                    supabase.table("catalogo_consignatarios").insert({
                        "nombre": nombre_cons.strip(), "rif_id": rif_cons.strip(),
                        "contacto": contacto_cons.strip(), "telefono": telefono_cons.strip(),
                        "email": email_cons.strip(), "direccion": direccion_cons.strip()
                    }).execute()
                    st.success(f"✅ ¡Consignatario '{nombre_cons}' registrado exitosamente!")
                    st.rerun()

        st.markdown("---")
        st.subheader("📋 Lista de Consignatarios Registrados")
        list_cons = get_catalogo_consignatarios()
        if list_cons:
            df_c = pd.DataFrame(list_cons)
            st.dataframe(df_c[['id', 'nombre', 'rif_id', 'contacto', 'telefono', 'email', 'direccion']], use_container_width=True, hide_index=True)
        else:
            st.info("Aún no hay consignatarios registrados.")

    # TAB 3: CATÁLOGO INTELIGENTE DE PRODUCTOS
    with tab_prod:
        st.subheader("📦 Catálogo Inteligente de Productos (Preformas PET, Resinas y Tapas)")
        st.caption("Registra de forma estandarizada los productos especificando categoría, gramajes (20g, 40g, 700g, etc.) y colores.")

        with st.form("form_nuevo_producto", clear_on_submit=True):
            col_pr1, col_pr2, col_pr3 = st.columns(3)
            with col_pr1:
                cat_prod = st.selectbox("Categoría de Producto *", CATEGORIAS_PRODUCTOS)
                nom_prod = st.text_input("Nombre Comercial / Descripción *", placeholder="Ej: Preforma 28mm PCO 1881")
            with col_pr2:
                gramaje_prod = st.text_input("Gramaje / Peso (Si Aplica)", placeholder="Ej: 20g, 25g, 40g, 700g, 25 Kg")
                color_prod = st.text_input("Color / Apariencia", placeholder="Ej: Cristal / Transparente, Azul, Verde")
            with col_pr3:
                specs_prod = st.text_area("Especificaciones Técnicas / Grado", placeholder="Ej: IV 0.80 Grado Botella, Rosca 30/25, etc.")

            btn_save_prod = st.form_submit_button("💾 Guardar Producto en Catálogo Maestros", type="primary", use_container_width=True)

            if btn_save_prod:
                if not nom_prod.strip():
                    st.error("❌ El nombre del producto es obligatorio.")
                else:
                    supabase.table("catalogo_productos").insert({
                        "categoria": cat_prod, "nombre": nom_prod.strip(),
                        "gramaje": gramaje_prod.strip(), "color": color_prod.strip(),
                        "especificaciones": specs_prod.strip()
                    }).execute()
                    st.success(f"✅ ¡Producto '{nom_prod}' agregado al catálogo!")
                    st.rerun()

        st.markdown("---")
        st.subheader("📋 Catálogo Maestro de Productos")
        list_prod = get_catalogo_productos()
        if list_prod:
            df_pr = pd.DataFrame(list_prod)
            st.dataframe(df_pr[['id', 'categoria', 'nombre', 'gramaje', 'color', 'especificaciones']], use_container_width=True, hide_index=True)
            
            with st.expander("🗑️ Eliminar un Producto del Catálogo"):
                prod_id_del = st.selectbox("Seleccione producto a eliminar:", [p['id'] for p in list_prod], format_func=lambda x: f"ID #{x} - {next(p['nombre'] for p in list_prod if p['id'] == x)}")
                if st.button("🗑️ Eliminar Producto", type="secondary"):
                    supabase.table("catalogo_productos").delete().eq("id", prod_id_del).execute()
                    st.warning("Producto eliminado del catálogo.")
                    st.rerun()
        else:
            st.info("Aún no hay productos en el catálogo maestro.")

# --- MENÚ 3: PAGOS INTERNACIONALES ---
elif "Pagos Internacionales" in menu:
    st.title("💳 Registro y Control de Pagos Internacionales")
    st.caption("Módulo exclusivo para Compras: Administra, modifica, elimina transferencias o salda deudas históricas")

    res_emb = supabase.table("embarques").select("num_invoice, fabricante, num_contenedor, monto_factura, estatus").execute()
    df_emb = pd.DataFrame(res_emb.data) if res_emb.data else pd.DataFrame()
    
    if df_emb.empty:
        st.warning("⚠️ Primero debe registrar al menos un embarque para asignarle pagos.")
    else:
        invoices_map = {row['num_invoice']: f"{row['num_invoice']} - {row['fabricante']} (Contenedor: {row['num_contenedor']})" for _, row in df_emb.iterrows()}
        tab_listado, tab_nuevo, tab_historico, tab_editar = st.tabs([
            "📜 Historial General de Pagos",
            "➕ Registrar Nuevo Pago", 
            "✅ Saldar Deuda Histórica", 
            "✏️ Editar / Eliminar Pago Existente"
        ])

        with tab_listado:
            st.subheader("📜 Historial de Pagos y Transferencias Registradas")
            res_all_p = supabase.table("pagos_embarques").select("*").order("fecha_pago", desc=True).execute()
            df_all_p = pd.DataFrame(res_all_p.data) if res_all_p.data else pd.DataFrame()

            if df_all_p.empty:
                st.info("No se han registrado pagos en el sistema aún.")
            else:
                col_m1, col_m2 = st.columns(2)
                tot_pago_fabrica = df_all_p[df_all_p['tipo_pago'] == 'Pago a Fábrica']['monto'].sum()
                tot_pago_ff = df_all_p[df_all_p['tipo_pago'] == 'Pago a Freight Forwarder']['monto'].sum()
                col_m1.metric("Total Pagado a Fábricas", f"${tot_pago_fabrica:,.2f} USD")
                col_m2.metric("Total Pagado a Freight Forwarders", f"${tot_pago_ff:,.2f} USD")

                st.markdown("---")
                filtro_inv_pago = st.selectbox("Filtrar por Invoice (Opcional):", ["Todas"] + list(df_all_p['num_invoice'].unique()))
                df_filt_p = df_all_p.copy()
                if filtro_inv_pago != "Todas":
                    df_filt_p = df_filt_p[df_filt_p['num_invoice'] == filtro_inv_pago]

                df_show_p = df_filt_p[['num_invoice', 'fecha_pago', 'tipo_pago', 'banco', 'monto', 'referencia', 'path_comprobante']].copy()
                df_show_p.columns = ['N° Invoice', 'Fecha Pago', 'Tipo de Pago', 'Banco / Origen', 'Monto ($ USD)', 'N° Referencia', 'Comprobante']
                df_show_p['Monto ($ USD)'] = df_show_p['Monto ($ USD)'].apply(lambda x: f"${float(x):,.2f}")

                st.dataframe(
                    df_show_p,
                    column_config={
                        "Comprobante": st.column_config.LinkColumn("Comprobante", display_text="📎 Ver Documento")
                    },
                    use_container_width=True,
                    hide_index=True
                )

        with tab_nuevo:
            st.subheader("➕ Registrar Nuevo Abono / Pago")
            inv_keys = list(invoices_map.keys())
            default_idx = 0
            if st.session_state.get("preselected_pago_invoice") in inv_keys:
                default_idx = inv_keys.index(st.session_state.preselected_pago_invoice)

            with st.form("form_registrar_pago", clear_on_submit=True):
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    selected_inv_key = st.selectbox("Seleccione Embarque / Invoice *", inv_keys, index=default_idx, format_func=lambda x: invoices_map[x], key="new_pago_inv")
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
                        file_path_pago = upload_file_to_supabase(file_comprobante, f"{selected_inv_key}_{num_ref}", "COMP", bucket="comprobantes")
                        
                        supabase.table("pagos_embarques").insert({
                            "num_invoice": selected_inv_key, "tipo_pago": tipo_pago, "banco": banco_pago,
                            "monto": monto_pago, "fecha_pago": str(fecha_pago), "referencia": num_ref,
                            "path_comprobante": file_path_pago
                        }).execute()
                        
                        if tipo_pago == "Pago a Fábrica":
                            res_c = supabase.table("embarques").select("estatus").eq("num_invoice", selected_inv_key).execute()
                            if res_c.data and res_c.data[0]['estatus'] == "Pendiente Pago":
                                supabase.table("embarques").update({"estatus": "En Producción"}).eq("num_invoice", selected_inv_key).execute()

                        st.session_state.preselected_pago_invoice = None
                        st.success(f"✅ Pago ({tipo_pago}) de ${monto_pago:,.2f} USD registrado exitosamente.")
                        st.rerun()

        with tab_historico:
            st.subheader("⚡ Saldar Deuda Histórica / Marcar Factura como Pagada")
            selected_inv_hist = st.selectbox("Seleccione Embarque / Invoice a Saldar *", list(invoices_map.keys()), format_func=lambda x: invoices_map[x], key="hist_pago_inv_sel")
            
            row_hist = df_emb[df_emb['num_invoice'] == selected_inv_hist].iloc[0]
            monto_fact = float(row_hist['monto_factura']) if pd.notna(row_hist.get('monto_factura')) else 0.0
            
            res_p_hist = supabase.table("pagos_embarques").select("monto").eq("num_invoice", selected_inv_hist).eq("tipo_pago", "Pago a Fábrica").execute()
            df_p_hist = pd.DataFrame(res_p_hist.data) if res_p_hist.data else pd.DataFrame()
            monto_abonado_hist = df_p_hist['monto'].sum() if not df_p_hist.empty else 0.0
            saldo_pend_hist = max(0.0, monto_fact - monto_abonado_hist)
            
            col_h1, col_h2, col_h3 = st.columns(3)
            col_h1.metric("Monto Total Factura", f"${monto_fact:,.2f} USD")
            col_h2.metric("Abonos Registrados", f"${monto_abonado_hist:,.2f} USD")
            col_h3.metric("Saldo Pendiente Actual", f"${saldo_pend_hist:,.2f} USD")
            
            st.markdown("---")
            with st.form("form_saldar_deuda_historica"):
                monto_saldar_input = st.number_input("Monto a Saldar ($ USD) *", value=float(saldo_pend_hist if saldo_pend_hist > 0 else monto_fact), min_value=0.0, step=100.0, format="%.2f")
                ref_saldar_input = st.text_input("Nota / Referencia", value="PAGO_HISTORICO_OK")
                btn_saldar_submit = st.form_submit_button("✅ Marcar Factura como Totalmente Pagada", type="primary", use_container_width=True)
                
                if btn_saldar_submit:
                    monto_a_registrar = monto_saldar_input if monto_saldar_input > 0 else saldo_pend_hist
                    if monto_a_registrar > 0:
                        supabase.table("pagos_embarques").insert({
                            "num_invoice": selected_inv_hist, "tipo_pago": "Pago a Fábrica",
                            "banco": "CIERRE HISTÓRICO / SINC. DEUDA", "monto": monto_a_registrar,
                            "fecha_pago": str(date.today()), "referencia": ref_saldar_input, "path_comprobante": None
                        }).execute()

                        # Cambio automático de estatus a 'En Producción' si estaba en 'Pendiente Pago'
                        res_c = supabase.table("embarques").select("estatus").eq("num_invoice", selected_inv_hist).execute()
                        if res_c.data and res_c.data[0]['estatus'] == "Pendiente Pago":
                            supabase.table("embarques").update({"estatus": "En Producción"}).eq("num_invoice", selected_inv_hist).execute()

                        st.success(f"🎉 Factura {selected_inv_hist} saldada exitosamente!")
                        st.rerun()

        with tab_editar:
            st.subheader("🛠️ Modificar o Eliminar un Pago Registrado")
            res_all_p = supabase.table("pagos_embarques").select("*").order("id", desc=True).execute()
            df_all_pagos = pd.DataFrame(res_all_p.data) if res_all_p.data else pd.DataFrame()

            if not df_all_pagos.empty:
                pagos_map = {row['id']: f"ID #{row['id']} | Inv: {row['num_invoice']} | [{row['tipo_pago']}] | Ref: {row['referencia']} | Monto: ${row['monto']:,.2f} USD" for _, row in df_all_pagos.iterrows()}
                selected_pago_id = st.selectbox("Selecciona el pago que deseas modificar o eliminar:", list(pagos_map.keys()), format_func=lambda x: pagos_map[x])
                pago_row = df_all_pagos[df_all_pagos['id'] == selected_pago_id].iloc[0]

                with st.form("form_edit_pago"):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        tipo_pago_edit = st.selectbox("Tipo de Pago", TIPO_PAGO_LISTA, index=TIPO_PAGO_LISTA.index(pago_row['tipo_pago']) if pago_row['tipo_pago'] in TIPO_PAGO_LISTA else 0)
                        banco_pago_edit = st.selectbox("Banco de Origen", BANCOS_LISTA, index=BANCOS_LISTA.index(pago_row['banco']) if pago_row['banco'] in BANCOS_LISTA else 0)
                        monto_pago_edit = st.number_input("Monto del Abono ($ USD)", min_value=0.01, value=float(pago_row['monto']), step=100.0, format="%.2f")
                    with col_e2:
                        fecha_pago_edit = st.date_input("Fecha del Pago", value=safe_parse_date(pago_row['fecha_pago']))
                        num_ref_edit = st.text_input("Número de Referencia", value=str(pago_row.get('referencia') or ''))
                        file_comp_edit = st.file_uploader("Reemplazar Comprobante (Opcional)", type=["png", "jpg", "jpeg", "pdf"])

                    col_b1, col_b2 = st.columns(2)
                    with col_b1: submit_pago_edit = st.form_submit_button("💾 Guardar Cambios en Pago", type="primary", use_container_width=True)
                    with col_b2: delete_pago = st.form_submit_button("🗑️ ELIMINAR ESTE PAGO", type="secondary", use_container_width=True)

                if submit_pago_edit:
                    new_path = upload_file_to_supabase(file_comp_edit, f"{pago_row['num_invoice']}_{num_ref_edit}", "COMP", bucket="comprobantes") if file_comp_edit else clean_url(pago_row.get('path_comprobante'))
                    supabase.table("pagos_embarques").update({
                        "tipo_pago": tipo_pago_edit, "banco": banco_pago_edit, "monto": monto_pago_edit,
                        "fecha_pago": str(fecha_pago_edit), "referencia": num_ref_edit, "path_comprobante": new_path
                    }).eq("id", selected_pago_id).execute()
                    st.success("✅ Pago actualizado.")
                    st.rerun()

                if delete_pago:
                    supabase.table("pagos_embarques").delete().eq("id", selected_pago_id).execute()
                    st.warning("🗑️ Pago eliminado.")
                    st.rerun()

# --- MENÚ 4: CARGA MASIVA ---
elif menu == "📊 Carga Masiva (Excel/CSV)" and role == "admin":
    st.title("📊 Carga Masiva de Embarques")
    sample_data = pd.DataFrame([{
        "num_invoice": "INV-1001", "num_bl": "BL-998877", "num_contenedor": "MSCU1234567",
        "naviera": "MSC", "fabricante": "Tech Corp", "producto": "Preforma PET 20g Cristal",
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
            st.dataframe(df_upload.head(10), use_container_width=True)

            if 'num_invoice' in df_upload.columns and st.button("🚀 Procesar e Importar a Supabase", type="primary"):
                n_up, n_new = 0, 0
                for _, row in df_upload.iterrows():
                    inv = str(row.get('num_invoice', '')).strip()
                    if not inv or inv.lower() in ['nan', 'none', '']: continue
                    
                    payload = {
                        "num_invoice": inv, "num_bl": str(row.get('num_bl', '')),
                        "num_contenedor": str(row.get('num_contenedor', '')), "naviera": str(row.get('naviera', '')),
                        "fabricante": str(row.get('fabricante', '')), "producto": str(row.get('producto', '')),
                        "origen": str(row.get('origen', 'China')), "destino": str(row.get('destino', 'Venezuela')),
                        "eta": str(row.get('eta', '')), "estatus": str(row.get('estatus', 'Pendiente Pago')),
                        "agente_carga": str(row.get('agente_carga', '')), "agente_aduanas": str(row.get('agente_aduanas', '')),
                        "consignatario": str(row.get('consignatario', '')), "monto_factura": float(row.get('monto_factura', 0.0)) if pd.notna(row.get('monto_factura')) else 0.0
                    }

                    res_check = supabase.table("embarques").select("id").eq("num_invoice", inv).execute()
                    if res_check.data:
                        supabase.table("embarques").update(payload).eq("num_invoice", inv).execute()
                        n_up += 1
                    else:
                        supabase.table("embarques").insert(payload).execute()
                        n_new += 1
                        
                st.success(f"✅ Importación masiva completada: {n_new} creados, {n_up} actualizados.")
                st.rerun()
        except Exception as e:
            st.error(f"Error procesando archivo: {e}")

# --- MENÚ 5: REGISTRO MANUAL (CON CATÁLOGOS INTEGRADOS) ---
elif menu == "➕ Cargar Nuevo Embarque" and role == "admin":
    st.title("➕ Registrar Nuevo Embarque Manual")
    st.caption("Carga individual utilizando las listas preseleccionables de tus Catálogos Maestros")

    # Cargar catálogos para los selectbox
    cat_fab = [p['nombre'] for p in get_catalogo_proveedores("Fabricante")]
    cat_ff = [p['nombre'] for p in get_catalogo_proveedores("Freight Forwarder")]
    cat_aduanas = [p['nombre'] for p in get_catalogo_proveedores("Agente de Aduanas")]
    cat_cons = [c['nombre'] for c in get_catalogo_consignatarios()]
    cat_prods = [f"{pr['categoria']} - {pr['nombre']} ({pr.get('gramaje','') or ''} {pr.get('color','') or ''})".strip() for pr in get_catalogo_productos()]

    with st.form("form_embarque", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            num_invoice = st.text_input("Número de Invoice *")
            
            # Selectbox dinámico Fabricantes
            sel_fab = st.selectbox("Fabricante / Proveedor", ["-- Seleccionar de Catálogo --", "-- Escribir Manualmente --"] + cat_fab)
            if sel_fab == "-- Escribir Manualmente --":
                fabricante = st.text_input("Nombre Fabricante (Manual)")
            elif sel_fab != "-- Seleccionar de Catálogo --":
                fabricante = sel_fab
            else:
                fabricante = ""

            monto_factura = st.number_input("Monto Total Factura ($ USD)", min_value=0.0, step=100.0, format="%.2f")
            
            # Selectbox dinámico Productos
            sel_prod = st.selectbox("Producto (Catálogo Maestros)", ["-- Seleccionar de Catálogo --", "-- Escribir Manualmente --"] + cat_prods)
            if sel_prod == "-- Escribir Manualmente --":
                producto = st.text_input("Descripción Producto (Manual)")
            elif sel_prod != "-- Seleccionar de Catálogo --":
                producto = sel_prod
            else:
                producto = ""

            origen = st.text_input("Origen", value="China")
            destino = st.text_input("Destino", value="Venezuela")
        
        with col2:
            num_bl = st.text_input("Número de BL *")
            naviera = st.selectbox("Línea Naviera", NAVIERAS)
            num_contenedor = st.text_input("Número de Contenedor")
            
            # Selectbox dinámico Forwarders
            sel_ff = st.selectbox("Freight Forwarder (Agente Carga)", ["-- Seleccionar de Catálogo --", "-- Escribir Manualmente --"] + cat_ff)
            if sel_ff == "-- Escribir Manualmente --":
                agente_carga = st.text_input("Nombre Agente Carga (Manual)")
            elif sel_ff != "-- Seleccionar de Catálogo --":
                agente_carga = sel_ff
            else:
                agente_carga = ""

            # Selectbox dinámico Agente Aduanas
            sel_ad = st.selectbox("Agente de Aduanas", ["-- Seleccionar de Catálogo --", "-- Escribir Manualmente --"] + cat_aduanas)
            if sel_ad == "-- Escribir Manualmente --":
                agente_aduanas = st.text_input("Nombre Agente Aduanas (Manual)")
            elif sel_ad != "-- Seleccionar de Catálogo --":
                agente_aduanas = sel_ad
            else:
                agente_aduanas = ""

        with col3:
            # Selectbox dinámico Consignatario
            sel_cons = st.selectbox("Consignatario", ["-- Seleccionar de Catálogo --", "-- Escribir Manualmente --"] + cat_cons)
            if sel_cons == "-- Escribir Manualmente --":
                consignatario = st.text_input("Nombre Consignatario (Manual)")
            elif sel_cons != "-- Seleccionar de Catálogo --":
                consignatario = sel_cons
            else:
                consignatario = ""

            eta = st.date_input("Estimado de Arribo (ETA)")
            estatus = st.selectbox("Estatus Inicial", ESTATUS_LISTA, index=0)
        
        st.markdown("### Adjuntar Documentación a Supabase (PDF/Excel)")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            file_packing = st.file_uploader("Packing List (Para Almacén)", type=["pdf", "xlsx"])
            file_invoice = st.file_uploader("Factura Comercial (Invoice)", type=["pdf"])
        with col_f2:
            file_flete = st.file_uploader("Factura de Flete", type=["pdf"])
            file_bl = st.file_uploader("Documento BL", type=["pdf"])
            
        submitted = st.form_submit_button("💾 Guardar y Publicar Embarque", type="primary", use_container_width=True)
        if submitted:
            if not num_invoice or not num_bl:
                st.error("❌ El N° de Invoice y N° de BL son obligatorios.")
            else:
                p_pack = upload_file_to_supabase(file_packing, num_invoice, "PACK")
                p_inv = upload_file_to_supabase(file_invoice, num_invoice, "INV")
                p_fle = upload_file_to_supabase(file_flete, num_invoice, "FLE")
                p_bl = upload_file_to_supabase(file_bl, num_invoice, "BL")
                
                try:
                    supabase.table("embarques").insert({
                        "origen": origen, "destino": destino, "fabricante": fabricante,
                        "num_invoice": num_invoice, "agente_carga": agente_carga,
                        "agente_aduanas": agente_aduanas, "consignatario": consignatario,
                        "producto": producto, "num_bl": num_bl, "naviera": naviera,
                        "num_contenedor": num_contenedor, "eta": str(eta), "estatus": estatus,
                        "path_packing": p_pack, "path_invoice": p_inv, "path_flete": p_fle,
                        "path_bl": p_bl, "monto_factura": monto_factura
                    }).execute()
                    st.success(f"✅ Embarque Invoice {num_invoice} guardado exitosamente.")
                except Exception as e:
                    st.error(f"❌ La Invoice {num_invoice} ya existe o hubo un fallo: {e}")

# --- MENÚ 6: EDITAR EMBARQUE ---
elif menu == "✏️ Editar / Actualizar Embarque" and role == "admin":
    st.title("✏️ Editar Embarque Existente")
    res_emb = supabase.table("embarques").select("*").execute()
    df = pd.DataFrame(res_emb.data) if res_emb.data else pd.DataFrame()
    
    if df.empty:
        st.info("No hay embarques para editar en Supabase.")
    else:
        invoices_list = list(df['num_invoice'].unique())
        selected_invoice = st.selectbox("Selecciona la Invoice a modificar:", invoices_list)
        row = df[df['num_invoice'] == selected_invoice].iloc[0]
        
        with st.form("form_editar_embarque"):
            col1, col2, col3 = st.columns(3)
            with col1:
                num_invoice_edit = st.text_input("Número de Invoice", value=str(row['num_invoice']), disabled=True)
                fabricante_edit = st.text_input("Fabricante / Proveedor", value=str(row.get('fabricante') or ''))
                monto_factura_edit = st.number_input("Monto Total Factura ($ USD)", min_value=0.0, value=float(row.get('monto_factura') or 0.0), step=100.0, format="%.2f")
                producto_edit = st.text_input("Descripción del Producto", value=str(row.get('producto') or ''))
                origen_edit = st.text_input("Origen", value=str(row.get('origen') or ''))
                destino_edit = st.text_input("Destino", value=str(row.get('destino') or ''))
            with col2:
                num_bl_edit = st.text_input("Número de BL", value=str(row.get('num_bl') or ''))
                nav_val = str(row.get('naviera')) if row.get('naviera') in NAVIERAS else NAVIERAS[0]
                naviera_edit = st.selectbox("Línea Naviera", NAVIERAS, index=NAVIERAS.index(nav_val))
                num_contenedor_edit = st.text_input("Número de Contenedor", value=str(row.get('num_contenedor') or ''))
                agente_carga_edit = st.text_input("Agente de Carga", value=str(row.get('agente_carga') or ''))
                agente_aduanas_edit = st.text_input("Agente de Aduanas", value=str(row.get('agente_aduanas') or ''))
            with col3:
                consignatario_edit = st.text_input("Consignatario", value=str(row.get('consignatario') or ''))
                fecha_val = safe_parse_date(row.get('eta'))
                eta_edit = st.date_input("Estimado de Arribo (ETA)", value=fecha_val)
                est_val = str(row.get('estatus')) if row.get('estatus') in ESTATUS_LISTA else ESTATUS_LISTA[0]
                estatus_edit = st.selectbox("Estatus Actualizado", ESTATUS_LISTA, index=ESTATUS_LISTA.index(est_val))
            
            st.markdown("### Actualizar / Reemplazar Documentos (Opcional)")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                new_file_packing = st.file_uploader("Nuevo Packing List", type=["pdf", "xlsx"], key="edit_pack")
                new_file_invoice = st.file_uploader("Nueva Factura Comercial", type=["pdf"], key="edit_inv")
            with col_f2:
                new_file_flete = st.file_uploader("Nueva Factura Flete", type=["pdf"], key="edit_fle")
                new_file_bl = st.file_uploader("Nuevo BL", type=["pdf"], key="edit_bl")

            submit_edit = st.form_submit_button("💾 Guardar Cambios en Supabase", type="primary", use_container_width=True)
            if submit_edit:
                p_pack = upload_file_to_supabase(new_file_packing, selected_invoice, "PACK") if new_file_packing else clean_url(row.get('path_packing'))
                p_inv = upload_file_to_supabase(new_file_invoice, selected_invoice, "INV") if new_file_invoice else clean_url(row.get('path_invoice'))
                p_fle = upload_file_to_supabase(new_file_flete, selected_invoice, "FLE") if new_file_flete else clean_url(row.get('path_flete'))
                p_bl = upload_file_to_supabase(new_file_bl, selected_invoice, "BL") if new_file_bl else clean_url(row.get('path_bl'))
                
                update_payload = {
                    "origen": origen_edit, "destino": destino_edit, "fabricante": fabricante_edit,
                    "agente_carga": agente_carga_edit, "agente_aduanas": agente_aduanas_edit,
                    "consignatario": consignatario_edit, "producto": producto_edit, "num_bl": num_bl_edit,
                    "naviera": naviera_edit, "num_contenedor": num_contenedor_edit, "eta": str(eta_edit),
                    "estatus": estatus_edit, "path_packing": p_pack, "path_invoice": p_inv,
                    "path_flete": p_fle, "path_bl": p_bl, "monto_factura": monto_factura_edit
                }

                if estatus_edit == "Entregado" and row.get('estatus') != "Entregado":
                    update_payload["fecha_entrega"] = str(date.today())
                    update_payload["dias_en_aduana"] = max(0, (date.today() - eta_edit).days)

                try:
                    supabase.table("embarques").update(update_payload).eq("num_invoice", selected_invoice).execute()
                    st.success(f"✅ Embarque Invoice {selected_invoice} actualizado correctamente.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar cambios: {e}")
