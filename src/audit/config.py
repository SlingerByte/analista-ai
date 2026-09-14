from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"
REPORTS_DIR = PROJECT_ROOT / "reports"

LEADS = DATA_DIR / "leads.csv"
CONVERSACIONES = DATA_DIR / "conversaciones.json"
CATALOGO = DATA_DIR / "catalogo_motos.csv"
ASESORES = DATA_DIR / "asesores.csv"
HISTORICO = DATA_DIR / "historico_cierres.csv"

CSV_FILES = {
    "leads": LEADS,
    "catalogo_motos": CATALOGO,
    "asesores": ASESORES,
    "historico_cierres": HISTORICO,
}

JSON_FILES = {
    "conversaciones": CONVERSACIONES,
}

CLASS_AUTO = "corregible_automaticamente"
CLASS_RULE = "requiere_regla_de_negocio"
CLASS_KEEP = "debe_conservarse_como_dato_original"
CLASS_HUMAN = "requiere_revision_humana"

CLASSIFICATIONS = [CLASS_AUTO, CLASS_RULE, CLASS_KEEP, CLASS_HUMAN]
