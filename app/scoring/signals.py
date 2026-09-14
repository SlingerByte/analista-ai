from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeadSignals:
    """Señales de entrada del scoring. Todo es Optional-a-excepción-del-id.

    Convenciones (no se inventa nada):

    - ``list_price`` es el precio de catálogo del modelo resuelto. ``None``
      significa modelo ambiguo, sin match o sin precio: el engine no asume.
    - Las señales IA en ``None`` significan desconocidas, nunca negativas.
    - ``days_since_registration`` en ``None`` significa fecha ausente o no
      confiable (ambigua). Se calcula fuera del engine para que el score sea
      una función pura y reproducible (mismos datos → mismo score).
    - ``has_conversation`` distingue "sin conversación" (esperable, no resta)
      de "con conversación pero sin señal" (incertidumbre que se reporta).
    """

    lead_id: str

    # Contexto comercial (estructural + IA).
    list_price: float | None = None
    model_resolved: bool = False
    presupuesto: float | None = None
    cuota_inicial: float | None = None
    forma_pago: str | None = None
    intencion_compra: str | None = None
    objecion: str | None = None
    solicitud_cita: bool | None = None
    solicitud_cotizacion: bool | None = None
    has_conversation: bool = False

    # Calidad / completitud del dato.
    phone_valid: bool = False
    email_present: bool = False
    city_present: bool = False
    registration_trustworthy: bool = False

    # Urgencia operativa.
    estado_gestion: str | None = None
    days_since_registration: int | None = None
    has_first_contact: bool = False
