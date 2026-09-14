from __future__ import annotations

import statistics
from collections import Counter

from .config import CLASS_HUMAN, CLASS_KEEP, CLASS_RULE


def analyze_conversations(data: dict) -> dict:
    leads = data["leads"]
    conversations = data["conversaciones"]

    lead_ids = {row["lead_id"] for row in leads}
    conv_lead_ids = [conv["lead_id"] for conv in conversations]
    matched = [conv for conv in conversations if conv["lead_id"] in lead_ids]
    unmatched = [conv for conv in conversations if conv["lead_id"] not in lead_ids]

    per_lead = Counter(conv_lead_ids)
    duplicated = {lead: count for lead, count in per_lead.items() if count > 1}

    message_counts = [len(conv.get("mensajes", [])) for conv in conversations]
    character_lengths = [
        sum(len(message.get("texto", "")) for message in conv.get("mensajes", []))
        for conv in conversations
    ]
    word_lengths = [
        sum(len(message.get("texto", "").split()) for message in conv.get("mensajes", []))
        for conv in conversations
    ]

    empty = [conv["conversacion_id"] for conv in conversations if not conv.get("mensajes")]
    no_cliente_first = [
        conv["conversacion_id"]
        for conv in conversations
        if conv.get("mensajes") and conv["mensajes"][0]["emisor"] != "cliente"
    ]
    single_sender = [
        conv["conversacion_id"]
        for conv in conversations
        if len({message["emisor"] for message in conv.get("mensajes", [])}) == 1
    ]

    lengths = {
        "mensajes_por_conversacion": dict(sorted(Counter(message_counts).items())),
        "caracteres": {
            "min": min(character_lengths),
            "max": max(character_lengths),
            "media": round(statistics.mean(character_lengths), 1),
            "mediana": statistics.median(character_lengths),
        },
        "palabras": {
            "min": min(word_lengths),
            "max": max(word_lengths),
            "media": round(statistics.mean(word_lengths), 1),
            "mediana": statistics.median(word_lengths),
        },
        "emisores": dict(Counter(message["emisor"] for conv in conversations for message in conv.get("mensajes", []))),
    }

    issues = [
        {
            "id": "C01",
            "dataset": "conversaciones",
            "campo": "lead_id",
            "tipo": "referencia_rota",
            "clasificacion": CLASS_HUMAN,
            "n_afectados": len(unmatched),
            "descripcion": "Conversaciones cuyo lead_id no existe en leads.csv (IDs fuera del rango LD-00001..LD-01501).",
            "ejemplo": [
                {"conversacion_id": conv["conversacion_id"], "lead_id": conv["lead_id"], "fecha_inicio": conv["fecha_inicio"]}
                for conv in unmatched[:6]
            ],
        },
        {
            "id": "C02",
            "dataset": "conversaciones",
            "campo": "lead_id",
            "tipo": "duplicados",
            "clasificacion": CLASS_RULE,
            "n_afectados": len(duplicated),
            "descripcion": "lead_id con más de una conversación. No es posible decidir sin regla si son sesiones distintas o duplicados.",
            "ejemplo": dict(list(sorted(duplicated.items()))[:5]),
        },
        {
            "id": "C03",
            "dataset": "leads",
            "campo": "lead_id",
            "tipo": "cobertura",
            "clasificacion": CLASS_KEEP,
            "n_afectados": len(lead_ids - set(conv_lead_ids)),
            "descripcion": "Leads sin conversación asociada. Coherente con que solo WhatsApp tiene transcripción.",
        },
    ]

    return {
        "total_conversaciones": len(conversations),
        "lead_ids_distintos": len(set(conv_lead_ids)),
        "conversaciones_con_match": len(matched),
        "conversaciones_sin_match": len(unmatched),
        "leads_sin_conversacion": len(lead_ids - set(conv_lead_ids)),
        "lead_id_duplicados": len(duplicated),
        "detalle_lead_id_duplicados": dict(sorted(duplicated.items())),
        "vacios": empty,
        "no_inicia_cliente": no_cliente_first,
        "un_solo_emisor": single_sender,
        "longitudes": lengths,
        "ejemplos_sin_match": [
            {"conversacion_id": conv["conversacion_id"], "lead_id": conv["lead_id"], "fecha_inicio": conv["fecha_inicio"]}
            for conv in unmatched
        ],
        "issues": issues,
    }
