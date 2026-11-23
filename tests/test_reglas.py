import json

import pytest

import reglas
from reglas import (MAX_REGLAS, ReglasError, cargar_reglas_archivo, normalizar_reglas,
                    reglas_a_json, reglas_desde_json)


def test_ida_y_vuelta_conserva_tildes_y_contenido():
    original = normalizar_reglas(reglas.REGLAS_INTEGRADAS)
    texto = reglas_a_json(original)
    assert "formalización" in texto and "\\u" not in texto
    assert reglas_desde_json(texto) == original


def test_rellena_hasta_el_maximo_con_reglas_inactivas():
    r = normalizar_reglas([{"boletin": "BOJA", "titulo": "ayuda"}])
    assert len(r) == MAX_REGLAS
    assert r[0] == {"activa": True, "boletin": "BOJA", "seccion": "", "organismo": "", "titulo": "ayuda"}
    assert all(x["activa"] is False for x in r[1:])


def test_acepta_lista_directa_y_boletin_en_minusculas():
    r = normalizar_reglas([{"boletin": "boe"}])
    assert r[0]["boletin"] == "BOE"


def test_demasiadas_reglas():
    with pytest.raises(ReglasError, match="máximo"):
        normalizar_reglas([{}] * (MAX_REGLAS + 1))


@pytest.mark.parametrize("datos", [
    {"reglas": "no es lista"},
    {"otra_cosa": []},
    42,
    {"reglas": [["no", "dict"]]},
    {"reglas": [{"boletin": "DOUE"}]},
    {"reglas": [{"activa": "si"}]},
    {"reglas": [{"titulo": 5}]},
])
def test_datos_invalidos(datos):
    with pytest.raises(ReglasError):
        normalizar_reglas(datos)


def test_json_roto_indica_posicion():
    with pytest.raises(ReglasError, match="JSON válido"):
        reglas_desde_json('{"reglas": [')


def test_el_archivo_reglas_json_del_repo_es_valido_e_igual_al_respaldo():
    r, aviso = cargar_reglas_archivo("reglas.json")
    assert aviso is None
    assert r == normalizar_reglas(reglas.REGLAS_INTEGRADAS)


def test_archivo_inexistente_usa_respaldo_sin_aviso(tmp_path):
    r, aviso = cargar_reglas_archivo(tmp_path / "no_existe.json")
    assert aviso is None and len(r) == MAX_REGLAS


def test_archivo_roto_usa_respaldo_con_aviso(tmp_path):
    p = tmp_path / "reglas.json"
    p.write_text("{esto no es json", encoding="utf-8")
    r, aviso = cargar_reglas_archivo(p)
    assert "reglas integradas" in aviso
    assert r == normalizar_reglas(reglas.REGLAS_INTEGRADAS)


def test_archivo_con_bom(tmp_path):
    p = tmp_path / "reglas.json"
    p.write_text(json.dumps({"reglas": [{"boletin": "BOE", "titulo": "x"}]}), encoding="utf-8-sig")
    r, aviso = cargar_reglas_archivo(p)
    assert aviso is None and r[0]["titulo"] == "x"
