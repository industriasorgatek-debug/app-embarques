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
# FUNCIONES DE CONFIGURACIÓN GLOBAL (MODO MANTENIMIENTO)
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

# Inicializar Variables de Sesión
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "user_role" not in st.session_state: st.session_state.user_role = None
if "user_dept" not in st.session_state: st.session_state.user_dept = None
if "editing_invoice" not in st.session_state: st.session_state.editing_invoice = None
if "preselected_pago_invoice" not in st.session_state: st.session_state.preselected_pago_invoice = None
if "pending_nav_menu" not in st.session_state: st.session_state.pending_nav_menu = None

# COMPROBAR MODO MANTENIMIENTO GLOBAL
modo_mantenimiento_activo = get_maintenance_mode()

# =============================================================
# 🔒 PANTALLA DE BLOQUEO DE MANTENIMIENTO (INFRANQUEABLE)
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
    
    ref = cont if cont and cont not in ['NONE', 'NAN', ''] else bl
    if not ref or ref in ['NONE', 'NAN', '']:
        return None, None, "⚠️ Sin Contenedor / BL asignado"

    encoded_ref = urllib.parse.quote(ref)
    
    if "MSC" in nav:
        url, label = f"https://www.msc.com/en/track-a-shipment?number={encoded_ref}", "🌐 Rastrear en MSC"
    elif "MAERSK" in nav:
        url, label = f"https://www.maersk.com/tracking/{encoded_ref}", "🌐 Rastrear en Maersk"
    elif "CMA" in nav:
        url, label = f"https://www.cma-cgm.com/ebusiness/tracking/search?SearchBy=Container&Reference={encoded_ref}", "🌐 Rastrear en CMA CGM"
    elif "HAPAG" in nav:
        url, label = f"https://www.hapag-lloyd.com/en/online-business/track/track-by-container.html?container={encoded_ref}", "🌐 Rastrear en Hapag-Lloyd"
    elif "ONE" in nav:
        url, label = f"https://ecomm.one-line.com/one-ecom/cargo-tracking?searchType=C&number={encoded_ref}", "🌐 Rastrear en ONE Line"
    elif "COSCO" in nav:
        url, label = f"https://lines.coscoshipping.com/ebusiness/cargo-tracking?type=CONTAINER_NO&number={encoded_ref}", "🌐 Rastrear en COSCO"
    elif "EVERGREEN" in nav:
        url, label = "https://www.shipmentlink.com/tms/servlet/TDB1_CargoTracking.do", "🌐 Portal Evergreen"
    else:
        url, label = f"https://www.searates.com/container/tracking/?container={encoded_ref}", "🌐 Rastrear en SeaRates"

    return url, label, f"Ref: `{ref}` ({nav})"

# NUEVA LÓGICA DE ETA (CAMBIO 1)
def get_eta_status(eta_val, estatus_val, row_data=None):
    if pd.isna(eta_val) or str(eta_val).strip() in ['', 'None', 'nan', 'NaT']:
        return "⚪ **ETA:** No especificada", "info"
    
    eta_date = safe_parse_date(eta_val)
    today = date.today()
    diff = (eta_date - today).days
    estatus_clean = str(estatus_val).strip()

    if estatus_clean == "Entregado":
        dias_ad = row_data.get('dias_en_aduana') if row_data and pd.notna(row_data.get('dias_en_aduana')) else max(0, (safe_parse_date(row_data.get('fecha_entrega', today)) - eta_date).days if row_data else 0)
        return f"✅ **Estatus:** ENTREGADO el {safe_parse_date(row_data.get('fecha_entrega', today)).strftime('%d/%m/%Y')} (Permaneció **{dias_ad} día(s)** en Aduana/Puerto)", "success"
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

# PDF MEJORADO CON DÍAS EN ADUANA Y COMENTARIOS (CAMBIO 3)
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

    # Lógica de cálculo de días en aduana para el PDF
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

    # IMPRIMIR COMENTARIOS EN EL PDF (CAMBIO 3)
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

# Aplicar redirección pendiente de menú antes de crear el widget del sidebar
if st.session_state.pending_nav_menu is not None:
    st.session_state.nav_menu = st.session_state.pending_nav_menu
    st.session_state.pending_nav_menu = None

menu = st.sidebar.radio("Navegación", options, key="nav_menu")

# -------------------------------------------------------------
# INTERRUPTOR DE MODO MANTENIMIENTO (SOLO VISIBLE PARA COMPRAS)
# -------------------------------------------------------------
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

# BANNER DE ADVERTENCIA PARA COMPRAS SI MANTENIMIENTO ESTÁ ACTIVO
if role == "admin" and modo_mantenimiento_activo:
    st.warning("🚨 **MODO MANTENIMIENTO ACTIVADO GLOBALMENTE:** Almacén y Administración tienen el acceso bloqueado hasta que desactives el interruptor en el menú lateral.")

# =============================================================
# VISTA 0: 📊 DASHBOARD GENERAL (ADAPTABLE POR ROL)
# =============================================================
if menu == "📊 Dashboard General":
    st.title(f"📊 Dashboard de Control — {st.session_state.user_dept}")
    st.caption("Visión analítica integrada en tiempo real basada en la información de Supabase")

    res_emb = supabase.table("embarques").select("*").execute()
    df_db = pd.DataFrame(res_emb.data) if res_emb.data else pd.DataFrame()

    res_pag = supabase.table("pagos_embarques").select("*").execute()
    df_pagos_db = pd.DataFrame(res_pag.data) if res_pag.data else pd.DataFrame()

    res_doc = supabase.table("documentos_embarque").select("*").execute()
    df_docs_db = pd.DataFrame(res_doc.data) if res_doc.data else pd.DataFrame()

    if df_db.empty:
        st.info("No hay datos registrados aún para generar indicadores en el Dashboard.")
    else:
        today = date.today()
        df_db['eta_dt'] = pd.to_datetime(df_db['eta'], errors='coerce')
        
        # Filtros de cargas activas
        df_activas = df_db[df_db['estatus'] != 'Entregado']
        
        # Arribos del mes actual (Entregadas o en curso)
        df_db['eta_month_year'] = df_db['eta_dt'].dt.strftime('%m/%Y')
        current_my = today.strftime('%m/%Y')
        df_entregadas_mes = df_db[(df_db['estatus'] == 'Entregado') & (df_db['eta_month_year'] == current_my)]

        # --- A) COMPRAS (ADMIN) ---
        if role == "admin":
            invoices_pago_ff = df_pagos_db[df_pagos_db['tipo_pago'] == 'Pago a Freight Forwarder']['num_invoice'].unique() if not df_pagos_db.empty else []
            
            # Deuda Fábrica
            monto_total_facturas = df_activas['monto_factura'].fillna(0).sum()
            df_pagos_fab = df_pagos_db[df_pagos_db['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos_db.empty else pd.DataFrame()
            total_abonado_fab = df_pagos_fab['monto'].sum() if not df_pagos_fab.empty else 0.0
            saldo_total_fabrica = max(0.0, monto_total_facturas - total_abonado_fab)

            # Contadores de alertas (CAMBIO 1)
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

        # --- B) ALMACÉN ---
        elif role == "almacen":
            df_camino = df_db[df_db['estatus'].str.contains('Tránsito', na=False)]
            df_aduanas = df_db[df_db['estatus'] == 'En Aduanas']
            
            # Próximos 7 días
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

        # --- C) ADMINISTRACIÓN ---
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
            st.caption("Monitoreo de disponibilidad de Packing List, Factura Comercial, Flete, BL y trámites DUA.")

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

            st.markdown("---")
            st.subheader("📊 Distribución de Cargas por Naviera y Consignatario")
            c_a1, c_a2 = st.columns(2)
            with c_a1:
                st.markdown("##### 🚢 Cargas por Línea Naviera")
                df_nav = df_activas['naviera'].value_counts().reset_index()
                df_nav.columns = ['Naviera', 'Cantidad']
                st.bar_chart(df_nav, x='Naviera', y='Cantidad')
            with c_a2:
                st.markdown("##### 🏢 Cargas por Consignatario")
                df_cons = df_activas['consignatario'].value_counts().reset_index()
                df_cons.columns = ['Consignatario', 'Cantidad']
                st.bar_chart(df_cons, x='Consignatario', y='Cantidad')

# --- VISTA 2: CONTROL DE EMBARQUES ---
elif menu == "📋 Control de Embarques":
    st.title("📋 Control General de Embarques")
    st.caption("Visualización interactiva en la nube, búsqueda en tiempo real y gestión de archivos")
    
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

        # Funciones auxiliares para badges DUA y RECA en la tabla principal
        df['dua_badge'] = df.apply(lambda r: "🟢 Solicitado" if r.get('solicitado_dua') else "🟡 Pendiente", axis=1)
        df['reca_badge'] = df.apply(lambda r: "🟢 Solicitado" if r.get('solicitado_reca') else "🟡 Pendiente", axis=1)

        with st.expander("🔍 **Buscador y Filtros Avanzados**", expanded=True):
            col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1, 1, 1])
            with col_f1: search_term = st.text_input("🔎 Búsqueda Global", placeholder="Escribe N° Invoice, Contenedor, BL, Fabricante o Producto...", key="search_global")
            with col_f2: filtro_estatus = st.selectbox("Estatus del Embarque", ["Todos"] + ESTATUS_LISTA, index=0)
            with col_f3: filtro_naviera = st.selectbox("Línea Naviera", ["Todas"] + NAVIERAS, index=0)
            with col_f4: filtro_flete = st.selectbox("Estado del Flete", ["Todos", "⚠️ PENDIENTE FLETE", "🟢 Flete Pagado", "✅ No Aplica / Pagado"], index=0) if role == "admin" else "Todos"

        df_filtered = df.copy()

        # 🗓️ ORDENAR POR FECHA DE ETA (CRONOLÓGICO)
        df_filtered['eta_dt'] = pd.to_datetime(df_filtered['eta'], errors='coerce')
        df_filtered = df_filtered.sort_values(by='eta_dt', ascending=True, na_position='last')

        # OCULTAR "ENTREGADO" POR DEFECTO SI NO HAY BÚSQUEDA NI FILTRO EXPLÍCITO
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

            # -------------------------------------------------------------
            # 🛡️ VALIDACIÓN Y DETALLES DEL EMBARQUE SELECCIONADO
            # -------------------------------------------------------------
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

                        # Alerta de Flete (Si aplica para Compras)
                        if role == "admin":
                            es_omito_flete = (str(row_data['estatus']).strip() in ["Entregado", "Pendiente Pago"])
                            tiene_pago_ff = selected_invoice in invoices_con_pago_ff
                            if not es_omito_flete and not tiene_pago_ff:
                                st.warning(f"⚠️ **ALERTA DE FLETE:** Este embarque se encuentra **'{row_data['estatus']}'** y **AÚN NO TIENE REGISTRADO EL PAGO AL FREIGHT FORWARDER**.")

                        # AVISO DE ETA / DÍAS EN PUERTO Y ADUANA (CAMBIO 1)
                        eta_msg, eta_type = get_eta_status(row_data['eta'], row_data['estatus'], row_data)
                        if eta_type == "error": st.error(eta_msg)
                        elif eta_type == "warning": st.warning(eta_msg)
                        elif eta_type == "success": st.success(eta_msg)
                        else: st.info(eta_msg)

                        # =============================================================
                        # 📡 RASTREO EN TIEMPO REAL (PLEGABLE Y SOLO COMPRAS)
                        # =============================================================
                        if role == "admin":
                            with st.expander("📡 **Rastreo de Carga en Tiempo Real**", expanded=False):
                                url_track, label_track, info_ref = get_tracking_info(row_data['naviera'], row_data['num_contenedor'], row_data['num_bl'])
                                c_track1, c_track2 = st.columns([3, 1])
                                with c_track1: st.caption(f"Línea Naviera: **{row_data['naviera'] or 'No especificada'}** | {info_ref}")
                                with c_track2:
                                    if url_track: st.link_button(label=label_track, url=url_track, type="primary", use_container_width=True)
                                    else: st.button("🚫 Sin datos para rastrear", disabled=True, use_container_width=True)

                        # =============================================================
                        # 1. 📍 LÍNEA DE TIEMPO Y PROGRESO (PLEGABLE)
                        # =============================================================
                        with st.expander("📍 **LÍNEA DE TIEMPO Y PROGRESO DEL EMBARQUE**", expanded=False):
                            render_timeline(row_data['estatus'])

                        # =============================================================
                        # 📑 CONTROL DE TRAMITACIÓN DE ADUANA (DUA) Y RECA (COMPRAS)
                        # =============================================================
                        if role == "admin" and str(row_data.get('estatus')).strip() in ["En Tránsito 2", "En Tránsito 3", "En Aduanas", "Entregado"]:
                            sol_dua = bool(row_data.get('solicitado_dua', False))
                            f_dua = str(row_data.get('fecha_solicitud_dua') or '')

                            sol_reca = bool(row_data.get('solicitado_reca', False))
                            f_reca = str(row_data.get('fecha_solicitud_reca') or '')

                            with st.expander("📑 **CONTROL DE TRAMITACIÓN DE ADUANA (DUA) Y RECA**", expanded=True):
                                st.caption("Registra el envío de expediente y seguimiento de trámites legales.")
                                c_tr1, c_tr2 = st.columns(2)

                                # PASO 1: DUA
                                with c_tr1:
                                    st.markdown("##### 1️⃣ Solicitud de Borrador DUA (Agente Aduana)")
                                    check_dua = st.checkbox("✅ Marcar como 'DUA Solicitada'", value=sol_dua, key=f"chk_dua_{selected_invoice}")

                                    if check_dua != sol_dua:
                                        now_str = datetime.now().strftime("%d/%m/%Y %H:%M") if check_dua else None
                                        supabase.table("embarques").update({
                                            "solicitado_dua": check_dua,
                                            "fecha_solicitud_dua": now_str
                                        }).eq("num_invoice", selected_invoice).execute()
                                        st.success("✅ Estado DUA actualizado.")
                                        st.rerun()

                                    if check_dua:
                                        st.success(f"🟢 **DUA Solicitada** el `{f_dua}`")
                                    else:
                                        st.warning("⏳ **DUA Pendiente:** Aún no solicitada al Agente de Aduana.")

                                # PASO 2: RECA
                                with c_tr2:
                                    st.markdown("##### 2️⃣ Solicitud de RECA (Exoneración)")
                                    check_reca = st.checkbox("✅ Marcar como 'RECA Solicitado'", value=sol_reca, key=f"chk_reca_{selected_invoice}")

                                    if check_reca != sol_reca:
                                        now_str = datetime.now().strftime("%d/%m/%Y %H:%M") if check_reca else None
                                        supabase.table("embarques").update({
                                            "solicitado_reca": check_reca,
                                            "fecha_solicitud_reca": now_str
                                        }).eq("num_invoice", selected_invoice).execute()
                                        st.success("✅ Estado RECA actualizado.")
                                        st.rerun()

                                    if check_reca:
                                        st.success(f"🟢 **RECA Solicitado** el `{f_reca}`")
                                    else:
                                        st.warning("⏳ **RECA Pendiente:** Aún no enviado al Tramitador de RECA.")

                        # =============================================================
                        # 2. 💼 EXPEDIENTE DIGITAL DEL EMBARQUE (DOCUMENTOS PRINCIPALES)
                        # =============================================================
                        with st.expander("💼 **Expediente Digital del Embarque (Documentos Principales)**", expanded=False):
                            if role == "almacen":
                                docs_principales = [
                                    ("Packing List", row_data.get('path_packing'))
                                ]
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

                        # Expediente Anexo (Solo visible para Compras/Admin)
                        if role == "admin":
                            res_anx = supabase.table("documentos_embarque").select("*").eq("num_invoice", selected_invoice).execute()
                            df_extra_docs = pd.DataFrame(res_anx.data) if res_anx.data else pd.DataFrame()
                            cant_anexos = len(df_extra_docs)
                            
                            with st.expander(f"📁 **Expediente Anexo y Documentación Adicional** ({cant_anexos} archivo(s) cargado(s))", expanded=False):
                                st.markdown("##### ➕ Adjuntar Nuevos Documentos")
                                with st.form(f"form_extra_docs_{selected_invoice}"):
                                    c_exp1, c_exp2 = st.columns(2)
                                    with c_exp1:
                                        tipo_doc_sel = st.selectbox("Tipo / Categoría de Documento *", TIPOS_DOCS_COMPRAS, key=f"sel_tipo_doc_{selected_invoice}")
                                    with c_exp2:
                                        extra_files = st.file_uploader("Seleccionar Archivo(s) *", accept_multiple_files=True, key=f"uploader_extra_{selected_invoice}")

                                    btn_subir_extra = st.form_submit_button("📤 Guardar Documentos en la Nube", type="primary", use_container_width=True)

                                    if btn_subir_extra:
                                        if not extra_files:
                                            st.error("❌ Debe seleccionar al menos un archivo.")
                                        else:
                                            for ef in extra_files:
                                                e_url = upload_file_to_supabase(ef, selected_invoice, "ANX", bucket="documentos")
                                                supabase.table("documentos_embarque").insert({
                                                    "num_invoice": selected_invoice,
                                                    "tipo_documento": tipo_doc_sel,
                                                    "nombre_archivo": ef.name,
                                                    "path_archivo": e_url,
                                                    "fecha_subida": str(date.today()),
                                                    "subido_por": st.session_state.user_dept
                                                }).execute()
                                            st.success(f"✅ ¡{len(extra_files)} documento(s) adjuntado(s) exitosamente en Supabase!")
                                            st.rerun()

                                st.divider()

                                if not df_extra_docs.empty:
                                    st.markdown("##### 📄 Archivos Anexos Registrados en este Embarque:")
                                    for idx_doc, doc_row in df_extra_docs.iterrows():
                                        c_doc1, c_doc2, c_doc3, c_doc4 = st.columns([2, 3, 2, 1])
                                        c_doc1.write(f"🏷️ **{doc_row['tipo_documento']}**")
                                        c_doc2.write(f"📄 {doc_row['nombre_archivo']}")
                                        c_doc3.caption(f"📅 {doc_row['fecha_subida']} ({doc_row['subido_por']})")
                                        
                                        path_anx = clean_url(doc_row['path_archivo'])
                                        with c_doc4:
                                            if path_anx:
                                                st.link_button("⬇️ Abrir", path_anx, use_container_width=True)
                                            
                                            if st.button("🗑️", key=f"del_extra_{doc_row['id']}", help="Eliminar este archivo"):
                                                supabase.table("documentos_embarque").delete().eq("id", doc_row['id']).execute()
                                                st.success("Documento eliminado.")
                                                st.rerun()
                                        st.divider()
                                else:
                                    st.info("No hay documentos anexos adjuntados para este embarque aún.")

                                st.markdown("##### 📦 Descarga Masiva del Expediente")
                                zip_buffer = generar_zip_expediente(selected_invoice, row_data)
                                st.download_button(
                                    label=f"📦 Descargar Expediente COMPLETO en .ZIP ({selected_invoice})",
                                    data=zip_buffer,
                                    file_name=f"Expediente_Completo_{selected_invoice}.zip",
                                    mime="application/zip",
                                    type="primary",
                                    use_container_width=True,
                                    key=f"btn_zip_{selected_invoice}"
                                )

                        # MÓDULOS ESPECÍFICOS PARA ALMACÉN (CAMBIO 2: REGISTRAR DÍAS EN ADUANA AL ENTREGAR)
                        if role == "almacen":
                            if row_data['estatus'] in ["En Aduanas", "En Tránsito 1", "En Tránsito 2", "En Tránsito 3"]:
                                st.info("💡 **Acción disponible:** Puede marcar este embarque como 'Entregado' al recibirlo en almacén.")
                                if st.button("✅ Marcar como ENTREGADO", type="primary"):
                                    today_str = str(date.today())
                                    eta_date = safe_parse_date(row_data.get('eta'))
                                    dias_aduana_calc = max(0, (date.today() - eta_date).days)
                                    
                                    supabase.table("embarques").update({
                                        "estatus": "Entregado",
                                        "fecha_entrega": today_str,
                                        "dias_en_aduana": dias_aduana_calc
                                    }).eq("num_invoice", selected_invoice).execute()
                                    
                                    st.success(f"¡Estatus actualizado a 'Entregado'! (Permaneció {dias_aduana_calc} día(s) en Aduana).")
                                    st.rerun()

                            if row_data['estatus'] == "Entregado":
                                with st.expander("📸 Cargar Fotos / Reporte de Descarga (Almacén)", expanded=False):
                                    with st.form(f"form_almacen_upload_{selected_invoice}"):
                                        uploaded_descarga_files = st.file_uploader(
                                            "Subir Fotos o Reporte de Descarga", 
                                            accept_multiple_files=True,
                                            key=f"upload_almacen_files_{selected_invoice}"
                                        )
                                        sub_almacen = st.form_submit_button("📤 Subir Fotos a la Nube", type="primary")
                                        if sub_almacen and uploaded_descarga_files:
                                            for f_up in uploaded_descarga_files:
                                                f_url = upload_file_to_supabase(f_up, selected_invoice, "FOTO", bucket="documentos")
                                                supabase.table("documentos_embarque").insert({
                                                    "num_invoice": selected_invoice,
                                                    "tipo_documento": "Fotos de Descarga",
                                                    "nombre_archivo": f_up.name,
                                                    "path_archivo": f_url,
                                                    "fecha_subida": str(date.today()),
                                                    "subido_por": "Almacén"
                                                }).execute()
                                            st.success("✅ Fotos guardadas en Supabase Storage exitosamente.")
                                            st.rerun()

                        # Consulta de Pagos en BD para los siguientes módulos
                        res_p_emb = supabase.table("pagos_embarques").select("*").eq("num_invoice", selected_invoice).execute()
                        df_pagos_emb = pd.DataFrame(res_p_emb.data) if res_p_emb.data else pd.DataFrame()

                        # =============================================================
                        # 3. 💰 BALANCE FINANCIERO DE FÁBRICA (PLEGABLE - COMPRAS)
                        # =============================================================
                        if role == "admin":
                            with st.expander(f"💰 **BALANCE FINANCIERO DE FÁBRICA ({selected_invoice})**", expanded=False):
                                df_pagos_fabrica = df_pagos_emb[df_pagos_emb['tipo_pago'] == 'Pago a Fábrica'] if not df_pagos_emb.empty else pd.DataFrame()
                                monto_total_pagado_fabrica = df_pagos_fabrica['monto'].sum() if not df_pagos_fabrica.empty else 0.0
                                monto_factura = float(row_data['monto_factura']) if pd.notna(row_data.get('monto_factura')) else 0.0
                                saldo_pendiente = max(0.0, monto_factura - monto_total_pagado_fabrica)

                                m1, m2 = st.columns(2)
                                m1.metric("Monto Total Factura (Fábrica)", f"${monto_factura:,.2f} USD")
                                m2.metric("Total Abonado a Fábrica", f"${monto_total_pagado_fabrica:,.2f} USD")
                                
                                if saldo_pendiente <= 0 and monto_factura > 0:
                                    st.success("🟢 **Saldo Pendiente Fábrica:** $0.00 USD — ¡PAGADO COMPLETAMENTE!")
                                elif saldo_pendiente > 0:
                                    st.error(f"🔴 **Saldo Pendiente por Pagar a Fábrica:** ${saldo_pendiente:,.2f} USD")
                                else:
                                    st.info("⚪ **Saldo Pendiente por Pagar a Fábrica:** $0.00 USD")

                        # =============================================================
                        # 4. 📄 HISTORIAL DE PAGOS Y COMPROBANTES REGISTRADOS (PLEGABLE - COMPRAS)
                        # =============================================================
                        if role == "admin":
                            with st.expander("📄 **HISTORIAL DE PAGOS Y COMPROBANTES REGISTRADOS**", expanded=False):
                                if df_pagos_emb.empty:
                                    st.info("No se han registrado pagos o abonos para este embarque.")
                                    if st.button("💳 Registrar Pago para esta Invoice", type="primary", use_container_width=True, key=f"btn_pago_empty_{selected_invoice}"):
                                        st.session_state.preselected_pago_invoice = selected_invoice
                                        st.session_state.pending_nav_menu = "💳 Módulo de Pagos Internacionales"
                                        st.rerun()
                                else:
                                    for idx, p_row in df_pagos_emb.iterrows():
                                        c_p1, c_p2, c_p3, c_p4 = st.columns([2, 2, 2, 2])
                                        badge = "🏭" if p_row['tipo_pago'] == 'Pago a Fábrica' else "🚢"
                                        c_p1.write(f"**Tipo:** {badge} {p_row['tipo_pago']}")
                                        c_p2.write(f"**Banco:** {p_row['banco']}")
                                        c_p3.write(f"**Monto:** ${p_row['monto']:,.2f} USD")
                                        c_p4.write(f"**Ref:** {p_row['referencia']} ({p_row['fecha_pago']})")
                                        
                                        path_comp = clean_url(p_row.get('path_comprobante'))
                                        if path_comp:
                                            st.link_button(f"📄 Ver Comprobante #{p_row['referencia']}", path_comp, use_container_width=True)
                                        st.divider()

                                    if st.button("➕ Registrar Nuevo Abono para esta Invoice", type="secondary", use_container_width=True, key=f"btn_pago_not_empty_{selected_invoice}"):
                                        st.session_state.preselected_pago_invoice = selected_invoice
                                        st.session_state.pending_nav_menu = "💳 Módulo de Pagos Internacionales"
                                        st.rerun()

                        # Consulta de notas escritas en este embarque
                        res_notas = supabase.table("notas_embarque").select("*").eq("num_invoice", selected_invoice).order("id", desc=True).execute()
                        df_notas_emb = pd.DataFrame(res_notas.data) if res_notas.data else pd.DataFrame()

                        # Acciones Rápidas (Edición y PDF) para Compras (CAMBIO 3: PDF INCLUYE COMENTARIOS Y DÍAS EN ADUANA)
                        if role == "admin":
                            col_b1, col_b2 = st.columns(2)
                            with col_b1:
                                if st.button(f"✏️ Desplegar Edición Rápida ({selected_invoice})", type="primary", use_container_width=True):
                                    st.session_state.editing_invoice = selected_invoice

                            with col_b2:
                                try:
                                    pdf_data = generar_pdf_embarque(row_data, df_pagos_emb, df_notas_emb)
                                    st.download_button(label=f"📄 Imprimir Ficha PDF ({selected_invoice})", data=pdf_data, file_name=f"Ficha_Embarque_{selected_invoice}.pdf", mime="application/pdf", type="secondary", use_container_width=True, key=f"btn_pdf_{selected_invoice}")
                                except Exception as e_pdf:
                                    st.error(f"⚠️ Error generando PDF: {e_pdf}")

                        # =============================================================
                        # 5. 💬 BITÁCORA DE COMENTARIOS Y NOVEDADES (VISIBLE PARA TODOS)
                        # =============================================================
                        st.markdown("---")
                        with st.form(key=f"form_nota_{selected_invoice}", clear_on_submit=True):
                            nuevo_comentario = st.text_area(
                                "Agregar observación o comentario sobre esta carga:",
                                placeholder="Escriba aquí cualquier novedad...",
                                max_chars=400,
                                height=80
                            )
                            btn_guardar_nota = st.form_submit_button("💬 Guardar Comentario", type="primary")

                            if btn_guardar_nota:
                                if not nuevo_comentario.strip():
                                    st.warning("⚠️ Escriba un comentario antes de guardar.")
                                else:
                                    fecha_hora_actual = datetime.now().strftime("%d/%m/%Y %H:%M")
                                    supabase.table("notas_embarque").insert({
                                        "num_invoice": selected_invoice,
                                        "usuario": st.session_state.user_dept,
                                        "rol": role,
                                        "comentario": nuevo_comentario.strip(),
                                        "fecha_hora": fecha_hora_actual
                                    }).execute()
                                    st.success("✅ Comentario registrado exitosamente.")
                                    st.rerun()

                        if not df_notas_emb.empty:
                            st.markdown("##### 📜 Historial de Observaciones:")
                            for _, n_row in df_notas_emb.iterrows():
                                if n_row['rol'] == 'admin':
                                    badge = "🛒 Compras"
                                elif n_row['rol'] == 'almacen':
                                    badge = "📦 Almacén"
                                else:
                                    badge = "💼 Administración"
                                
                                st.info(f"**{badge} ({n_row['usuario']})** — `{n_row['fecha_hora']}`\n\n💬 {n_row['comentario']}")
                        else:
                            st.caption("ℹ️ No hay observaciones registradas para esta carga aún.")

        # FORMULARIO DE EDICIÓN RÁPIDA (CAMBIO 2: REGISTRAR DÍAS EN ADUANA SI EDITA A ENTREGADO)
        if role == "admin" and st.session_state.editing_invoice:
            st.markdown("---")
            st.subheader(f"🛠️ Editando Embarque: {st.session_state.editing_invoice}")
            row_data = df[df['num_invoice'] == st.session_state.editing_invoice].iloc[0]
            
            with st.form("form_quick_edit"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.text_input("Número de Invoice", value=str(row_data['num_invoice']), disabled=True)
                    fabricante_e = st.text_input("Fabricante / Proveedor", value=str(row_data.get('fabricante') or ''))
                    monto_factura_e = st.number_input("Monto Total Factura ($ USD)", min_value=0.0, value=float(row_data.get('monto_factura') or 0.0), step=100.0, format="%.2f")
                    producto_e = st.text_input("Descripción del Producto", value=str(row_data.get('producto') or ''))
                    origen_e = st.text_input("Origen", value=str(row_data.get('origen') or ''))
                    destino_e = st.text_input("Destino", value=str(row_data.get('destino') or ''))
                    
                with col2:
                    num_bl_e = st.text_input("Número de BL", value=str(row_data.get('num_bl') or ''))
                    nav_val = str(row_data.get('naviera')) if row_data.get('naviera') in NAVIERAS else NAVIERAS[0]
                    naviera_e = st.selectbox("Línea Naviera", NAVIERAS, index=NAVIERAS.index(nav_val))
                    num_contenedor_e = st.text_input("Número de Contenedor", value=str(row_data.get('num_contenedor') or ''))
                    agente_carga_e = st.text_input("Agente de Carga", value=str(row_data.get('agente_carga') or ''))
                    agente_aduanas_e = st.text_input("Agente de Aduanas", value=str(row_data.get('agente_aduanas') or ''))
                    
                with col3:
                    consignatario_e = st.text_input("Consignatario", value=str(row_data.get('consignatario') or ''))
                    fecha_v = safe_parse_date(row_data.get('eta'))
                    eta_e = st.date_input("Estimado de Arribo (ETA)", value=fecha_v)
                    est_v = str(row_data.get('estatus')) if row_data.get('estatus') in ESTATUS_LISTA else ESTATUS_LISTA[0]
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
                p_pack = upload_file_to_supabase(q_file_pack, st.session_state.editing_invoice, "PACK") if q_file_pack else clean_url(row_data.get('path_packing'))
                p_inv = upload_file_to_supabase(q_file_inv, st.session_state.editing_invoice, "INV") if q_file_inv else clean_url(row_data.get('path_invoice'))
                p_fle = upload_file_to_supabase(q_file_fle, st.session_state.editing_invoice, "FLE") if q_file_fle else clean_url(row_data.get('path_flete'))
                p_bl = upload_file_to_supabase(q_file_bl, st.session_state.editing_invoice, "BL") if q_file_bl else clean_url(row_data.get('path_bl'))
                
                update_payload = {
                    "origen": origen_e, "destino": destino_e, "fabricante": fabricante_e,
                    "agente_carga": agente_carga_e, "agente_aduanas": agente_aduanas_e,
                    "consignatario": consignatario_e, "producto": producto_e, "num_bl": num_bl_e,
                    "naviera": naviera_e, "num_contenedor": num_contenedor_e, "eta": str(eta_e),
                    "estatus": estatus_e, "path_packing": p_pack, "path_invoice": p_inv,
                    "path_flete": p_fle, "path_bl": p_bl, "monto_factura": monto_factura_e
                }

                if estatus_e == "Entregado" and row_data.get('estatus') != "Entregado":
                    update_payload["fecha_entrega"] = str(date.today())
                    update_payload["dias_en_aduana"] = max(0, (date.today() - eta_e).days)

                try:
                    supabase.table("embarques").update(update_payload).eq("num_invoice", st.session_state.editing_invoice).execute()
                    
                    st.session_state.editing_invoice = None
                    st.success("✅ ¡Embarque actualizado con éxito en Supabase!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error guardando en Supabase: {e}")

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
        tab_nuevo, tab_historico, tab_editar = st.tabs([
            "➕ Registrar Nuevo Pago", 
            "✅ Saldar Deuda Histórica", 
            "✏️ Editar / Eliminar Pago Existente"
        ])

        # TAB 1: REGISTRAR NUEVO PAGO NORMAL
        with tab_nuevo:
            st.subheader("➕ Registrar Nuevo Abono / Pago")
            
            # Preselección inteligente si se hace clic desde la tabla
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
                            "num_invoice": selected_inv_key,
                            "tipo_pago": tipo_pago,
                            "banco": banco_pago,
                            "monto": monto_pago,
                            "fecha_pago": str(fecha_pago),
                            "referencia": num_ref,
                            "path_comprobante": file_path_pago
                        }).execute()
                        
                        if tipo_pago == "Pago a Fábrica":
                            res_c = supabase.table("embarques").select("estatus").eq("num_invoice", selected_inv_key).execute()
                            if res_c.data and res_c.data[0]['estatus'] == "Pendiente Pago":
                                supabase.table("embarques").update({"estatus": "En Producción"}).eq("num_invoice", selected_inv_key).execute()
                                st.info("ℹ️ **Estatus Actualizado:** El embarque cambió automáticamente a **'En Producción'**.")

                        st.session_state.preselected_pago_invoice = None
                        st.success(f"✅ Pago ({tipo_pago}) de ${monto_pago:,.2f} USD registrado exitosamente.")
                        st.rerun()

        # TAB 2: MARCAR COMO PAGADO (DEUDA HISTÓRICA)
        with tab_historico:
            st.subheader("⚡ Saldar Deuda Histórica / Marcar Factura como Pagada")
            st.caption("Utiliza esta opción para embarques viejos donde no se dispone de comprobantes bancarios, dejando el saldo de la factura en $0.00 USD.")
            
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
                monto_saldar_input = st.number_input(
                    "Monto a Saldar ($ USD) *", 
                    value=float(saldo_pend_hist if saldo_pend_hist > 0 else monto_fact), 
                    min_value=0.0, 
                    step=100.0, 
                    format="%.2f",
                    help="Monto que se registrará para dejar la factura totalmente pagada"
                )
                ref_saldar_input = st.text_input("Nota / Referencia", value="PAGO_HISTORICO_OK")
                
                btn_saldar_submit = st.form_submit_button("✅ Marcar Factura como Totalmente Pagada", type="primary", use_container_width=True)
                
                if btn_saldar_submit:
                    monto_a_registrar = monto_saldar_input if monto_saldar_input > 0 else saldo_pend_hist
                    if monto_a_registrar <= 0:
                        st.warning("⚠️ Especifique un monto mayor a 0 para saldar.")
                    else:
                        supabase.table("pagos_embarques").insert({
                            "num_invoice": selected_inv_hist,
                            "tipo_pago": "Pago a Fábrica",
                            "banco": "CIERRE HISTÓRICO / SINC. DEUDA",
                            "monto": monto_a_registrar,
                            "fecha_pago": str(date.today()),
                            "referencia": ref_saldar_input,
                            "path_comprobante": None
                        }).execute()
                        
                        res_c = supabase.table("embarques").select("estatus").eq("num_invoice", selected_inv_hist).execute()
                        if res_c.data and res_c.data[0]['estatus'] == "Pendiente Pago":
                            supabase.table("embarques").update({"estatus": "En Producción"}).eq("num_invoice", selected_inv_hist).execute()
                        
                        st.success(f"🎉 ¡Factura {selected_inv_hist} saldada exitosamente por ${monto_a_registrar:,.2f} USD!")
                        st.rerun()

        # TAB 3: EDITAR / ELIMINAR PAGOS EXISTENTES
        with tab_editar:
            st.subheader("🛠️ Modificar o Eliminar un Pago Registrado")
            res_all_p = supabase.table("pagos_embarques").select("*").order("id", desc=True).execute()
            df_all_pagos = pd.DataFrame(res_all_p.data) if res_all_p.data else pd.DataFrame()

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
                        num_ref_edit = st.text_input("Número de Referencia", value=str(pago_row.get('referencia') or ''))
                        file_comp_edit = st.file_uploader("Reemplazar Comprobante (Opcional)", type=["png", "jpg", "jpeg", "pdf"])

                    col_b1, col_b2 = st.columns(2)
                    with col_b1: submit_pago_edit = st.form_submit_button("💾 Guardar Cambios en Pago", type="primary", use_container_width=True)
                    with col_b2: delete_pago = st.form_submit_button("🗑️ ELIMINAR ESTE PAGO", type="secondary", use_container_width=True)

                if submit_pago_edit:
                    if not num_ref_edit or monto_pago_edit <= 0:
                        st.error("❌ El monto debe ser mayor a 0 y la referencia no puede estar vacía.")
                    else:
                        new_path = upload_file_to_supabase(file_comp_edit, f"{pago_row['num_invoice']}_{num_ref_edit}", "COMP", bucket="comprobantes") if file_comp_edit else clean_url(pago_row.get('path_comprobante'))
                        supabase.table("pagos_embarques").update({
                            "tipo_pago": tipo_pago_edit, "banco": banco_pago_edit, "monto": monto_pago_edit,
                            "fecha_pago": str(fecha_pago_edit), "referencia": num_ref_edit, "path_comprobante": new_path
                        }).eq("id", selected_pago_id).execute()
                        
                        st.success(f"✅ ¡El pago ID #{selected_pago_id} ha sido actualizado correctamente!")
                        st.rerun()

                if delete_pago:
                    supabase.table("pagos_embarques").delete().eq("id", selected_pago_id).execute()
                    st.warning(f"🗑️ El pago ID #{selected_pago_id} ha sido eliminado.")
                    st.rerun()

        st.markdown("---")
        st.subheader("📊 Historial General de Pagos Registrados")
        res_all_p = supabase.table("pagos_embarques").select("*").order("id", desc=True).execute()
        df_all_pagos = pd.DataFrame(res_all_p.data) if res_all_p.data else pd.DataFrame()
        if df_all_pagos.empty:
            st.info("No se registra ningún pago en el sistema.")
        else:
            st.dataframe(df_all_pagos[['id', 'num_invoice', 'tipo_pago', 'banco', 'monto', 'fecha_pago', 'referencia']], use_container_width=True, hide_index=True)

# --- MENÚ 4: CARGA MASIVA ---
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
            
            clean_cols = []
            for i, col in enumerate(df_upload.columns):
                if pd.isna(col) or str(col).strip() == '' or 'unnamed' in str(col).lower():
                    clean_cols.append(f"columna_{i+1}")
                else:
                    clean_cols.append(str(col).strip().lower())
            df_upload.columns = clean_cols

            col_map = {
                'invoice': 'num_invoice', 'empresa': 'fabricante', 'agente': 'agente_carga', 
                'ag aduana': 'agente_aduanas', 'consignee': 'consignatario', 'estimado': 'eta', 
                'org /bl / booking': 'num_bl', 'monto': 'monto_factura'
            }
            df_upload.rename(columns=col_map, inplace=True)
            
            df_preview = df_upload.head(10).fillna("")
            st.dataframe(df_preview, use_container_width=True)

            if 'num_invoice' in df_upload.columns and st.button("🚀 Procesar e Importar a Supabase", type="primary"):
                n_up, n_new = 0, 0
                for _, row in df_upload.iterrows():
                    inv = str(row.get('num_invoice', '')).strip()
                    if not inv or inv.lower() in ['nan', 'none', '']: continue
                    
                    bl = str(row.get('num_bl', '')) if pd.notna(row.get('num_bl')) and str(row.get('num_bl')).lower() != 'nan' else ''
                    cont = str(row.get('num_contenedor', '')) if pd.notna(row.get('num_contenedor')) and str(row.get('num_contenedor')).lower() != 'nan' else ''
                    nav = str(row.get('naviera', '')) if pd.notna(row.get('naviera')) and str(row.get('naviera')).lower() != 'nan' else ''
                    fab = str(row.get('fabricante', '')) if pd.notna(row.get('fabricante')) and str(row.get('fabricante')).lower() != 'nan' else ''
                    prod = str(row.get('producto', '')) if pd.notna(row.get('producto')) and str(row.get('producto')).lower() != 'nan' else ''
                    ori = str(row.get('origen', 'China')) if pd.notna(row.get('origen')) and str(row.get('origen')).lower() != 'nan' else 'China'
                    des = str(row.get('destino', 'Venezuela')) if pd.notna(row.get('destino')) and str(row.get('destino')).lower() != 'nan' else 'Venezuela'
                    eta = str(row.get('eta', '')) if pd.notna(row.get('eta')) and str(row.get('eta')).lower() != 'nan' else ''
                    est = str(row.get('estatus', 'Pendiente Pago')) if pd.notna(row.get('estatus')) and str(row.get('estatus')).lower() != 'nan' else 'Pendiente Pago'
                    ag_c = str(row.get('agente_carga', '')) if pd.notna(row.get('agente_carga')) and str(row.get('agente_carga')).lower() != 'nan' else ''
                    ag_a = str(row.get('agente_aduanas', '')) if pd.notna(row.get('agente_aduanas')) and str(row.get('agente_aduanas')).lower() != 'nan' else ''
                    cons = str(row.get('consignatario', '')) if pd.notna(row.get('consignatario')) and str(row.get('consignatario')).lower() != 'nan' else ''
                    
                    try: monto = float(row.get('monto_factura', 0.0)) if pd.notna(row.get('monto_factura')) else 0.0
                    except Exception: monto = 0.0

                    payload = {
                        "num_invoice": inv, "num_bl": bl, "num_contenedor": cont, "naviera": nav,
                        "fabricante": fab, "producto": prod, "origen": ori, "destino": des,
                        "eta": eta, "estatus": est, "agente_carga": ag_c, "agente_aduanas": ag_a,
                        "consignatario": cons, "monto_factura": monto
                    }

                    res_check = supabase.table("embarques").select("id").eq("num_invoice", inv).execute()
                    if res_check.data:
                        supabase.table("embarques").update(payload).eq("num_invoice", inv).execute()
                        n_up += 1
                    else:
                        supabase.table("embarques").insert(payload).execute()
                        n_new += 1
                        
                st.success(f"✅ ¡Éxito en la Nube!: {n_new} nuevos registros, {n_up} actualizados.")
                st.rerun()
        except Exception as e:
            st.error(f"Error procesando archivo: {e}")

# --- MENÚ 5: REGISTRO MANUAL ---
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
        
        st.markdown("### Adjuntar Documentación a Supabase (PDF/Excel)")
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
                    st.success(f"✅ Embarque Invoice {num_invoice} guardado exitosamente en la Nube.")
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

            submit_edit = st.form_submit_button("💾 Guardar Cambios en Supabase")
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
                    
                    st.success(f"✅ Embarque Invoice {selected_invoice} actualizado correctamente en Supabase.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar cambios en Supabase: {e}")


