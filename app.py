import streamlit as st
import sqlite3
import pandas as pd
import os
import shutil
from datetime import datetime
from PIL import Image
import io
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE LA PÁGINA Y ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Control de Embarques e Importaciones",
    page_icon="🚢",
    layout="wide"
)

# Estilo CSS personalizado para limpiar espacio superior
st.markdown("""
    <style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. BASE DE DATOS Y DIRECTORIOS
# -----------------------------------------------------------------------------
UPLOAD_DIR = "archivos_embarques"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_NAME = "importaciones.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS embarques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_invoice TEXT UNIQUE,
            num_contenedor TEXT,
            num_bl TEXT,
            naviera TEXT,
            fabricante TEXT,
            producto TEXT,
            origen TEXT,
            destino TEXT,
            etd TEXT,
            eta TEXT,
            monto_factura REAL,
            costo_flete REAL,
            monto_impuestos REAL,
            estatus TEXT,
            notas TEXT,
            path_packing TEXT,
            path_invoice TEXT,
            path_flete TEXT,
            path_bl TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pagos_embarques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_invoice TEXT,
            tipo_pago TEXT,
            banco TEXT,
            monto REAL,
            referencia TEXT,
            fecha_pago TEXT,
            path_comprobante TEXT,
            FOREIGN KEY(num_invoice) REFERENCES embarques(num_invoice)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_connection():
    return sqlite3.connect(DB_NAME)

def has_valid_file(path):
    return path and isinstance(path, str) and path.strip() != "" and os.path.exists(path)

# -----------------------------------------------------------------------------
# 3. GENERADOR DE PDF
# -----------------------------------------------------------------------------
def generar_pdf_ficha(row, conn):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1E3A8A"),
        spaceAfter=12
    )
    
    h2_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=10,
        spaceAfter=6
    )

    cell_bold = ParagraphStyle('CellB', parent=styles['Normal'], fontSize=9, leading=11, fontName='Helvetica-Bold')
    cell_norm = ParagraphStyle('CellN', parent=styles['Normal'], fontSize=9, leading=11)

    story.append(Paragraph(f"📄 FICHA TÉCNICA Y RESUMEN DE EMBARQUE", title_style))
    story.append(Paragraph(f"<b>Invoice:</b> {row['num_invoice']} | <b>Generado:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", cell_norm))
    story.append(Spacer(1, 10))

    # Tabla General
    data_gen = [
        [Paragraph("Contenedor:", cell_bold), Paragraph(str(row['num_contenedor']), cell_norm),
         Paragraph("Bill of Lading (BL):", cell_bold), Paragraph(str(row['num_bl']), cell_norm)],
        [Paragraph("Naviera:", cell_bold), Paragraph(str(row['naviera']), cell_norm),
         Paragraph("Fabricante:", cell_bold), Paragraph(str(row['fabricante']), cell_norm)],
        [Paragraph("Producto:", cell_bold), Paragraph(str(row['producto']), cell_norm),
         Paragraph("Estatus Actual:", cell_bold), Paragraph(str(row['estatus']), cell_norm)],
        [Paragraph("Origen / Destino:", cell_bold), Paragraph(f"{row['origen']} ➔ {row['destino']}", cell_norm),
         Paragraph("Fechas (ETD / ETA):", cell_bold), Paragraph(f"{row['etd']} / {row['eta']}", cell_norm)]
    ]

    t_gen = Table(data_gen, colWidths=[110, 160, 110, 160])
    t_gen.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    
    story.append(Paragraph("1. Información Logística General", h2_style))
    story.append(t_gen)
    story.append(Spacer(1, 10))

    # Pagos y Balances
    df_pagos = pd.read_sql_query("SELECT * FROM pagos_embarques WHERE num_invoice = ?", conn, params=(row['num_invoice'],))
    monto_fac = float(row['monto_factura']) if pd.notna(row['monto_factura']) else 0.0
    pagos_fabrica = df_pagos[df_pagos['tipo_pago'] == 'Pago a Fábrica']['monto'].sum() if not df_pagos.empty else 0.0
    saldo_fabrica = monto_fac - pagos_fabrica

    data_fin = [
        [Paragraph("Monto Factura (Fábrica):", cell_bold), Paragraph(f"${monto_fac:,.2f} USD", cell_norm),
         Paragraph("Abonado a Fábrica:", cell_bold), Paragraph(f"${pagos_fabrica:,.2f} USD", cell_norm)],
        [Paragraph("Saldo Pendiente Fábrica:", cell_bold), Paragraph(f"${saldo_fabrica:,.2f} USD", cell_bold),
         Paragraph("Costo Flete:", cell_bold), Paragraph(f"${float(row['costo_flete'] or 0):,.2f} USD", cell_norm)]
    ]

    t_fin = Table(data_fin, colWidths=[130, 140, 130, 140])
    t_fin.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F1F5F9")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    story.append(Paragraph("2. Resumen Financiero", h2_style))
    story.append(t_fin)
    story.append(Spacer(1, 10))

    # Historial de Pagos
    story.append(Paragraph("3. Historial de Pagos Registrados", h2_style))
    if df_pagos.empty:
        story.append(Paragraph("No hay pagos registrados para este embarque.", cell_norm))
    else:
        p_data = [[Paragraph("Tipo", cell_bold), Paragraph("Banco", cell_bold), Paragraph("Monto (USD)", cell_bold), Paragraph("Referencia", cell_bold), Paragraph("Fecha", cell_bold)]]
        for _, pr in df_pagos.iterrows():
            p_data.append([
                Paragraph(str(pr['tipo_pago']), cell_norm),
                Paragraph(str(pr['banco']), cell_norm),
                Paragraph(f"${pr['monto']:,.2f}", cell_norm),
                Paragraph(str(pr['referencia']), cell_norm),
                Paragraph(str(pr['fecha_pago']), cell_norm)
            ])
        t_pagos = Table(p_data, colWidths=[110, 100, 100, 120, 110])
        t_pagos.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E2E8F0")),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
            ('PADDING', (0,0), (-1,-1), 5),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(t_pagos)

    doc.build(story)
    buffer.seek(0)
    return buffer

# -----------------------------------------------------------------------------
# 4. CONTROL DE SESIÓN Y LOGIN DE ROLES
# -----------------------------------------------------------------------------
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'role' not in st.session_state:
    st.session_state['role'] = None

def login():
    st.title("🔐 Sistema de Control de Importaciones")
    st.subheader("Iniciar Sesión")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        usuario = st.selectbox("Selecciona tu Rol / Usuario", ["Compras (Admin)", "Administración", "Almacén"])
        password = st.text_input("Contraseña", type="password")
        
        if st.button("Ingresar", type="primary"):
            if usuario == "Compras (Admin)" and password == "admin123":
                st.session_state['logged_in'] = True
                st.session_state['role'] = "admin"
                st.rerun()
            elif usuario == "Administración" and password == "admon123":
                st.session_state['logged_in'] = True
                st.session_state['role'] = "admon"
                st.rerun()
            elif usuario == "Almacén" and password == "almacen123":
                st.session_state['logged_in'] = True
                st.session_state['role'] = "almacen"
                st.rerun()
            else:
                st.error("🔒 Contraseña incorrecta")

if not st.session_state['logged_in']:
    login()
    st.stop()

# -----------------------------------------------------------------------------
# 5. MENÚ PRINCIPAL Y DASHBOARD
# -----------------------------------------------------------------------------
role = st.session_state['role']

with st.sidebar:
    st.title("🚢 Control Importaciones")
    role_names = {"admin": "Compras (Admin)", "admon": "Administración", "almacen": "Almacén"}
    st.info(f"👤 **Rol Actual:** {role_names[role]}")
    
    if st.button("🚪 Cerrar Sesión"):
        st.session_state['logged_in'] = False
        st.session_state['role'] = None
        st.rerun()

    st.markdown("---")
    menu = ["📊 Tabla de Embarques"]
    if role == "admin":
        menu.extend(["➕ Registrar Embarque", "💰 Registrar Pago"])
    
    choice = st.sidebar.radio("Navegación", menu)

conn = get_connection()

# -----------------------------------------------------------------------------
# 6. VISTA 1: TABLA DE EMBARQUES Y DETALLES
# -----------------------------------------------------------------------------
if choice == "📊 Tabla de Embarques":
    st.title("📋 Estado General de Embarques")

    df = pd.read_sql_query("SELECT * FROM embarques", conn)

    if df.empty:
        st.warning("No hay embarques registrados en el sistema.")
    else:
        st.markdown("##### 📌 Lista General de Embarques Registrados")
        
        # Opciones AgGrid para selección de fila
        gb = GridOptionsBuilder.from_dataframe(df[['num_invoice', 'num_contenedor', 'num_bl', 'fabricante', 'producto', 'estatus', 'eta']])
        gb.configure_selection('single', pre_selected_rows=[0])
        gridOptions = gb.build()

        grid_response = AgGrid(
            df,
            gridOptions=gridOptions,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            height=250,
            fit_columns_on_grid_load=True,
            key="grid_main"
        )

        selected_rows = grid_response['selected_rows']

        # Si el usuario seleccionó una fila
        if selected_rows is not None and len(selected_rows) > 0:
            if isinstance(selected_rows, pd.DataFrame):
                row_data = selected_rows.iloc[0].to_dict()
            else:
                row_data = selected_rows[0]

            selected_invoice = row_data['num_invoice']
            st.markdown("---")
            st.subheader(f"🔍 Detalle del Embarque: **{selected_invoice}**")

            # -----------------------------------------------------------------
            # COMPORTAMIENTO SEGÚN EL ROL
            # -----------------------------------------------------------------
            
            # 1. ROL ALMACÉN
            if role == "almacen":
                st.subheader("📦 Lista de Embarques (Recepción de Mercancía)")
                st.info("💡 **Instrucciones:** Haz **doble clic** sobre el estatus de un embarque que esté en *En Aduanas* para cambiarlo a *Entregado*.")

                df_almacen = df[['num_invoice', 'num_contenedor', 'num_bl', 'naviera', 'fabricante', 'producto', 'origen', 'destino', 'eta', 'estatus']].copy()
                
                gb = GridOptionsBuilder.from_dataframe(df_almacen)
                gb.configure_default_column(editable=False)
                gb.configure_column(
                    field="estatus",
                    header_name="Estatus",
                    editable=True,
                    cellEditor='agSelectCellEditor',
                    cellEditorParams={'values': ['En Aduanas', 'Entregado']}
                )
                
                gridOptions = gb.build()

                grid_response_alm = AgGrid(
                    df_almacen,
                    gridOptions=gridOptions,
                    update_mode=GridUpdateMode.VALUE_CHANGED,
                    height=350,
                    fit_columns_on_grid_load=True,
                    key="aggrid_almacen"
                )

                df_modificado = grid_response_alm['data']

                if not df_almacen.equals(df_modificado):
                    for index, row in df_modificado.iterrows():
                        estatus_anterior = df_almacen.loc[index, 'estatus']
                        estatus_nuevo = row['estatus']

                        if estatus_anterior != estatus_nuevo:
                            if estatus_anterior == "En Aduanas" and estatus_nuevo == "Entregado":
                                c = conn.cursor()
                                c.execute("UPDATE embarques SET estatus = 'Entregado' WHERE num_invoice = ?", (row['num_invoice'],))
                                conn.commit()
                                st.success(f"✅ ¡Embarque **{row['num_invoice']}** marcado como **Entregado**!")
                                st.rerun()
                            else:
                                st.warning(f"⚠️ Solo está permitido cambiar embarques que estén 'En Aduanas' a 'Entregado'.")
                                st.rerun()

            # 2. ROL ADMINISTRACIÓN
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

            # 3. ROL COMPRAS (ADMIN)
            elif role == "admin":
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
                                    key=f"main_compras_{label}_{selected_invoice}"
                                )
                        else:
                            st.caption(f"❌ {label}: No cargado")

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
                    st.success(f"🟢 **Saldo Pendiente Fábrica:** $0.00 USD — ¡PAGADO COMPLETAMENTE!")
                elif saldo_pendiente > 0:
                    st.error(f"🔴 **Saldo Pendiente por Pagar a Fábrica:** ${saldo_pendiente:,.2f} USD")
                else:
                    st.info(f"⚪ **Saldo Pendiente por Pagar a Fábrica:** $0.00 USD")

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
                                st.download_button(
                                    label=f"📄 Ver Comprobante #{p_row['referencia']}",
                                    data=f_comp,
                                    file_name=os.path.basename(p_row['path_comprobante']),
                                    mime="application/octet-stream",
                                    key=f"dl_pago_{p_row['id']}"
                                )
                        st.divider()

            # -----------------------------------------------------------------
            # BOTONES DE ACCIÓN COMPARTIDOS (PDF / EDICIÓN)
            # -----------------------------------------------------------------
            st.markdown("---")
            c_bot1, c_bot2 = st.columns([1, 2])
            
            with c_bot1:
                pdf_bytes = generar_pdf_ficha(row_data, conn)
                st.download_button(
                    label="📄 Imprimir / Descargar Ficha PDF",
                    data=pdf_bytes,
                    file_name=f"Ficha_Embarque_{selected_invoice}.pdf",
                    mime="application/pdf",
                    key=f"pdf_btn_{selected_invoice}"
                )

            if role == "admin":
                with c_bot2:
                    with st.expander("✏️ Edición Rápida de Datos del Embarque"):
                        with st.form(f"form_edit_{selected_invoice}"):
                            e_contenedor = st.text_input("Número de Contenedor", value=str(row_data['num_contenedor'] or ''))
                            e_bl = st.text_input("Número de BL", value=str(row_data['num_bl'] or ''))
                            e_naviera = st.text_input("Naviera", value=str(row_data['naviera'] or ''))
                            e_fabricante = st.text_input("Fabricante", value=str(row_data['fabricante'] or ''))
                            e_producto = st.text_input("Producto", value=str(row_data['producto'] or ''))
                            
                            st_opts = ["En Producción", "En Tránsito Marítimo", "En Aduanas", "Entregado"]
                            cur_st_idx = st_opts.index(row_data['estatus']) if row_data['estatus'] in st_opts else 0
                            e_estatus = st.selectbox("Estatus", st_opts, index=cur_st_idx)
                            
                            e_notas = st.text_area("Notas / Observaciones", value=str(row_data['notas'] or ''))

                            if st.form_submit_button("💾 Guardar Cambios"):
                                c = conn.cursor()
                                c.execute('''
                                    UPDATE embarques 
                                    SET num_contenedor = ?, num_bl = ?, naviera = ?, fabricante = ?, producto = ?, estatus = ?, notas = ?
                                    WHERE num_invoice = ?
                                ''', (e_contenedor, e_bl, e_naviera, e_fabricante, e_producto, e_estatus, e_notas, selected_invoice))
                                conn.commit()
                                st.success("✅ ¡Datos del embarque actualizados correctamente!")
                                st.rerun()

# -----------------------------------------------------------------------------
# 7. VISTA 2: REGISTRAR NUEVO EMBARQUE (SOLO ADMIN)
# -----------------------------------------------------------------------------
elif choice == "➕ Registrar Embarque" and role == "admin":
    st.title("➕ Registro de Nuevo Embarque")

    with st.form("form_nuevo_embarque", clear_on_submit=True):
        st.subheader("📌 Datos Principales")
        c1, c2, c3 = st.columns(3)
        num_invoice = c1.text_input("Número de Invoice / Factura *")
        num_contenedor = c2.text_input("Número de Contenedor")
        num_bl = c3.text_input("Número de Bill of Lading (BL)")

        c4, c5, c6 = st.columns(3)
        naviera = c4.text_input("Naviera")
        fabricante = c5.text_input("Fabricante / Proveedor")
        producto = c6.text_input("Producto / Mercancía")

        st.subheader("🗺️ Ruta y Fechas")
        r1, r2, r3, r4 = st.columns(4)
        origen = r1.text_input("Puerto Origen", value="China")
        destino = r2.text_input("Puerto Destino", value="Venezuela")
        etd = r3.date_input("Fecha Salida (ETD)").strftime("%Y-%m-%d")
        eta = r4.date_input("Fecha LLegada Estimada (ETA)").strftime("%Y-%m-%d")

        st.subheader("💰 Costos y Estatus")
        m1, m2, m3, m4 = st.columns(4)
        monto_factura = m1.number_input("Monto Factura (USD)", min_value=0.0, step=100.0)
        costo_flete = m2.number_input("Costo Flete (USD)", min_value=0.0, step=100.0)
        monto_impuestos = m3.number_input("Estimado Impuestos (USD)", min_value=0.0, step=100.0)
        estatus = m4.selectbox("Estatus Inicial", ["En Producción", "En Tránsito Marítimo", "En Aduanas", "Entregado"])

        notas = st.text_area("Notas Adicionales")

        st.subheader("📁 Carga de Documentos Iniciales")
        d1, d2 = st.columns(2)
        f_packing = d1.file_uploader("Packing List (PDF/Imagen)", type=['pdf', 'png', 'jpg', 'jpeg'])
        f_invoice = d2.file_uploader("Factura Comercial (PDF/Imagen)", type=['pdf', 'png', 'jpg', 'jpeg'])

        d3, d4 = st.columns(2)
        f_flete = d3.file_uploader("Factura de Flete (PDF/Imagen)", type=['pdf', 'png', 'jpg', 'jpeg'])
        f_bl = d4.file_uploader("Bill of Lading - BL (PDF/Imagen)", type=['pdf', 'png', 'jpg', 'jpeg'])

        submitted = st.form_submit_button("🚀 Guardar Embarque", type="primary")

        if submitted:
            if not num_invoice:
                st.error("⚠️ El número de invoice es obligatorio.")
            else:
                def guardar_archivo(file_obj, prefix):
                    if file_obj is not None:
                        ext = os.path.splitext(file_obj.name)[1]
                        fname = f"{prefix}_{num_invoice}{ext}"
                        fpath = os.path.join(UPLOAD_DIR, fname)
                        with open(fpath, "wb") as f:
                            f.write(file_obj.getbuffer())
                        return fpath
                    return None

                p_packing = guardar_archivo(f_packing, "packing")
                p_invoice = guardar_archivo(f_invoice, "invoice")
                p_flete = guardar_archivo(f_flete, "flete")
                p_bl = guardar_archivo(f_bl, "bl")

                try:
                    c = conn.cursor()
                    c.execute('''
                        INSERT INTO embarques (
                            num_invoice, num_contenedor, num_bl, naviera, fabricante, producto,
                            origen, destino, etd, eta, monto_factura, costo_flete, monto_impuestos,
                            estatus, notas, path_packing, path_invoice, path_flete, path_bl
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        num_invoice, num_contenedor, num_bl, naviera, fabricante, producto,
                        origen, destino, etd, eta, monto_factura, costo_flete, monto_impuestos,
                        estatus, notas, p_packing, p_invoice, p_flete, p_bl
                    ))
                    conn.commit()
                    st.success(f"✅ Embarque **{num_invoice}** registrado exitosamente.")
                except sqlite3.IntegrityError:
                    st.error("⚠️ Ya existe un embarque registrado con este mismo Número de Invoice.")

# -----------------------------------------------------------------------------
# 8. VISTA 3: REGISTRAR PAGO / ABONO (SOLO ADMIN)
# -----------------------------------------------------------------------------
elif choice == "💰 Registrar Pago" and role == "admin":
    st.title("💰 Registro de Pagos y Comprobantes")

    df_emb = pd.read_sql_query("SELECT num_invoice, fabricante, monto_factura FROM embarques", conn)

    if df_emb.empty:
        st.warning("Debe registrar al menos un embarque antes de agregar pagos.")
    else:
        with st.form("form_pago", clear_on_submit=True):
            selected_inv = st.selectbox("Selecciona el Embarque / Invoice *", df_emb['num_invoice'].tolist())
            
            p1, p2 = st.columns(2)
            tipo_pago = p1.selectbox("Tipo de Pago *", ["Pago a Fábrica", "Pago de Flete", "Pago de Impuestos / Aduana", "Otro Servicio"])
            banco = p2.text_input("Banco / Entidad Emisora *", value="Banesco / Transferencia")

            p3, p4 = st.columns(2)
            monto_pago = p3.number_input("Monto Pagado (USD) *", min_value=0.01, step=50.0)
            referencia = p4.text_input("Número de Referencia / Transferencia *")

            fecha_pago = st.date_input("Fecha del Pago").strftime("%Y-%m-%d")
            f_comprobante = st.file_uploader("Adjuntar Comprobante de Pago (PDF/Imagen)", type=['pdf', 'png', 'jpg', 'jpeg'])

            sub_pago = st.form_submit_button("💳 Registrar Pago", type="primary")

            if sub_pago:
                if not referencia or monto_pago <= 0:
                    st.error("⚠️ Por favor complete el monto y el número de referencia.")
                else:
                    path_comp = None
                    if f_comprobante is not None:
                        ext = os.path.splitext(f_comprobante.name)[1]
                        fname = f"pago_{selected_inv}_{referencia}{ext}"
                        path_comp = os.path.join(UPLOAD_DIR, fname)
                        with open(path_comp, "wb") as f:
                            f.write(f_comprobante.getbuffer())

                    c = conn.cursor()
                    c.execute('''
                        INSERT INTO pagos_embarques (
                            num_invoice, tipo_pago, banco, monto, referencia, fecha_pago, path_comprobante
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (selected_inv, tipo_pago, banco, monto_pago, referencia, fecha_pago, path_comp))
                    conn.commit()

                    st.success(f"✅ Pago de **${monto_pago:,.2f} USD** registrado correctamente al embarque **{selected_inv}**.")

conn.close()
