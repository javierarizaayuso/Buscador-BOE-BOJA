import datetime
import hashlib
import logging
from pathlib import Path

import requests
import streamlit as st
from lxml import etree

import boletines
import filtros
import reglas

VERSION = "v20261123"
RUTA_REGLAS = Path(__file__).with_name("reglas.json")

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


# --- ESTADO DE LAS REGLAS ---
# Cada fila del formulario guarda su valor en st.session_state (claves a0, bol0, s0, d0, w0...).
# Al arrancar se rellenan desde reglas.json; el usuario puede cargar o descargar otro archivo.

def aplicar_reglas_al_formulario(lista):
    for i, r in enumerate(lista):
        st.session_state[f"a{i}"] = r["activa"]
        st.session_state[f"bol{i}"] = r["boletin"]
        st.session_state[f"s{i}"] = r["seccion"]
        st.session_state[f"d{i}"] = r["organismo"]
        st.session_state[f"w{i}"] = r["titulo"]


def reglas_del_formulario():
    return [{
        "activa": st.session_state[f"a{i}"],
        "boletin": st.session_state[f"bol{i}"],
        "seccion": st.session_state[f"s{i}"],
        "organismo": st.session_state[f"d{i}"],
        "titulo": st.session_state[f"w{i}"],
    } for i in range(reglas.MAX_REGLAS)]


# --- INTERFAZ ---

st.title("📑 Radar Maestro BOE/BOJA by JAA")

if "reglas_iniciadas" not in st.session_state:
    lista_inicial, aviso_inicial = reglas.cargar_reglas_archivo(RUTA_REGLAS)
    aplicar_reglas_al_formulario(lista_inicial)
    st.session_state["aviso_reglas"] = aviso_inicial
    st.session_state["reglas_iniciadas"] = True

if st.session_state.get("aviso_reglas"):
    st.warning(f"⚠️ {st.session_state['aviso_reglas']}")

fecha = st.date_input("Fecha de consulta", datetime.date.today())

with st.expander("💾 Guardar, cargar o restaurar reglas"):
    st.caption("Las reglas se guardan en un archivo `reglas.json` que puedes llevar a cualquier dispositivo. "
               "Para que sean las de arranque en todos, sube ese archivo al repositorio sustituyendo el existente.")
    st.download_button("⬇️ Descargar reglas actuales",
                       data=reglas.reglas_a_json(reglas_del_formulario()),
                       file_name="reglas.json", mime="application/json")

    subida = st.file_uploader("⬆️ Cargar reglas desde un archivo .json", type="json", key="subida_reglas")
    if subida is not None:
        contenido = subida.getvalue()
        firma = hashlib.md5(contenido).hexdigest()
        if st.session_state.get("firma_reglas") != firma:  # aplicar una sola vez cada archivo
            try:
                aplicar_reglas_al_formulario(reglas.reglas_desde_json(contenido.decode("utf-8-sig")))
                st.session_state["firma_reglas"] = firma
                st.success(f"✅ Reglas cargadas desde {subida.name}.")
            except (reglas.ReglasError, UnicodeDecodeError) as e:
                st.error(f"No se pudo cargar {subida.name}: {e}")
    else:
        st.session_state.pop("firma_reglas", None)

    if st.button("↩️ Restaurar las reglas de reglas.json"):
        lista_restaurada, aviso_restaurar = reglas.cargar_reglas_archivo(RUTA_REGLAS)
        aplicar_reglas_al_formulario(lista_restaurada)
        st.session_state["aviso_reglas"] = aviso_restaurar
        st.rerun()

st.markdown("### ⚙️ Reglas de Vigilancia")

rules_input = []
c_h = st.columns([0.4, 0.7, 1.2, 1.3, 3.4])
c_h[0].write("**Act.**")
c_h[1].write("**Bol.**")
c_h[2].write("**Sección (OR)**")
c_h[3].write("**Organismo (OR)**")
c_h[4].write("**Filtro Título (Bool)**")

for i in range(reglas.MAX_REGLAS):
    c = st.columns([0.4, 0.7, 1.2, 1.3, 3.4])
    with c[0]:
        act = st.checkbox(f"Regla {i + 1} activa", key=f"a{i}", label_visibility="collapsed")
    with c[1]:
        bol = st.selectbox(f"Regla {i + 1} boletín", list(reglas.BOLETINES), key=f"bol{i}", label_visibility="collapsed")
    with c[2]:
        sec = st.text_input(f"Regla {i + 1} sección", key=f"s{i}", label_visibility="collapsed")
    with c[3]:
        dep = st.text_input(f"Regla {i + 1} organismo", key=f"d{i}", label_visibility="collapsed")
    with c[4]:
        words = st.text_input(f"Regla {i + 1} filtro de título", key=f"w{i}", label_visibility="collapsed")
    rules_input.append({"num": i + 1, "activa": act, "boletin": bol, "seccion": sec, "organismo": dep, "titulo": words})

submit = st.button("🚀 EJECUTAR VIGILANCIA", type="primary")

if submit:
    active_rules = [r for r in rules_input if r["activa"]]

    # Validar los filtros ANTES de descargar nada: una expresión mal escrita
    # se avisa en lugar de dejar la regla sin resultados en silencio.
    errores_reglas = []
    for r in active_rules:
        try:
            filtros.compilar_expresion(r["titulo"])
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
                if not filtros.match_multiples_palabras_or(anuncio["organismo"], rule["organismo"]):
                    continue
                if not filtros.evaluate_boolean(anuncio["titulo"], rule["titulo"]):
                    continue
                item = anuncio.copy()
                item["filtro_aplicado"] = rule["titulo"]
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
