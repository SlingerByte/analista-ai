"""Normalización de nombres para presentación (`app.presentation.display_name`)."""

from __future__ import annotations

from app.presentation import display_name


def test_mayusculas():
    assert display_name("BRAYAN TORRES OSORIO") == "Brayan Torres Osorio"


def test_minusculas():
    assert display_name("brayan torres osorio") == "Brayan Torres Osorio"


def test_mixto():
    assert display_name("Brayan TORRES Osorio") == "Brayan Torres Osorio"


def test_espacios_externos_y_repetidos():
    assert display_name("  BRAYAN   TORRES OSORIO  ") == "Brayan Torres Osorio"


def test_tildes_mayusculas():
    assert display_name("ÓSCAR DAVID FRANCO OSPINA") == "Óscar David Franco Ospina"


def test_tildes_minusculas():
    assert display_name("vanessa ramírez quintero") == "Vanessa Ramírez Quintero"


def test_ya_formateado_no_cambia():
    assert display_name("Brayan Torres Osorio") == "Brayan Torres Osorio"
    assert display_name("Ana María") == "Ana María"


def test_none_y_vacio():
    assert display_name(None) is None
    assert display_name("") is None
    assert display_name("   ") is None


def test_unicode_valido_e_iniciales():
    assert display_name("JOSÉ ÑÁÑEZ") == "José Ñáñez"
    assert display_name("o'neill gómez") == "O'Neill Gómez"
    assert display_name("maría-josé gómez") == "María-José Gómez"
    assert display_name("A. AGUDELO OSPINA") == "A. Agudelo Ospina"


def test_capitalizacion_mixta_no_se_alterada():
    # No inventamos ni corregimos capitalización ya mixta.
    assert display_name("MismoPos") == "MismoPos"
    assert display_name("McDonald") == "McDonald"
    assert display_name("Ana Alta") == "Ana Alta"


def test_es_pura_no_muta_el_valor():
    original = "BRAYAN   TORRES OSORIO"
    assert display_name(original) == "Brayan Torres Osorio"
    assert original == "BRAYAN   TORRES OSORIO"  # no muta


def test_filtro_jinja_disponible_en_plantillas():
    from app.dashboard import templates

    assert "display_name" in templates.env.filters
    rendered = templates.env.from_string(
        "{{ n | display_name }}").render(n="BRAYAN TORRES OSORIO")
    assert rendered == "Brayan Torres Osorio"
