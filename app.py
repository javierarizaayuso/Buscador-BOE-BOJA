import datetime
import logging

import requests
import streamlit as st
from lxml import etree

import boletines
import filtros

VERSION = "v20261123"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(page_title=f"Radar Maestro BOE/BOJA - {VERSION}", layout="wide")

# Errores de red / de datos que se muestran al usuario en lugar de ocultarlos
ERRORES_DESCARGA = (requests.RequestException, etree.LxmlError, ValueError)


# --- DESCARGAS CON CACHÉ ---
# Las excepciones no se guardan en caché, así que un fallo puntual se reintenta
# en la siguiente ejecución. El BOE/BOJA de hoy puede cambiar durante el día,
# de ahí el TTL corto.

@st.cache_data(ttl=900, show_spinner=False)
def boe_cacheado(fecha):
    return boletines.descargar_sumario_boe(fecha)


@st.cache_data(ttl=900, show_spinner=False)
def boletines_boja_cacheado(fecha):
    return boletines.localizar_boletines_boja(fecha)


@st.cache_data(ttl=3600, max_entries=30, show_spinner=False)
def anuncios_boletin_boja_cacheado(b_url):
    return boletines.obtener_anuncios_boletin_boja(b_url)


# --- INTERFAZ ---

st.title("📑 Radar Maestro BOE/BOJA by JAA")

with st.form("radar_form"):
    fecha = st.date_input("Fecha de consulta", datetime.date.today())
    st.markdown("### ⚙️ Reglas de Vigilancia")

    default_rules = [
        {"act": True, "bol": "BOE", "sec": "", "dep": "", "words": "ayuda OR subvencion OR incentivos"},
        {"act": True, "bol": "BOE", "sec": "", "dep": "jefatura competencia", "words": ""},
        {"act": True, "bol": "BOE", "sec": "", "dep": "ecologica", "words": "NOT riego AND NOT subterranea AND NOT vertido AND NOT extincion AND NOT sancionador"},
        {"act": True, "bol": "BOE", "sec": "", "dep": "movilidad", "words": "DGT OR comunicaciones OR ADIF AND NOT formalización"},
        {"act": False, "bol": "BOE", "sec": "", "dep": "", "words": ""},
        {"act": True, "bol": "BOJA", "sec": "", "dep": "agricultura hacienda empleo industria sostenibilidad", "words": "ayuda OR subvencion OR incentivos"},
        {"act": True, "bol": "BOJA", "sec": "generales", "dep": "presidencia", "words": ""},
        {"act": True, "bol": "BOJA", "sec": "otras anuncios generales", "dep": "hacienda agua sostenibilidad energía fomento", "words": "NOT riego AND NOT subterranea AND NOT vertido AND NOT extincion AND NOT sancionador AND NOT comparecencia"},
        {"act": True, "bol": "BOJA", "sec": "", "dep": "Ayuntamientos", "words": "Córdoba OR Málaga"},
        {"act": False, "bol": "BOJA", "sec": "", "dep": "", "words": ""},
    ]

    rules_input = []
    c_h = st.columns([0.4, 0.7, 1.2, 1.3, 3.4])
    c_h[0].write("**Act.**")
    c_h[1].write("**Bol.**")
    c_h[2].write("**Sección (OR)**")
    c_h[3].write("**Organismo (OR)**")
    c_h[4].write("**Filtro Título (Bool)**")

    for i, r in enumerate(default_rules):
        c = st.columns([0.4, 0.7, 1.2, 1.3, 3.4])
        with c[0]:
            act = st.checkbox(f"Regla {i + 1} activa", value=r["act"], key=f"a{i}", label_visibility="collapsed")
        with c[1]:
            bol = st.selectbox(f"Regla {i + 1} boletín", ["BOE", "BOJA"], index=0 if r["bol"] == "BOE" else 1,
                               key=f"bol{i}", label_visibility="collapsed")
        with c[2]:
            sec = st.text_input(f"Regla {i + 1} sección", value=r["sec"], key=f"s{i}", label_visibility="collapsed")
        with c[3]:
            dep = st.text_input(f"Regla {i + 1} organismo", value=r["dep"], key=f"d{i}", label_visibility="collapsed")
        with c[4]:
            words = st.text_input(f"Regla {i + 1} filtro de título", value=r["words"], key=f"w{i}", label_visibility="collapsed")
        rules_input.append({"num": i + 1, "active": act, "boletin": bol, "seccion": sec, "depto": dep, "palabras": words})

    submit = st.form_submit_button("🚀 EJECUTAR VIGILANCIA")

if submit:
    active_rules = [r for r in rules_input if r["active"]]

    # Validar los filtros ANTES de descargar nada: una expresión mal escrita
    # se avisa en lugar de dejar la regla sin resultados en silencio.
    errores_reglas = []
    for r in active_rules:
        try:
            filtros.compilar_expresion(r["palabras"])
        except filtros.ExpresionBooleanaError as e:
            errores_reglas.append(f"Regla {r['num']}: filtro de título no válido ({e}).")
    if errores_reglas:
        for msg in errores_reglas:
            st.error(msg)
        st.stop()

    data_pool = []
    with st.spinner("Analizando boletines..."):
        # Descarga BOE
        if any(r["boletin"] == "BOE" for r in active_rules):
            try:
                res_boe = boe_cacheado(fecha)
                if res_boe is None:
                    st.info("ℹ️ El BOE no ha publicado sumario para esa fecha (domingo, festivo o fecha futura).")
                else:
                    data_pool.extend(res_boe)
                    st.write(f"✅ BOE: {len(res_boe)} anuncios leídos.")
            except ERRORES_DESCARGA as e:
                logger.exception("Error descargando el BOE")
                st.warning(f"⚠️ No se pudo leer el BOE: {e}")

        # Descarga BOJA
        if any(r["boletin"] == "BOJA" for r in active_rules):
            try:
                urls_boja = boletines_boja_cacheado(fecha)
            except ERRORES_DESCARGA as e:
                logger.exception("Error localizando los boletines del BOJA")
                st.warning(f"⚠️ No se pudieron localizar los boletines del BOJA: {e}")
                urls_boja = []

            if not urls_boja:
                st.info("ℹ️ No se han encontrado boletines del BOJA para esa fecha.")

            total_boja_ads = []
            for b_url in urls_boja:
                st.write(f"📥 Accediendo a BOJA: `{b_url}`")
                try:
                    ads = anuncios_boletin_boja_cacheado(b_url)
                except ERRORES_DESCARGA as e:
                    logger.exception("Error en el boletín %s", b_url)
                    st.warning(f"⚠️ No se pudo leer {b_url}: {e}")
                    continue
                except Exception as e:  # el PDF puede fallar de formas muy variadas (pdfminer)
                    logger.exception("Error interpretando el PDF de %s", b_url)
                    st.warning(f"⚠️ No se pudo interpretar el PDF de {b_url}: {e}")
                    continue
                if ads:
                    st.write(f"   👍 {len(ads)} anuncios extraídos.")
                else:
                    st.warning(f"⚠️ Se leyó el sumario de {b_url} pero no se extrajo ningún anuncio. "
                               "Puede que el BOJA haya cambiado el formato del PDF.")
                total_boja_ads.extend(ads)
            if urls_boja:
                data_pool.extend(total_boja_ads)
                st.write(f"✅ BOJA: {len(total_boja_ads)} anuncios leídos en total.")

    if data_pool:
        encontrados = []
        for anuncio in data_pool:
            for rule in active_rules:
                if rule["boletin"] not in anuncio["fuente"]:
                    continue
                # Filtros por capas
                if not filtros.match_multiples_palabras_or(anuncio["seccion"], rule["seccion"]):
                    continue
                if not filtros.match_multiples_palabras_or(anuncio["organismo"], rule["depto"]):
                    continue
                if not filtros.evaluate_boolean(anuncio["titulo"], rule["palabras"]):
                    continue
                item = anuncio.copy()
                item["filtro_aplicado"] = rule["palabras"]
                encontrados.append(item)
                break

        if encontrados:
            encontrados.sort(key=lambda x: (0 if "BOE" in x["fuente"] else 1, filtros.normalizar(x["organismo"])))
            st.success(f"🔥 Detectados {len(encontrados)} anuncios de interés.")
            last_bol_group, last_org = None, None
            for e in encontrados:
                curr_bol_group = "BOE" if "BOE" in e["fuente"] else "BOJA"
                if curr_bol_group != last_bol_group:
                    st.header(f"🏛 {curr_bol_group}")
                    last_bol_group, last_org = curr_bol_group, None
                if e["organismo"] != last_org:
                    st.markdown(f"### <u>**{e['organismo']}**</u>", unsafe_allow_html=True)
                    last_org = e["organismo"]
                t_final = filtros.resaltar_palabras(e["titulo"], e["filtro_aplicado"])
                with st.expander(t_final):
                    st.write(f"**📂 Sección:** {e['seccion']} | **📍 Fuente:** {e['fuente']}")
                    st.markdown(f"[📄 Ver PDF]({e['url']})" + (f" | [🔗 Ver HTML]({e['url_html']})" if e['url_html'] else ""))
        else:
            st.warning("No hay coincidencias con los filtros aplicados.")
    else:
        st.error("No se han podido recuperar datos. Verifica la fecha seleccionada.")

# Creado por Javier Ariza Ayuso con Google AI Studio
