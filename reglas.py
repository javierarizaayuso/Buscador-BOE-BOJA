"""Reglas de vigilancia: valores por defecto, validación y (de)serialización JSON.

Sin dependencias de Streamlit, para poder probarlo de forma aislada.

Formato del archivo (reglas.json):
{
  "version": 1,
  "reglas": [
    {"activa": true, "boletin": "BOE", "seccion": "", "organismo": "", "titulo": "ayuda OR subvencion"},
    ...
  ]
}
"""
import json
from pathlib import Path

MAX_REGLAS = 10
BOLETINES = ("BOE", "BOJA")
VERSION_FORMATO = 1

REGLA_VACIA = {"activa": False, "boletin": "BOE", "seccion": "", "organismo": "", "titulo": ""}

# Respaldo por si reglas.json no existe o está mal escrito.
REGLAS_INTEGRADAS = [
    {"activa": True, "boletin": "BOE", "seccion": "", "organismo": "", "titulo": "ayuda OR subvencion OR incentivos"},
    {"activa": True, "boletin": "BOE", "seccion": "", "organismo": "jefatura competencia", "titulo": ""},
    {"activa": True, "boletin": "BOE", "seccion": "", "organismo": "ecologica", "titulo": "NOT riego AND NOT subterranea AND NOT vertido AND NOT extincion AND NOT sancionador"},
    {"activa": True, "boletin": "BOE", "seccion": "", "organismo": "movilidad", "titulo": "DGT OR comunicaciones OR ADIF AND NOT formalización"},
    {"activa": False, "boletin": "BOE", "seccion": "", "organismo": "", "titulo": ""},
    {"activa": True, "boletin": "BOJA", "seccion": "", "organismo": "agricultura hacienda empleo industria sostenibilidad", "titulo": "ayuda OR subvencion OR incentivos"},
    {"activa": True, "boletin": "BOJA", "seccion": "generales", "organismo": "presidencia", "titulo": ""},
    {"activa": True, "boletin": "BOJA", "seccion": "otras anuncios generales", "organismo": "hacienda agua sostenibilidad energía fomento", "titulo": "NOT riego AND NOT subterranea AND NOT vertido AND NOT extincion AND NOT sancionador AND NOT comparecencia"},
    {"activa": True, "boletin": "BOJA", "seccion": "", "organismo": "Ayuntamientos", "titulo": "Córdoba OR Málaga"},
    {"activa": False, "boletin": "BOJA", "seccion": "", "organismo": "", "titulo": ""},
]


class ReglasError(ValueError):
    """El contenido de un archivo de reglas no es válido."""


def _texto(valor, nombre, num):
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise ReglasError(f"Regla {num}: «{nombre}» debe ser texto.")
    return valor


def normalizar_reglas(datos):
    """Valida los datos leídos del JSON y devuelve exactamente MAX_REGLAS reglas.

    Acepta {"reglas": [...]} o directamente una lista. Si hay menos de
    MAX_REGLAS, rellena con reglas inactivas. Lanza ReglasError si algo falla.
    """
    if isinstance(datos, dict):
        datos = datos.get("reglas")
    if not isinstance(datos, list):
        raise ReglasError('El archivo debe contener una lista "reglas".')
    if len(datos) > MAX_REGLAS:
        raise ReglasError(f"Hay {len(datos)} reglas y el máximo es {MAX_REGLAS}.")

    resultado = []
    for num, r in enumerate(datos, start=1):
        if not isinstance(r, dict):
            raise ReglasError(f"Regla {num}: debe ser un objeto con campos.")
        activa = r.get("activa", True)
        if not isinstance(activa, bool):
            raise ReglasError(f"Regla {num}: «activa» debe ser true o false.")
        boletin = _texto(r.get("boletin", "BOE"), "boletin", num).strip().upper()
        if boletin not in BOLETINES:
            raise ReglasError(f"Regla {num}: «boletin» debe ser BOE o BOJA (recibido: «{boletin}»).")
        resultado.append({
            "activa": activa,
            "boletin": boletin,
            "seccion": _texto(r.get("seccion"), "seccion", num),
            "organismo": _texto(r.get("organismo"), "organismo", num),
            "titulo": _texto(r.get("titulo"), "titulo", num),
        })
    while len(resultado) < MAX_REGLAS:
        resultado.append(dict(REGLA_VACIA))
    return resultado


def reglas_a_json(reglas):
    """Serializa las reglas a texto JSON legible (con tildes sin escapar)."""
    return json.dumps({"version": VERSION_FORMATO, "reglas": reglas},
                      ensure_ascii=False, indent=2) + "\n"


def reglas_desde_json(texto):
    """Interpreta un texto JSON y devuelve las reglas validadas."""
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ReglasError(f"El archivo no es un JSON válido (línea {e.lineno}, columna {e.colno}).") from e
    return normalizar_reglas(datos)


def cargar_reglas_archivo(ruta):
    """Lee las reglas por defecto de un archivo.

    Devuelve (reglas, aviso). Si el archivo no existe o es inválido, devuelve
    las reglas integradas y un aviso explicándolo (None si todo fue bien).
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return normalizar_reglas(REGLAS_INTEGRADAS), None
    try:
        return reglas_desde_json(ruta.read_text(encoding="utf-8-sig")), None
    except (OSError, UnicodeDecodeError, ReglasError) as e:
        return (normalizar_reglas(REGLAS_INTEGRADAS),
                f"No se pudo leer {ruta.name} ({e}). Se usan las reglas integradas.")
