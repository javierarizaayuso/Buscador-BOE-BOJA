import pytest

from filtros import (ExpresionBooleanaError, evaluate_boolean,
                     match_multiples_palabras_or, normalizar, resaltar_palabras)


def test_normalizar_quita_tildes_y_mayusculas():
    assert normalizar("Transición ECOLÓGICA") == "transicion ecologica"
    assert normalizar(None) == ""


# --- expresiones booleanas ---

def test_or_basico():
    expr = "ayuda OR subvencion OR incentivos"
    assert evaluate_boolean("Convocatoria de ayudas a la pyme", expr)
    assert evaluate_boolean("SUBVENCIÓN directa", expr)
    assert not evaluate_boolean("Nombramiento de funcionario", expr)


def test_not_y_and():
    expr = "NOT riego AND NOT sancionador"
    assert evaluate_boolean("Obras de carretera", expr)
    assert not evaluate_boolean("Comunidad de regantes: riego", expr)
    assert not evaluate_boolean("Procedimiento sancionador", expr)


def test_precedencia_and_sobre_or():
    # a OR (b AND c)
    assert evaluate_boolean("a", "a OR b AND c") is True
    assert evaluate_boolean("b", "a OR b AND c") is False
    assert evaluate_boolean("b c", "a OR b AND c") is True


def test_expresion_real_de_movilidad():
    expr = "DGT OR comunicaciones OR ADIF AND NOT formalización"
    assert evaluate_boolean("Resolución de la DGT sobre formalización", expr)  # DGT basta (OR)
    assert not evaluate_boolean("ADIF: formalizacion de contrato", expr)
    assert evaluate_boolean("ADIF: obras en la línea", expr)


def test_parentesis():
    expr = "(a OR b) AND c"
    assert not evaluate_boolean("a", expr)
    assert evaluate_boolean("a c", expr)
    assert evaluate_boolean("b c", expr)


def test_expresion_vacia_siempre_coincide():
    assert evaluate_boolean("lo que sea", "")
    assert evaluate_boolean("lo que sea", "   ")


@pytest.mark.parametrize("expr", [
    "ayuda AND",
    "(ayuda",
    "ayuda)",
    "ayuda subvencion",
    "AND ayuda",
    "NOT",
])
def test_expresiones_invalidas_dan_error(expr):
    with pytest.raises(ExpresionBooleanaError):
        evaluate_boolean("texto", expr)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hola')",
    "ayuda; drop",
    "a.__class__",
    "ayuda & subvencion",
])
def test_no_se_ejecuta_codigo(expr):
    with pytest.raises(ExpresionBooleanaError):
        evaluate_boolean("texto", expr)


def test_palabras_con_guion():
    assert evaluate_boolean("Plan COVID-19 en Andalucía", "covid-19")


# --- coincidencia por palabras (secciones / organismos) ---

def test_coincidencia_al_inicio_de_palabra():
    assert match_multiples_palabras_or("Ministerio para la Transición Ecológica", "ecologica")
    assert match_multiples_palabras_or("Convocatoria de subvenciones", "subvencion")
    assert not match_multiples_palabras_or("Venta de paraguas", "agua")


def test_or_entre_palabras_del_filtro():
    assert match_multiples_palabras_or("Ministerio de Hacienda", "ecologica hacienda")
    assert not match_multiples_palabras_or("Ministerio de Justicia", "ecologica hacienda")


def test_filtro_vacio_coincide():
    assert match_multiples_palabras_or("cualquier cosa", "")
    assert match_multiples_palabras_or("cualquier cosa", None)


# --- resaltado ---

def test_resaltado_con_tildes():
    assert resaltar_palabras("Ayudas para la subvención de empresas", "ayuda OR subvencion") == \
        "**Ayuda**s para la **subvención** de empresas"


def test_resaltado_ignora_palabras_negadas():
    assert resaltar_palabras("Ayuda y riego", "ayuda AND NOT riego") == "**Ayuda** y riego"


def test_resaltado_sin_filtro_o_invalido_devuelve_titulo():
    assert resaltar_palabras("Título", "") == "Título"
    assert resaltar_palabras("Título", "(roto") == "Título"
