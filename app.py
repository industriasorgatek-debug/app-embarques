import streamlit as st
import pandas as pd
from datetime import datetime, date
import io

# Importaciones para la generación del PDF con ReportLab
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE LA PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Gestión de Embarques e Inventario",
    page_layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# CONTROL DE ACCESO (PINS)
# -----------------------------------------------------------------------------
ROLES = {
    "Ventas": "1111",
    "Compras": "1212",
    "Administrador": "9999"
}

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "rol_actual" not in st.session_state:
    st.session_state.rol_actual = None

def login():
    st.sidebar.title("🔐 Acceso al Sistema")
    rol = st.sidebar.selectbox("Seleccione su Rol", list(ROLES.keys()))
    pin_input = st.sidebar.text_input("Ingrese PIN de acceso", type="password")
    
    if st.sidebar.button("Ingresar"):
        if pin_input == ROLES[rol]:
            st.session_state.autenticado = True
            st.session_state.rol_actual = rol
            st.rerun()
        else:
            st.sidebar.error("PIN incorrecto. Intente nuevamente.")

def logout():
    st.session_state.autenticado = False
    st.session_state.rol_actual = None
    st.rerun()

if not st.session_state.autenticado:
    login()
    st.title("Bienvenido al Sistema de Gestión")
    st.info("Por favor, ingrese sus credenciales en la barra lateral para continuar.")
    st.stop()

# Mostrar barra superior con el usuario actual
st.sidebar.success(f"Sesión activa: **{st.session_state.rol_actual}**")
if st.sidebar.button("Cerrar Sesión"):
    logout()

# -----------------------------------------------------------------------------
# BASE DE DATOS EN MEMORIA (SESSION STATE)
# -----------------------------------------------------------------------------
if "db_embarques" not in st.session_state:
    st.session_state.db_embarques = pd.DataFrame(columns=[
        "ID_Embarque", "Fecha_Llegada", "Proveedor", "Producto", "Cantidad_Cajas",
        "Kilos_Totales", "Transportista", "Costo_Flete", "Flete_Pagado", "Estatus_Inspeccion", "Notas"
    ])

# -----------------------------------------------------------------------------
# FUNCIÓN PARA GENERAR PDF DE EMBARQUE
# -----------------------------------------------------------------------------
def generar_pdf_embarque(datos):
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
    
    # Estilos personalizados
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor("#1E3A8A"),
        alignment=1, # Centrado
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor("#4B5563"),
        alignment=1,
        spaceAfter=20
    )

    cell_bold = ParagraphStyle('CellBold', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold')
    cell_normal = ParagraphStyle('CellNormal', parent=styles['Normal'], fontSize=10)

    # Encabezado
    story.append(Paragraph("FICHA TÉCNICA DE RECEPCIÓN DE EMBARQUE", title_style))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 10))

    # Formatear el pago del flete
    pago_flete_str = "SÍ (PAGADO)" if datos.get('Flete_Pagado') == "Sí" or datos.get('Flete_Pagado') is True else "NO (PENDIENTE)"
    pago_flete_color = colors.HexColor("#065F46") if "SÍ" in pago_flete_str else colors.HexColor("#991B1B")

    # Contenido organizado en Tabla
    data_table = [
        [Paragraph("Código de Embarque:", cell_bold), Paragraph(str(datos.get('ID_Embarque', '-')), cell_normal)],
        [Paragraph("Fecha de Llegada:", cell_bold), Paragraph(str(datos.get('Fecha_Llegada', '-')), cell_normal)],
        [Paragraph("Proveedor:", cell_bold), Paragraph(str(datos.get('Proveedor', '-')), cell_normal)],
        [Paragraph("Producto:", cell_bold), Paragraph(str(datos.get('Producto', '-')), cell_normal)],
        [Paragraph("Cantidad de Cajas:", cell_bold), Paragraph(f"{datos.get('Cantidad_Cajas', 0):,} cs", cell_normal)],
        [Paragraph("Kilos Totales:", cell_bold), Paragraph(f"{datos.get('Kilos_Totales', 0.0):,.2f} Kg", cell_normal)],
        [Paragraph("Empresa Transportista:", cell_bold), Paragraph(str(datos.get('Transportista', '-')), cell_normal)],
        [Paragraph("Costo del Flete:", cell_bold), Paragraph(f"${datos.get('Costo_Flete', 0.0):,.2f}", cell_normal)],
        [Paragraph("Estado de Pago del Flete:", cell_bold), Paragraph(f"<b>{pago_flete_str}</b>", cell_normal)],
        [Paragraph("Estatus de Inspección:", cell_bold), Paragraph(str(datos.get('Estatus_Inspeccion', '-')), cell_normal)],
        [Paragraph("Notas / Observaciones:", cell_bold), Paragraph(str(datos.get('Notas', '-')), cell_normal)]
    ]

    t = Table(data_table, colWidths=[180, 360])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F9FAFB")),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#D1D5DB")),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    
    story.append(t)
    story.append(Spacer(1, 30))

    # Firmas
    firma_data = [
        [Paragraph("___________________________", cell_bold), Paragraph("___________________________", cell_bold)],
        [Paragraph("Firma Recibido (Almacén)", cell_normal), Paragraph("Firma Conforme (Transporte)", cell_normal)]
    ]
    tabla_firmas = Table(firma_data, colWidths=[270, 270])
    tabla_firmas.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    
    story.append(tabla_firmas)

    doc.build(story)
    buffer.seek(0)
    return buffer

# -----------------------------------------------------------------------------
# NAVEGACIÓN Y PÁGINAS DEL SISTEMA
# -----------------------------------------------------------------------------
menu = st.sidebar.radio(
    "Navegación",
    ["📋 Control de Embarques", "📦 Inventario Consolidado"]
)

# -----------------------------------------------------------------------------
# MÓDULO 1: CONTROL DE EMBARQUES
# -----------------------------------------------------------------------------
if menu == "📋 Control de Embarques":
    st.title("📋 Recepción y Control de Embarques")
    st.write("Registre y gestione la entrada de mercancía, fletes e inspección de calidad.")

    # SOLO COMPRAS Y ADMIN PUEDEN REGISTRAR/EDITAR
    if st.session_state.rol_actual in ["Compras", "Administrador"]:
        
        with st.expander("➕ Registrar Nuevo Embarque", expanded=False):
            with st.form("form_nuevo_embarque", clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    id_emb = f"INV-{len(st.session_state.db_embarques) + 101}"
                    st.text_input("ID Embarque (Autogenerado)", value=id_emb, disabled=True)
                    fecha = st.date_input("Fecha de Llegada", value=date.today())
                    proveedor = st.text_input("Proveedor", placeholder="Ej: Agro Export S.A.")
                    
                with col2:
                    producto = st.text_input("Producto", placeholder="Ej: Manzana Red Delicious")
                    cajas = st.number_input("Cantidad de Cajas", min_value=1, value=100)
                    kilos = st.number_input("Kilos Totales", min_value=0.1, value=1800.0, step=0.5)
                    
                with col3:
                    transportista = st.text_input("Empresa Transportista", placeholder="Ej: Logística del Norte")
                    costo_flete = st.number_input("Costo del Flete ($)", min_value=0.0, value=250.0, step=10.0)
                    flete_pagado = st.selectbox("¿Flete Pagado?", ["No", "Sí"])
                    estatus_insp = st.selectbox("Estatus de Inspección", ["Pendiente", "Aprobado", "Rechazado", "Aprobado con Observación"])
                
                notas = st.text_area("Notas / Observaciones de Calidad", placeholder="Comentarios adicionales...")
                
                btn_guardar = st.form_submit_button("💾 Guardar Embarque")
                
                if btn_guardar:
                    if not proveedor or not producto or not transportista:
                        st.error("Por favor complete los campos obligatorios: Proveedor, Producto y Transportista.")
                    else:
                        nuevo_reg = {
                            "ID_Embarque": id_emb,
                            "Fecha_Llegada": fecha.strftime("%Y-%m-%d"),
                            "Proveedor": proveedor,
                            "Producto": producto,
                            "Cantidad_Cajas": cajas,
                            "Kilos_Totales": kilos,
                            "Transportista": transportista,
                            "Costo_Flete": costo_flete,
                            "Flete_Pagado": flete_pagado,
                            "Estatus_Inspeccion": estatus_insp,
                            "Notas": notas
                        }
                        st.session_state.db_embarques = pd.concat([
                            st.session_state.db_embarques,
                            pd.DataFrame([nuevo_reg])
                        ], ignore_index=True)
                        st.success(f"Embarque {id_emb} registrado exitosamente.")
                        st.rerun()

    else:
        st.info("ℹ️ Su rol actual tiene permiso de **solo lectura** para este módulo.")

    st.markdown("---")
    st.subheader("Registros Existentes")

    if st.session_state.db_embarques.empty:
        st.warning("No hay embarques registrados hasta el momento.")
    else:
        # Selección de fila para exportar o editar
        df_mostrar = st.session_state.db_embarques.copy()
        
        event = st.dataframe(
            df_mostrar,
            use_container_width=True,
            selection_mode="single-row",
            on_select="rerun",
            hide_index=True
        )

        filas_seleccionadas = event.selection.rows if event else []

        if filas_seleccionadas:
            idx = filas_seleccionadas[0]
            registro_sel = df_mostrar.iloc[idx].to_dict()

            st.success(f"Seleccionado: **{registro_sel['ID_Embarque']}** - {registro_sel['Producto']}")

            col_pdf, col_edit = st.columns([1, 1])

            # Botón de Descarga de PDF
            with col_pdf:
                pdf_bytes = generar_pdf_embarque(registro_sel)
                st.download_button(
                    label=f"📄 Imprimir Ficha PDF ({registro_sel['ID_Embarque']})",
                    data=pdf_bytes,
                    file_name=f"Ficha_Embarque_{registro_sel['ID_Embarque']}.pdf",
                    mime="application/pdf"
                )

            # Opción de edición solo para Compras y Admin
            with col_edit:
                if st.session_state.rol_actual in ["Compras", "Administrador"]:
                    with st.expander("✏️ Editar Embarque Seleccionado"):
                        with st.form("form_edit_embarque"):
                            e_prov = st.text_input("Proveedor", value=registro_sel['Proveedor'])
                            e_prod = st.text_input("Producto", value=registro_sel['Producto'])
                            e_cajas = st.number_input("Cajas", value=int(registro_sel['Cantidad_Cajas']))
                            e_kilos = st.number_input("Kilos", value=float(registro_sel['Kilos_Totales']))
                            e_trans = st.text_input("Transportista", value=registro_sel['Transportista'])
                            e_flete = st.number_input("Costo Flete ($)", value=float(registro_sel['Costo_Flete']))
                            
                            # Selección del pago de flete
                            idx_pago = 1 if registro_sel['Flete_Pagado'] == "Sí" else 0
                            e_pagado = st.selectbox("¿Flete Pagado?", ["No", "Sí"], index=idx_pago)
                            
                            e_estatus = st.selectbox("Inspección", ["Pendiente", "Aprobado", "Rechazado", "Aprobado con Observación"], index=["Pendiente", "Aprobado", "Rechazado", "Aprobado con Observación"].index(registro_sel['Estatus_Inspeccion']))
                            e_notas = st.text_area("Notas", value=registro_sel['Notas'])

                            if st.form_submit_button("Actualizar Registro"):
                                st.session_state.db_embarques.loc[idx, 'Proveedor'] = e_prov
                                st.session_state.db_embarques.loc[idx, 'Producto'] = e_prod
                                st.session_state.db_embarques.loc[idx, 'Cantidad_Cajas'] = e_cajas
                                st.session_state.db_embarques.loc[idx, 'Kilos_Totales'] = e_kilos
                                st.session_state.db_embarques.loc[idx, 'Transportista'] = e_trans
                                st.session_state.db_embarques.loc[idx, 'Costo_Flete'] = e_flete
                                st.session_state.db_embarques.loc[idx, 'Flete_Pagado'] = e_pagado
                                st.session_state.db_embarques.loc[idx, 'Estatus_Inspeccion'] = e_estatus
                                st.session_state.db_embarques.loc[idx, 'Notas'] = e_notas
                                st.success("Registro actualizado correctamente.")
                                st.rerun()

# -----------------------------------------------------------------------------
# MÓDULO 2: INVENTARIO CONSOLIDADO
# -----------------------------------------------------------------------------
elif menu == "📦 Inventario Consolidado":
    st.title("📦 Inventario Consolidado")
    st.write("Vista de disponibilidad agregada por producto basada en embarques aprobados.")

    df = st.session_state.db_embarques

    if df.empty:
        st.info("No hay datos para consolidar. Ingrese embarques en el módulo correspondiente.")
    else:
        # Filtrar solo aprobados o aprobados con observación
        df_aprobados = df[df['Estatus_Inspeccion'].isin(["Aprobado", "Aprobado con Observación"])]

        if df_aprobados.empty:
            st.warning("Existen embarques registrados, pero ninguno ha sido **Aprobado** por inspección.")
        else:
            consolidado = df_aprobados.groupby("Producto").agg(
                Embarques_Recibidos=("ID_Embarque", "count"),
                Total_Cajas=("Cantidad_Cajas", "sum"),
                Total_Kilos=("Kilos_Totales", "sum")
            ).reset_index()

            st.dataframe(consolidado, use_container_width=True, hide_index=True)

            # Métricas rápidas
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Variedades Disponibles", len(consolidado))
            col_m2.metric("Cajas Totales en Stock", f"{consolidado['Total_Cajas'].sum():,} cs")
            col_m3.metric("Kilos Totales en Stock", f"{consolidado['Total_Kilos'].sum():,.2f} Kg")
