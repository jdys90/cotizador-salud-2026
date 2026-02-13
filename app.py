import streamlit as st
import pandas as pd
import os
from io import BytesIO
from datetime import datetime, timedelta
import calendar
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN DE PÁGINA Y ESTILOS ---
st.set_page_config(page_title="Cotizador YQ Seguros", page_icon="🛡️", layout="wide")

# Estilos CSS personalizados
st.markdown("""
    <style>
    .stButton>button {
        background-color: #2456A6;
        color: white;
        border-radius: 8px;
    }
    .stButton>button:hover {
        background-color: #1a428a;
        color: white;
    }
    div[data-testid="stSidebarHeader"] {
        padding-bottom: 0px;
    }
    </style>
""", unsafe_allow_html=True)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as ImageRL
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
except ImportError:
    st.error("❌ Falta la librería 'reportlab'. Ejecuta REPARAR.bat")
    st.stop()

# --- DATOS DE ACCESO (ROLES) ---
CODIGO_ADMIN = "ADMIN2026"
CODIGOS_ASESORES = ["ASE01", "ASE02", "ASE03", "VENTAS2026"] 

# --- FUNCIÓN DE HORA PERÚ (NUEVA) ---
def obtener_hora_peru():
    """Obtiene la hora actual ajustada a Perú (UTC-5)."""
    return datetime.utcnow() - timedelta(hours=5)

# --- FUNCIONES GOOGLE SHEETS ---

def get_gspread_client():
    """Conecta con Google Sheets usando librerías modernas."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.warning("⚠️ Falta configuración de Google en Secrets.")
            return None
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"❌ Error de conexión Google: {e}")
        return None

def guardar_en_sheets(datos_fila):
    """Guarda la cotización en Google Sheets."""
    try:
        client = get_gspread_client()
        if not client: return

        sheet = client.open("historial_cotizador_salud").sheet1 
        sheet.append_row(datos_fila)
        
    except Exception as e:
        st.error(f"❌ Error al guardar en Sheets: {e}")

def descargar_historial_sheets():
    """Descarga todo el historial desde Google Sheets."""
    try:
        client = get_gspread_client()
        if not client: return None

        sheet = client.open("historial_cotizador_salud").sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error descargando historial: {e}")
        return None

# --- FUNCIONES DE CORREO ---

def enviar_notificacion(cliente, correo, celular, plan_interes_list, n_familia, edad, clinicas, continuidad):
    """Envía un correo a administración usando Zoho Mail."""
    SMTP_SERVER = "smtppro.zoho.com"
    SMTP_PORT = 587
    SENDER_EMAIL = "administracion@yqcorredores.com"
    
    if "EMAIL_PASSWORD" in st.secrets:
        SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    else:
        SENDER_PASSWORD = "TU_CONTRASEÑA_AQUI" 
        
    RECEIVER_EMAIL = "administracion@yqcorredores.com"

    clinicas_txt = ", ".join(clinicas) if clinicas else "Sin preferencia específica"
    if isinstance(plan_interes_list, list):
        cobertura_txt = ", ".join(plan_interes_list)
    else:
        cobertura_txt = str(plan_interes_list)

    # Usamos la hora de Perú para el correo
    fecha_hora_peru = obtener_hora_peru().strftime('%d/%m/%Y %H:%M')

    asunto = f"NUEVO LEAD DE COTIZADOR SALUD: {cliente}"
    cuerpo = f"""
    Hola Chicos,
    
    Un cliente ha generado una cotización de salud:
    
    ¡Llama ahora!
    
    DATOS DEL CLIENTE:
    ------------------------------------------------
    Nombre: {cliente}
    Correo: {correo}
    WhatsApp: {celular}
    ------------------------------------------------
    
    DATOS DE LA COTIZACIÓN:
    ------------------------------------------------
    Edad Titular: {edad} años
    Interés (Coberturas): {cobertura_txt}
    Condición: {continuidad}
    Clínicas Preferidas: {clinicas_txt}
    Total Asegurados (Familia): {n_familia + 1}
    ------------------------------------------------
    
    Fecha: {fecha_hora_peru} (Hora Perú)
    Este correo fue generado automáticamente por el Cotizador YQ.
    """

    try:
        if SENDER_PASSWORD == "TU_CONTRASEÑA_AQUI":
            return True

        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error enviando correo: {e}")
        return False

# --- SOPORTE ---

def normalizar_clinica(nombre):
    if pd.isna(nombre): return ""
    return str(nombre).strip().title()

def obtener_nuevo_folio():
    try:
        with open('folio.txt', 'r') as f: return int(f.read().strip()) + 1
    except: return 1000

def incrementar_folio():
    fol = obtener_nuevo_folio()
    try:
        with open('folio.txt', 'w') as f: f.write(str(fol))
    except: pass
    return fol

def get_mes_actual():
    # Usamos la hora de Perú para saber en qué mes estamos realmente
    mes_num = obtener_hora_peru().month
    meses = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
             7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
    return meses[mes_num]

# --- CARGA DE DATOS ---
@st.cache_data
def cargar_datos_base():
    if not os.path.exists('precios_2026.csv') or not os.path.exists('base_clinicas.xlsx'):
        return None

    try:
        try: df_precios = pd.read_csv('precios_2026.csv', sep=',')
        except: df_precios = pd.read_csv('precios_2026.csv', sep=';')

        df_precios = df_precios.loc[:, ~df_precios.columns.str.contains('^Unnamed')]
        df_precios['Aseguradora'] = df_precios['Aseguradora'].astype(str).str.strip()
        df_precios['Plan'] = df_precios['Plan'].astype(str).str.strip()

        if os.path.exists('info_adicional.csv'):
            try: df_int = pd.read_csv('info_adicional.csv')
            except: df_int = pd.read_csv('info_adicional.csv', sep=';')
            
            df_int['Aseguradora'] = df_int['Aseguradora'].astype(str).str.strip()
            df_int['Plan'] = df_int['Plan'].astype(str).str.strip()
            cols_drop = [c for c in df_int.columns if c in df_precios.columns and c not in ['Aseguradora','Plan']]
            df_precios = df_precios.drop(columns=cols_drop, errors='ignore')
            df_precios = pd.merge(df_precios, df_int, on=['Aseguradora','Plan'], how='left')
        
        cols_seguras = ['Cob_Int_Amb', 'Cob_Int_Hosp', 'Link_Carencia', 'Link_Cartilla', 'Int_Ded_Amb_Pre', 'Int_Reem_Amb_Sin', 'Int_Ded_Hosp_Pre', 'Int_Reem_Hosp_Sin', 'Tiene_Int']
        for col in cols_seguras:
            if col not in df_precios.columns: df_precios[col] = "-"
            df_precios[col] = df_precios[col].fillna("-")

        xls = pd.ExcelFile('base_clinicas.xlsx', engine='openpyxl')
        df_redes = pd.read_excel(xls, sheet_name='REDES')
        df_redes['Clinicas_Busqueda'] = df_redes['Clinicas_Incluidas'].fillna('').astype(str)
        df_redes['Aseguradora'] = df_redes['Aseguradora'].astype(str).str.strip()
        df_redes['Plan'] = df_redes['Plan'].astype(str).str.strip()
        
        todas = []
        for l in df_redes['Clinicas_Incluidas'].dropna():
            todas.extend([c.strip() for c in l.split(',')])
        clinicas_unicas = sorted(list(set(todas)))

        return df_precios, df_redes, clinicas_unicas, df_precios
    except Exception as e:
        st.error(f"Error cargando datos base: {e}")
        return None

def cargar_campanas():
    dict_campanas = {}
    if os.path.exists('campana_descuentos.csv'):
        try:
            try: df_camp = pd.read_csv('campana_descuentos.csv', sep=',')
            except: df_camp = pd.read_csv('campana_descuentos.csv', sep=';')
            for _, row in df_camp.iterrows():
                key = (str(row['Aseguradora']).strip(), str(row['Plan']).strip(), str(row['Tipo_Cliente']).strip(), str(row['Mes']).strip())
                try: dict_campanas[key] = int(row['Porcentaje_Descuento'])
                except: dict_campanas[key] = 0
        except: pass
    return dict_campanas

# --- BÚSQUEDA ---
def calcular_precio(df, cia, plan, familia):
    total = 0
    for p in familia:
        edad = min(p['edad'], 81)
        row = df[(df['Aseguradora']==cia) & (df['Plan']==plan) & (df['Edad']==edad)]
        if row.empty: return None
        col_p = 'Precio_Sano' if p['salud']=='Sano' else 'Precio_Cronico'
        try: precio = float(row.iloc[0][col_p])
        except: precio = 0.0
        if precio <= 0: return None
        total += precio
    return total

def buscar(df_precios, df_redes, familia, clinicas_user, continuidad, coberturas_list, descuentos):
    candidatos = []
    set_user = set(clinicas_user)
    
    PLANES_BASICA = ['Esencial', 'Esencial Plus', 'Multisalud Base', 'Medisalud Lite', 'Medisalud Base']
    PLANES_INTEGRAL = ['Red Preferente', 'Red Médica', 'Multisalud', 'Medisalud', 'Medisalud Plus', 'Viva Salud', 'Trébol Salud', 'Medisalud Senior +', 'Oro - Plan preferente', 'Oro - Plan Red', 'Oro - Plan Completo']
    PLANES_REEMBOLSO = ['Full Salud', 'Medicvida Nacional', 'Medisalud Premium']
    PLANES_INTERNACIONAL = ['Salud Preferencial', 'Medicvida Internacional']

    planes_permitidos = set()
    if "Básica" in coberturas_list: planes_permitidos.update(PLANES_BASICA)
    if "Integral" in coberturas_list: planes_permitidos.update(PLANES_INTEGRAL)
    if "Integral + Reembolso" in coberturas_list: planes_permitidos.update(PLANES_REEMBOLSO)
    if "Integral + Cobertura Internacional" in coberturas_list: planes_permitidos.update(PLANES_INTERNACIONAL)

    es_continuidad = (continuidad == "Vengo con continuidad")
    if es_continuidad:
        if 'Viva Salud' in planes_permitidos: planes_permitidos.remove('Viva Salud')
        if 'Trébol Salud' in planes_permitidos: planes_permitidos.remove('Trébol Salud')

    for (cia, plan), grupo in df_redes.groupby(['Aseguradora', 'Plan']):
        if es_continuidad and "mapfre" in str(cia).lower(): continue

        plan_check = str(plan).strip()
        if plan_check not in planes_permitidos: continue

        clinicas_plan = set()
        for _, row in grupo.iterrows():
            clinicas_plan.update([c.strip() for c in str(row['Clinicas_Busqueda']).split(',')])
        
        if clinicas_user and not set_user.issubset(clinicas_plan): continue

        list_clin_red = []
        list_cob_amb = []
        list_cob_hosp = []
        
        if not clinicas_user:
            row = grupo.iloc[0]
            list_clin_red.append(f"• <b>Red:</b> {row['Nombre_Red']}")
            list_cob_amb.append(f"• <b>Amb:</b> {row['Cobertura_Amb']}")
            list_cob_hosp.append(f"• <b>Hosp:</b> {row['Cobertura_Hosp']}")
        else:
            for cli in clinicas_user:
                for _, row in grupo.iterrows():
                    if cli in [c.strip() for c in str(row['Clinicas_Busqueda']).split(',')]:
                        list_clin_red.append(f"• <b>{cli}</b>: {row['Nombre_Red']}")
                        list_cob_amb.append(f"• <b>{cli}</b>: {row['Cobertura_Amb']}")
                        list_cob_hosp.append(f"• <b>{cli}</b>: {row['Cobertura_Hosp']}")
                        break
        
        match = df_precios[(df_precios['Aseguradora']==cia) & (df_precios['Plan']==plan)]
        if match.empty: continue
        data = match.iloc[0]
        
        base = calcular_precio(df_precios, cia, plan, familia)
        if base is None: continue
        
        dsc = descuentos.get((cia, plan), 0)
        final = base * (1 - dsc/100)
        ahorro = base - final

        amb_pre = str(data.get('Int_Ded_Amb_Pre', '-'))
        amb_sin = str(data.get('Int_Reem_Amb_Sin', '-'))
        hosp_pre = str(data.get('Int_Ded_Hosp_Pre', '-'))
        hosp_sin = str(data.get('Int_Reem_Hosp_Sin', '-'))
        txt_int_amb = f"<b>Ded:</b> {amb_pre}<br/><b>Reemb:</b> {amb_sin}"
        txt_int_hosp = f"<b>Ded:</b> {hosp_pre}<br/><b>Reemb:</b> {hosp_sin}"

        candidatos.append({
            'Aseguradora': cia, 'Plan': plan,
            'Txt_Clin_Red': "<br/>".join(list_clin_red),
            'Txt_Cob_Amb': "<br/>".join(list_cob_amb),
            'Txt_Cob_Hosp': "<br/>".join(list_cob_hosp),
            'Int_Amb_Full': txt_int_amb,
            'Int_Hosp_Full': txt_int_hosp,
            'Precio_Final': final,
            'Precio_Lista': base,
            'Ahorro_Soles': ahorro,
            'Pct_Dscto': dsc,
            'Precio_Mensual': final/12,
            'Link_Cartilla': data.get('Link_Cartilla', ''),
            'Link_Carencia': data.get('Link_Carencia', ''),
            'ID': f"{cia}-{plan}"
        })

    if not candidatos: return pd.DataFrame()
    return pd.DataFrame(candidatos).sort_values('Precio_Final')

# --- PDF ---
def generar_pdf(perfil, df, id_sel, razon, folio):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
        estilos = getSampleStyleSheet()
        
        AZUL = colors.HexColor("#2456A6"); DORADO_FONDO = colors.HexColor("#FFF2CC"); DORADO_BORDE = colors.HexColor("#D6B656")
        VERDE = colors.HexColor("#28A745"); ROJO = colors.HexColor("#D32F2F"); GRIS = colors.HexColor("#6E7A8A"); AZUL_CLARO = colors.HexColor("#E6F3FF")
        
        st_tit = ParagraphStyle('T', parent=estilos['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=AZUL, leading=16)
        st_sub = ParagraphStyle('S', parent=estilos['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=AZUL)
        st_norm = ParagraphStyle('N', parent=estilos['Normal'], fontSize=9, textColor=GRIS, leading=11)
        st_bold = ParagraphStyle('B', parent=st_norm, fontName='Helvetica-Bold', textColor=AZUL)
        st_analysis = ParagraphStyle('Analysis', parent=st_norm, leading=14, fontSize=9)
        st_th = ParagraphStyle('TH', parent=estilos['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
        st_td = ParagraphStyle('TD', parent=estilos['Normal'], fontSize=7.5, textColor=colors.black, leading=9)
        st_td_b = ParagraphStyle('TDB', parent=st_td, fontName='Helvetica-Bold', textColor=AZUL)

        elements = []
        img = ImageRL("logo.png", width=4.5*cm, height=1.6*cm, kind='proportional') if os.path.exists("logo.png") else Paragraph("", st_norm)
        txt_header = """<b>YQ CORREDORES DE SEGUROS</b><br/>Propuesta de seguro de salud"""
        p_header = Paragraph(txt_header, st_tit)
        
        # FECHA PDF (PERU)
        fecha_peru = obtener_hora_peru().strftime('%d/%m/%Y')
        txt_folio = f"<b>Folio:</b> {folio}<br/><b>Fecha:</b> {fecha_peru}"
        
        p_folio = Paragraph(txt_folio, ParagraphStyle('F', parent=st_norm, alignment=2))
        t_head = Table([[img, p_header, p_folio]], colWidths=[5*cm, 9*cm, 4*cm])
        t_head.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        elements.append(t_head)
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("En YQ Corredores de Seguros, entendemos la importancia de proteger tu salud. Te presentamos esta cotización personalizada con precios de campaña exclusivos.", st_norm))
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("TU PERFIL", st_sub))
        elements.append(Spacer(1, 5))
        data_perfil = [
            [Paragraph("<b>Titular:</b>", st_bold), Paragraph(perfil['Titular'], st_norm),
             Paragraph("<b>Cobertura:</b>", st_bold), Paragraph(perfil['Cobertura'], st_norm)],
            [Paragraph("<b>Dependientes:</b>", st_bold), Paragraph(perfil['Dependientes'], st_norm),
             Paragraph("<b>Condición:</b>", st_bold), Paragraph(perfil['Continuidad'], st_norm)]
        ]
        t_perf = Table(data_perfil, colWidths=[2.5*cm, 6.5*cm, 2.5*cm, 6.5*cm])
        t_perf.setStyle(TableStyle([('LINEBELOW', (0,0), (-1,-1), 0.5, colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('PADDING', (0,0), (-1,-1), 5)]))
        elements.append(t_perf)
        elements.append(Spacer(1, 20))

        es_int = "Internacional" in perfil['Cobertura']
        if es_int:
            headers = ['Plan', 'Clínicas / Redes', 'Int. Amb', 'Int. Hosp', 'Mensual', 'Anual']
            anchos = [3.0*cm, 4.2*cm, 3.7*cm, 3.5*cm, 1.4*cm, 2.2*cm]
        else:
            headers = ['Plan', 'Clínicas / Redes', 'Cob. Ambulatoria', 'Cob. Hospitalaria', 'Mensual', 'Anual']
            anchos = [3.0*cm, 4.2*cm, 4.2*cm, 3.0*cm, 1.4*cm, 2.2*cm]

        data = [[Paragraph(h, st_th) for h in headers]]
        
        for _, row in df.iterrows():
            rec = (row['ID'] == id_sel)
            txt_p = f"<b>{row['Aseguradora']}</b><br/>{row['Plan']}"
            if rec: txt_p = "⭐ RECOMENDADO ⭐<br/>" + txt_p
            
            links = []
            if row['Link_Cartilla'] and str(row['Link_Cartilla']).startswith('http'):
                links.append(f"<a href='{row['Link_Cartilla']}' color='blue'><u>Cartilla</u></a>")
            if perfil['Continuidad'] == "Nuevo" and row['Link_Carencia'] and str(row['Link_Carencia']).startswith('http'):
                links.append(f"<a href='{row['Link_Carencia']}' color='red'><u>Carencias</u></a>")
            
            if links: txt_p += "<br/>" + " | ".join(links)

            precio_anual = f"S/ {row['Precio_Final']:,.2f}"
            if row['Pct_Dscto'] > 0:
                precio_anual = f"<strike color='grey'>S/ {row['Precio_Lista']:,.0f}</strike><br/><b>{precio_anual}</b><br/><font color='red' size='7'>Ahorras S/ {row['Ahorro_Soles']:,.0f}</font>"
            precio_mensual = f"S/ {row['Precio_Mensual']:,.0f}"

            if es_int:
                fila = [Paragraph(txt_p, st_td), Paragraph(row['Txt_Clin_Red'], st_td), Paragraph(row['Int_Amb_Full'], st_td), Paragraph(row['Int_Hosp_Full'], st_td), Paragraph(precio_mensual, st_td_b), Paragraph(precio_anual, st_td_b)]
            else:
                fila = [Paragraph(txt_p, st_td), Paragraph(row['Txt_Clin_Red'], st_td), Paragraph(row['Txt_Cob_Amb'], st_td), Paragraph(row['Txt_Cob_Hosp'], st_td), Paragraph(precio_mensual, st_td_b), Paragraph(precio_anual, st_td_b)]
            data.append(fila)

        t = Table(data, colWidths=anchos, repeatRows=1)
        estilos_t = [('BACKGROUND', (0,0), (-1,0), AZUL), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 4)]
        for i, row in enumerate(df.iterrows()):
            if row[1]['ID'] == id_sel:
                estilos_t.append(('BACKGROUND', (0, i+1), (-1, i+1), DORADO_FONDO))
                estilos_t.append(('BOX', (0, i+1), (-1, i+1), 1.5, DORADO_BORDE))
        t.setStyle(TableStyle(estilos_t))
        elements.append(t)
        
        elements.append(Spacer(1, 10))
        if perfil['Continuidad'] == "Nuevo":
            aviso = "<b>IMPORTANTE:</b> Al ser un seguro nuevo, aplican periodos de carencia (30 días) y espera (para preexistencias). Por favor revise el enlace de carencias en la tabla superior."
            t_warn = Table([[Paragraph(aviso, ParagraphStyle('W', parent=st_norm, textColor=AZUL))]], colWidths=[18*cm])
            t_warn.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), AZUL_CLARO), ('BOX', (0,0), (-1,-1), 0.5, AZUL), ('PADDING', (0,0), (-1,-1), 8)]))
            elements.append(t_warn)
        elif perfil['Continuidad'] == "Vengo con continuidad":
            aviso_cont = "<b>BENEFICIO DE CONTINUIDAD:</b> Para gozar del beneficio de continuidad debe haber estado asegurado dentro de los últimos 90 días con una póliza de salud EPS o Individual."
            t_cont = Table([[Paragraph(aviso_cont, ParagraphStyle('W', parent=st_norm, textColor=VERDE))]], colWidths=[18*cm])
            t_cont.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#E8F5E9")), ('BOX', (0,0), (-1,-1), 0.5, VERDE), ('PADDING', (0,0), (-1,-1), 8)]))
            elements.append(t_cont)

        elements.append(Spacer(1, 20))
        if razon:
            elements.append(Paragraph(f"¿POR QUÉ RECOMENDAMOS EL PLAN {str(df[df['ID']==id_sel]['Plan'].values[0]).upper()}?", st_sub))
            elements.append(Spacer(1, 15)) 
            t_box = Table([[Paragraph(f"<b>ANÁLISIS DEL EXPERTO:</b><br/><br/>{razon}", st_analysis)]], colWidths=[18*cm])
            t_box.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), DORADO_FONDO), ('BOX', (0,0), (-1,-1), 1, DORADO_BORDE), ('PADDING', (0,0), (-1,-1), 12)]))
            elements.append(t_box)
            elements.append(Spacer(1, 25))

        elements.append(Paragraph("¿Listo para estar protegido?", st_sub))
        elements.append(Spacer(1, 5))
        st_btn = ParagraphStyle('Btn', parent=st_norm, textColor=colors.white, alignment=1, fontName='Helvetica-Bold', fontSize=10)
        t_btns = Table([[Paragraph('<a href="https://wa.link/czc7jg">¡QUIERO MI ASESORÍA GRATUITA!</a>', st_btn), "", Paragraph('<a href="https://wa.link/zwdc6r">¡QUIERO CONTRATAR AHORA!</a>', st_btn)]], colWidths=[7*cm, 1*cm, 7*cm], rowHeights=[1.2*cm])
        t_btns.setStyle(TableStyle([('BACKGROUND', (0,0), (0,0), AZUL), ('BACKGROUND', (2,0), (2,0), VERDE), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ROUNDED', (0,0), (-1,-1), 8)]))
        elements.append(t_btns)
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("Nota: Precios referenciales sujetos a evaluación médica. Incluyen IGV.", ParagraphStyle('D', parent=st_norm, fontSize=7)))

        doc.build(elements)
        buffer.seek(0)
        return buffer
    except Exception as e:
        return f"ERROR PDF: {str(e)}"

# --- INTERFAZ ---
base_data = cargar_datos_base()
if base_data is None:
    st.error("Ejecuta 'actualizar_db.py'")
else:
    df_precios, df_redes, clinicas_unicas, df_full = base_data
    campanas_activas = cargar_campanas() 
    
    if 'resultados' not in st.session_state: st.session_state['resultados'] = None
    
    with st.sidebar:
        if os.path.exists("logo.png"):
            st.sidebar.image("logo.png", use_container_width=True)
        
        st.header("Datos del Cliente")
        nom = st.text_input("Nombres completos")
        edad = st.number_input("Edad", 18, 99, 30)
        salud = st.radio("Estado de salud", ["Sano", "Crónico"], horizontal=True)
        
        st.header("Familia")
        n_dep = st.number_input("Número de dependientes", 0, 10, 0)
        familia = [{'edad': edad, 'salud': salud, 'rol': 'Titular'}]
        txt_fam = []
        if n_dep > 0:
            for i in range(n_dep):
                e = st.number_input(f"Edad Dep {i+1}", 0, 99, 10, key=f"edad_dep_{i}")
                s = st.radio(f"Salud Dep {i+1}", ["Sano", "Crónico"], horizontal=True, key=f"salud_dep_{i}")
                familia.append({'edad': e, 'salud': s, 'rol': 'Dependiente'})
                txt_fam.append(f"Dep ({e}a)")
        
        txt_dependientes = ", ".join(txt_fam) if txt_fam else "Ninguno"

        st.header("Filtros")
        cont = st.selectbox("Tipo de asegurado", ["Nuevo", "Vengo con continuidad"])
        cob = st.multiselect("Cobertura", ["Básica", "Integral", "Integral + Reembolso", "Integral + Cobertura Internacional"], default=["Integral"])
        clinicas = st.multiselect("Clínicas de preferencia", clinicas_unicas, placeholder="Puedes elegir más de una")
        
        st.header("Descuento")
        codigo_acceso = st.text_input("Código opcional de descuento", type="password")
        
        es_admin = (codigo_acceso == CODIGO_ADMIN)
        es_asesor = (codigo_acceso in CODIGOS_ASESORES)
        es_cliente = (not es_admin and not es_asesor)

        correo = ""
        celular = ""
        if es_cliente:
            st.info("Para generar tu cotización, por favor ingresa tus datos de contacto:")
            correo = st.text_input("Correo Electrónico")
            celular_num = st.number_input("Celular / WhatsApp (Solo números)", min_value=0, step=1, format="%d", value=0)
            celular = str(celular_num) if celular_num > 0 else ""
        
        mes_actual = get_mes_actual()
        tipo_cliente_key = "Nuevo" if cont == "Nuevo" else "Continuidad"
        
        descuentos = {}
        if es_admin:
            with st.expander(f"Campañas {mes_actual} (Modo Admin)"):
                for c in df_full['Aseguradora'].unique():
                    for p in df_full[df_full['Aseguradora']==c]['Plan'].unique():
                        key = (str(c).strip(), str(p).strip(), tipo_cliente_key, mes_actual)
                        val_default = campanas_activas.get(key, 0)
                        widget_key = f"dsct_{c}_{p}_{tipo_cliente_key}"
                        descuentos[(c,p)] = st.number_input(f"{c} - {p} %", 0, 50, val_default, key=widget_key)
            
            # --- PANEL DE ADMIN PARA HISTORIAL ---
            st.divider()
            st.write("### Base de Datos (Nube)")
            
            col_admin_1, col_admin_2 = st.columns(2)
            
            with col_admin_1:
                if st.button("🔄 Probar Conexión Sheets"):
                    client = get_gspread_client()
                    if client:
                        try:
                            sheet = client.open("historial_cotizador_salud")
                            st.success(f"✅ Conectado a: {sheet.title}")
                        except Exception as e:
                            st.error(f"❌ Falló al abrir hoja: {e}")
                    else:
                        st.error("❌ No hay cliente de Google.")

            with col_admin_2:
                if st.button("📥 Descargar Historial Completo"):
                    with st.spinner("Descargando..."):
                        df_historial = descargar_historial_sheets()
                        if df_historial is not None and not df_historial.empty:
                            csv = df_historial.to_csv(index=False).encode('utf-8-sig')
                            st.download_button(
                                label="💾 Guardar CSV",
                                data=csv,
                                file_name=f"historial_completo_{obtener_hora_peru().strftime('%d%m%Y')}.csv",
                                mime="text/csv"
                            )
                            st.success(f"Registros encontrados: {len(df_historial)}")
                        else:
                            st.warning("No se encontraron datos o hubo un error.")

        else:
            for c in df_full['Aseguradora'].unique():
                for p in df_full[df_full['Aseguradora']==c]['Plan'].unique():
                    key = (str(c).strip(), str(p).strip(), tipo_cliente_key, mes_actual)
                    descuentos[(c,p)] = campanas_activas.get(key, 0)

        es_solo_internacional = (len(cob) == 1 and "Integral + Cobertura Internacional" in cob)
        requiere_clinica = not es_solo_internacional and es_cliente

        if st.button("Cotizar"):
            # Validaciones
            if not cob:
                st.error("⚠️ Por favor selecciona al menos un tipo de Cobertura.")
            elif requiere_clinica and not clinicas:
                st.error("⚠️ Por favor selecciona al menos una Clínica de preferencia.")
            elif es_cliente:
                if not correo:
                    st.error("⚠️ Por favor ingresa tu Correo Electrónico.")
                elif not celular or len(celular) != 9 or not celular.startswith("9") or not celular.isdigit():
                    st.error("⚠️ El número de celular debe tener 9 dígitos numéricos y comenzar con 9.")
                else:
                    rol_actual = "Cliente"
                    # Guardar con hora PERÚ
                    guardar_en_sheets([
                        obtener_hora_peru().strftime('%Y-%m-%d %H:%M'),
                        nom, correo, celular, edad, str(cob), cont, str(clinicas), len(familia)-1, rol_actual
                    ])
                    enviar_notificacion(nom, correo, celular, cob, len(familia)-1, edad, clinicas, cont)
                    
                    st.session_state['resultados'] = buscar(df_full, df_redes, familia, clinicas, cont, cob, descuentos)
                    cob_str = ", ".join(cob) if isinstance(cob, list) else str(cob)
                    st.session_state['perfil'] = {'Titular': f"{nom} ({edad} años)", 'Dependientes': txt_dependientes, 'Continuidad': cont, 'Cobertura': cob_str}
                    st.session_state['nombre_cliente'] = nom
                    st.session_state['clinicas_sel'] = clinicas
            else:
                # Todo OK para Admin/Asesor
                rol_actual = "Admin" if es_admin else "Asesor"
                # Guardar con hora PERÚ
                guardar_en_sheets([
                    obtener_hora_peru().strftime('%Y-%m-%d %H:%M'),
                    nom, correo, celular, edad, str(cob), cont, str(clinicas), len(familia)-1, rol_actual
                ])
                
                st.session_state['resultados'] = buscar(df_full, df_redes, familia, clinicas, cont, cob, descuentos)
                cob_str = ", ".join(cob) if isinstance(cob, list) else str(cob)
                st.session_state['perfil'] = {'Titular': f"{nom} ({edad} años)", 'Dependientes': txt_dependientes, 'Continuidad': cont, 'Cobertura': cob_str}
                st.session_state['nombre_cliente'] = nom
                st.session_state['clinicas_sel'] = clinicas

    if st.session_state['resultados'] is not None:
        res = st.session_state['resultados']
        if res.empty:
            st.error(f"⚠️ No se encontraron planes. Intenta cambiar los filtros.")
        else:
            st.success(f"¡Hemos encontrado {len(res)} opciones compatibles!")
            
            if not es_cliente:
                cols = ['Aseguradora','Plan']
                if "Integral + Cobertura Internacional" in cob:
                    cols += ['Int_Amb_Full', 'Int_Hosp_Full']
                
                mostrar_locales = any(c != "Integral + Cobertura Internacional" for c in cob)
                if mostrar_locales:
                    cols += ['Txt_Cob_Amb', 'Txt_Cob_Hosp']

                df_view = res.copy()
                for c in df_view.columns:
                    if df_view[c].dtype == object:
                        df_view[c] = df_view[c].str.replace('<b>','').str.replace('</b>','').str.replace('<br/>','\n').str.replace('• ','')
                
                cols_final = [c for c in cols if c in df_view.columns]
                st.subheader("Tabla Comparativa (Vista Asesor/Admin)")
                st.dataframe(df_view[cols_final + ['Precio_Lista', 'Pct_Dscto', 'Precio_Final']], hide_index=True)
            else:
                st.info("👇 Descarga el PDF para ver el comparativo detallado.")

            if cont == "Vengo con continuidad":
                st.info("ℹ️ Para gozar del beneficio de continuidad debe haber estado asegurado dentro de los últimos 90 días.")

            st.divider()
            
            op = {f"{r['Aseguradora']} {r['Plan']}": r['ID'] for _,r in res.iterrows()}
            op_keys = list(op.keys())
            
            clin_txt = ", ".join(st.session_state.get('clinicas_sel', []))
            if not clin_txt: clin_txt = "su red de afiliados"
            
            txt_motivo = f"Este plan es el que tiene mejor precio considerando las clínicas que prefiere ({clin_txt}) y sus beneficios."
            if cont == "Nuevo": txt_motivo += " Recuerde revisar los periodos de carencia."

            if es_cliente:
                sel = op_keys[0] 
                razon = txt_motivo 
            else:
                sel = st.radio("Recomendar", op_keys) 
                razon = st.text_area("Motivo (Análisis del Experto):", value=txt_motivo)
            
            if st.button("Generar PDF"):
                pdf_res = generar_pdf(st.session_state['perfil'], res, op[sel], razon, incrementar_folio())
                if isinstance(pdf_res, str): st.error(pdf_res)
                else:
                    nom_clean = st.session_state.get('nombre_cliente', 'Cliente').strip().split()[0]
                    cls_list = [c.strip().split()[0] for c in st.session_state.get('clinicas_sel', [])]
                    cls_clean = "_".join(cls_list)
                    # Hora Perú para nombre de archivo
                    fecha_str = obtener_hora_peru().strftime("%d%m%y_%H%M")
                    file_name = f"COTISALUD_{nom_clean}_{cls_clean}_{fecha_str}.pdf"
                    st.download_button("Descargar PDF", pdf_res, file_name, "application/pdf")




