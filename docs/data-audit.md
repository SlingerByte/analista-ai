# Auditoría de datos - Prueba técnica Analista de IA

> Documento generado automáticamente por `scripts/run_audit.py`.
> Generado: 2026-09-14T10:38:56 · Python 3.10.11 · Modo solo lectura.
> Los archivos de `data/` no se modifican. Ver hashes SHA-256 abajo para verificar la evidencia.

## 0. Archivos auditados y garantía de no modificación

La auditoría abre los archivos originales en modo lectura y nunca escribe en `data/`.
Hashes al momento de ejecutar (re-ejecutar debe reproducir los mismos hashes):

| Archivo | Ruta | Bytes | SHA-256 (prefijo) |
| --- | --- | --- | --- |
| leads | data/leads.csv | 250,658 | b95c10b3106bc8f4… |
| catalogo_motos | data/catalogo_motos.csv | 2,568 | 1388ffa40ce57e51… |
| asesores | data/asesores.csv | 2,807 | 55db5ae9a36cce6f… |
| historico_cierres | data/historico_cierres.csv | 218,954 | ce8e7fd93c3e0036… |
| conversaciones | data/conversaciones.json | 688,512 | e5f76c5548e7a432… |

## 1. Estructura de cada archivo

### leads.csv

- Registros: 1503 · Columnas: 13

| Columna | Tipo inferido | Nulos | % Nulos | Únicos | Ejemplos |
| --- | --- | --- | --- | --- | --- |
| lead_id | identificador | 0 | 0.0% | 1501 | LD-00011, LD-00251 |
| fecha_registro | fecha | 0 | 0.0% | 1319 | 09-08-2026, 31-08-2026 |
| canal | texto | 1 | 0.07% | 9 | WhatsApp, Meta Ads |
| empresa_id | identificador | 0 | 0.0% | 3 | EMP-02, EMP-01 |
| punto_venta_id | identificador | 0 | 0.0% | 15 | PV-008, PV-014 |
| nombre_cliente | texto | 0 | 0.0% | 1442 | Nelson Rodríguez Castaño, Marcela Muñoz Valencia |
| telefono | texto | 0 | 0.0% | 1466 | 315 229 3701, 3176036920 |
| email | texto | 700 | 46.57% | 802 | marcela.munoz15@yahoo.es, claudia.agudelo22@hotmail.com |
| ciudad | texto | 79 | 5.26% | 36 | Medellín, Bogotá D.C. |
| modelo_interes_texto | texto | 80 | 5.32% | 190 | Honda Navi, Bajaj Boxer CT 100 |
| estado_gestion | texto | 0 | 0.0% | 10 | Contactado, Sin gestión |
| fecha_primer_contacto | fecha | 487 | 32.4% | 848 | 26-08-2026, 25-08-2026 |
| campania | texto | 434 | 28.88% | 5 | Feria de Motos 2026, Agosto Cero Cuotas |

### catalogo_motos.csv

- Registros: 24 · Columnas: 8

| Columna | Tipo inferido | Nulos | % Nulos | Únicos | Ejemplos |
| --- | --- | --- | --- | --- | --- |
| sku | identificador | 0 | 0.0% | 24 | SKU-001, SKU-002 |
| marca | texto | 0 | 0.0% | 5 | Honda, Bajaj |
| linea | texto | 0 | 0.0% | 24 | CB 125F Twister, XR 150L |
| cilindraje | entero | 0 | 0.0% | 14 | 125, 110 |
| segmento | texto | 0 | 0.0% | 5 | Trabajo, Deportiva |
| precio_lista | entero | 0 | 0.0% | 24 | 7990000, 11490000 |
| puntos_venta_disponibles | texto | 0 | 0.0% | 24 | PV-001\\|PV-003\\|PV-006\\|PV-007\\|PV-008\\|PV-009\\|PV-010\\|PV-011\\|PV-015, PV-002\\|PV-004\\|PV-012\\|PV-015 |
| unidades_disponibles | entero | 0 | 0.0% | 16 | 12, 10 |

### asesores.csv

- Registros: 42 · Columnas: 7

| Columna | Tipo inferido | Nulos | % Nulos | Únicos | Ejemplos |
| --- | --- | --- | --- | --- | --- |
| asesor_id | identificador | 0 | 0.0% | 42 | AS-001, AS-002 |
| nombre | texto | 0 | 0.0% | 42 | Édinson Mosquera Pérez, Andrés Felipe Bedoya Salazar |
| punto_venta_id | identificador | 0 | 0.0% | 15 | PV-001, PV-002 |
| empresa_id | identificador | 0 | 0.0% | 3 | EMP-01, EMP-03 |
| capacidad_diaria_leads | entero | 0 | 0.0% | 5 | 20, 15 |
| activo | booleano | 0 | 0.0% | 2 | SI, NO |
| fecha_ingreso | fecha | 0 | 0.0% | 42 | 2026-02-27, 2025-02-10 |

### historico_cierres.csv

- Registros: 2200 · Columnas: 13

| Columna | Tipo inferido | Nulos | % Nulos | Únicos | Ejemplos |
| --- | --- | --- | --- | --- | --- |
| lead_id | identificador | 0 | 0.0% | 2200 | HX-00001, HX-00002 |
| fecha_registro | fecha | 0 | 0.0% | 150 | 2026-05-05, 2026-03-24 |
| canal | texto | 0 | 0.0% | 3 | WhatsApp, Meta Ads |
| empresa_id | identificador | 0 | 0.0% | 3 | EMP-01, EMP-03 |
| punto_venta_id | identificador | 0 | 0.0% | 15 | PV-001, PV-015 |
| modelo_cotizado | texto | 0 | 0.0% | 24 | Bajaj Pulsar NS 125, Honda XR 150L |
| precio_lista | entero | 0 | 0.0% | 24 | 8990000, 11490000 |
| horas_al_primer_contacto | texto | 179 | 8.14% | 10 | 2, 4 |
| numero_contactos | entero | 0 | 0.0% | 8 | 5, 7 |
| manifesto_cuota_inicial | texto | 0 | 0.0% | 3 | SI, NO |
| forma_pago_declarada | texto | 0 | 0.0% | 3 | credito, no_informa |
| pidio_cita | booleano | 0 | 0.0% | 2 | NO, SI |
| desenlace | texto | 0 | 0.0% | 3 | Perdido, Cerrado |

### conversaciones.json

- Registros: 677
- Campos de conversación: canal, conversacion_id, fecha_inicio, lead_id, mensajes
- Campos de mensaje: emisor, hora, texto
- Mensajes totales: 4310

## 2. Calidad de datos

### 2.1 Duplicados

- Filas completamente duplicadas en `leads.csv`: 2 (grupos: 2; lead_id: LD-00011, LD-00251).
- `lead_id` repetidos en `leads.csv`: ['LD-00011', 'LD-00251'].
- Teléfonos normalizados compartidos por más de un `lead_id`: 140 (280 leads involucrados; máx. leads por teléfono: 2).
- Emails normalizados repetidos: 1.

### 2.2 Teléfonos

- Teléfonos con formato distinto a 10 dígitos planos: 847 registros.
| Formato detectado | Registros |
| --- | --- |
| otro | 1 |
| parentesis | 120 |
| plano_10 | 656 |
| prefijo_57_separado | 203 |
| prefijo_57_sin_signo | 129 |
| separado_10 | 394 |

- Teléfonos inválidos (longitud distinta de 10-12 dígitos): 1 → [{'lead_id': 'LD-01501', 'telefono': '300123'}].

### 2.3 Emails

- Presentes: 803 · Faltantes: 700 (46.57%).
- Sintácticamente inválidos: 0.
- Duplicados: {'marcela.munoz15@yahoo.es': 2}.

### 2.4 Fechas

| Columna | Formatos detectados | Ambiguos DD/MM vs MM/DD | Ambiguos DD-MM (convención) | Desconocidos |
| --- | --- | --- | --- | --- |
| fecha_registro | DD-MM-YYYY=219, DD/MM/YYYY=204, DD/MM/YYYY vs MM/DD/YYYY=265, ISO_SPACE=592, ISO_T=163, MM/DD/YYYY=59, desconocido=1 | 265 | 113 | 1 |
| fecha_primer_contacto | DD-MM-YYYY=208, DD/MM/YYYY=96, DD/MM/YYYY vs MM/DD/YYYY=216, ISO_SPACE=200, ISO_T=203, MM/DD/YYYY=93, vacio=487 | 216 | 107 | 0 |

> Las fechas con guion (`DD-MM-YYYY`) se interpretaron como día-mes por convención local; aun así pueden ser ambiguas en principio y se reportan aparte. Las fechas con barra mezclan evidencia de DD/MM y de MM/DD, por lo que las ambiguas quedan sin resolver.

- Inconsistencias cronológicas (`fecha_primer_contacto` < `fecha_registro`): 29 (se omitieron 424 pares con fecha ambigua; no comparables por formato: 0).
- Leads gestionados (estado distinto de 'Sin gestión') sin `fecha_primer_contacto`: 86.

### 2.5 Ciudades

- Valores crudos distintos: 36 · Normalizados: 11 · Vacíos: 79.
- Alias aplicados (basados en evidencia): {'bogota d.c.': 'bogota', 'bogota dc': 'bogota', 'cartagena de indias': 'cartagena', 'sta marta': 'santa marta', 'rio negro': 'rionegro', 'b/quilla': 'barranquilla', 'itagui': 'itagui'}.
| Ciudad normalizada | Leads |
| --- | --- |
| barranquilla | 104 |
| bello | 107 |
| bogota | 378 |
| cartagena | 113 |
| itagui | 88 |
| medellin | 178 |
| monteria | 95 |
| rionegro | 94 |
| santa marta | 99 |
| soacha | 90 |
| soledad | 78 |

### 2.6 Modelos de interés en leads

- Textos crudos distintos: 190.
| Resultado de normalización | Leads |
| --- | --- |
| directo_unico | 1245 |
| prefijo_ambiguo | 18 |
| prefijo_unico | 63 |
| solo_marca | 97 |
| vacio | 80 |

- Sin match tras normalizar: [].

### 2.7 Canal y estado de gestión (variantes de formato)

- Canal crudo: {'': 1, 'FORMULARIO WEB': 26, 'Formulario Web': 174, 'META ADS': 36, 'Meta Ads': 384, 'WHATSAPP': 68, 'WhatsApp': 689, 'formulario web': 21, 'meta ads': 37, 'whatsapp': 67}.
- Canal normalizado: {'Meta Ads': 457, 'Formulario Web': 221, 'WhatsApp': 824, 'None': 1}.
- Estado crudo: {'Contactado': 285, 'Cotización enviada': 202, 'Descartado': 149, 'En proceso': 178, 'No contesta': 150, 'SIN GESTION': 44, 'Sin gestión': 258, 'contactado': 69, 'no contesta': 69, 'sin gestion': 99}.
- Estado normalizado: {'Cotización enviada': 202, 'Descartado': 149, 'Contactado': 354, 'Sin gestión': 401, 'En proceso': 178, 'No contesta': 219}.

### 2.8 Nombres de cliente

- Con espacios sobrantes: 281 · En mayúsculas: 305.
- Posibles clientes repetidos (nombre + teléfono normalizados): 93.

## 3. Relaciones entre datasets

- Mapa empresa → puntos de venta (desde `asesores.csv`): {'EMP-01': ['PV-001', 'PV-002', 'PV-003', 'PV-004', 'PV-005'], 'EMP-02': ['PV-006', 'PV-007', 'PV-008', 'PV-009', 'PV-010'], 'EMP-03': ['PV-011', 'PV-012', 'PV-013', 'PV-014', 'PV-015']}.
- Puntos de venta válidos: 15 · Puntos del catálogo sin asesor: [].
- Puntos de venta inválidos en catálogo: 0.
- `leads` ↔ `historico_cierres` por `lead_id`: 0 coincidencias (prefijos: leads=['LD'], histórico=['HX']).
- `leads` ↔ `conversaciones` por `lead_id`: 665 conversaciones coinciden, 12 no coinciden.
- Validaciones de referencias (empresa/punto): [{'dataset': 'leads', 'pv_desconocido': [], 'empresa_inconsistente_con_pv': []}, {'dataset': 'historico_cierres', 'pv_desconocido': [], 'empresa_inconsistente_con_pv': []}, {'dataset': 'asesores', 'pv_desconocido': [], 'empresa_inconsistente_con_pv': []}].

## 4. Conversaciones

- Total: 677 · `lead_id` distintos: 652.
- Con match a `leads.csv`: 665 · Sin match: 12.
- Leads sin conversación: 861.
- `lead_id` con más de una conversación: 25.
- Conversaciones vacías: 0 · Que no inician con cliente: 0 · De un solo emisor: 0.
- Mensajes por conversación: {3: 73, 6: 258, 7: 225, 8: 121}.
- Caracteres por conversación: {'min': 196, 'max': 545, 'media': 392.0, 'mediana': 414}.
- Palabras por conversación: {'min': 34, 'max': 99, 'media': 69.4, 'mediana': 74}.
- Emisores: {'cliente': 2610, 'asesor': 1700}.

Conversaciones sin match (bloque anómalo):

| conversacion_id | lead_id | fecha_inicio |
| --- | --- | --- |
| CONV-00648 | LD-99188 | 2026-08-15 11:00:00 |
| CONV-00650 | LD-95231 | 2026-08-15 11:00:00 |
| CONV-00641 | LD-98570 | 2026-08-15 11:00:00 |
| CONV-00643 | LD-96391 | 2026-08-15 11:00:00 |
| CONV-00647 | LD-90301 | 2026-08-15 11:00:00 |
| CONV-00646 | LD-91440 | 2026-08-15 11:00:00 |
| CONV-00642 | LD-91598 | 2026-08-15 11:00:00 |
| CONV-00652 | LD-94638 | 2026-08-15 11:00:00 |
| CONV-00651 | LD-93917 | 2026-08-15 11:00:00 |
| CONV-00649 | LD-91911 | 2026-08-15 11:00:00 |
| CONV-00645 | LD-98483 | 2026-08-15 11:00:00 |
| CONV-00644 | LD-99235 | 2026-08-15 11:00:00 |

## 5. Histórico

- Registros: 2200.
- Desenlace: {'Perdido': 1824, 'Cerrado': 197, 'Sin gestión': 179}.
- Por empresa: {'EMP-03': 723, 'EMP-02': 713, 'EMP-01': 764}.
- Por canal: {'WhatsApp': 1206, 'Meta Ads': 670, 'Formulario Web': 324}.
- Valores faltantes: {'horas_al_primer_contacto': {'n': 179, 'pct': 8.14}}.
- Numéricas: {'precio_lista': {'n': 2200, 'min': 4990000.0, 'max': 24900000.0, 'media': 10566222.73, 'mediana': 8990000.0}, 'numero_contactos': {'n': 2200, 'min': 0.0, 'max': 7.0, 'media': 3.8, 'mediana': 4.0}, 'horas_al_primer_contacto': {'n': 2021, 'min': 0.5, 'max': 120.0, 'media': 25.44, 'mediana': 8.0}}.
- Contactos por desenlace: {'Cerrado': {'n': 197, 'min': 1.0, 'max': 7.0, 'media': 4.23, 'mediana': 4.0}, 'Perdido': {'n': 1824, 'min': 1.0, 'max': 7.0, 'media': 4.13, 'mediana': 4.0}, 'Sin gestión': {'n': 179, 'min': 0.0, 'max': 0.0, 'media': 0.0, 'mediana': 0.0}}.
- Horas por desenlace: {'Cerrado': {'n': 197, 'min': 0.5, 'max': 120.0, 'media': 17.33, 'mediana': 4.0}, 'Perdido': {'n': 1824, 'min': 0.5, 'max': 120.0, 'media': 26.31, 'mediana': 8.0}}.

### 5.1 Variables candidatas a data leakage

| Variable | Clasificación | Afectados | Motivo |
| --- | --- | --- | --- |
| horas_al_primer_contacto | requiere_regla_de_negocio | 179 | El nulo coincide exactamente con 'Sin gestión': la variable se registra después de gestionar y delata el desenlace. |
| numero_contactos | requiere_regla_de_negocio | 179 | El valor 0 coincide exactamente con 'Sin gestión'; se comporta como consecuencia del desenlace. |
| desenlace | variable_objetivo |  | Es la etiqueta a predecir; nunca debe entrar como predictor. |
| precio_lista | debe_conservarse_como_dato_original |  | Disponible en catálogo antes de la gestión; no hay evidencia de fuga, aunque su utilidad es limitada. |
| manifesto_cuota_inicial | requiere_regla_de_negocio |  | Declarado por el cliente durante la gestión; debe confirmarse si estaba disponible al momento de priorizar. |
| forma_pago_declarada | requiere_regla_de_negocio |  | Declarado por el cliente durante la gestión; debe confirmarse su momento de captura. |
| pidio_cita | requiere_regla_de_negocio |  | Comportamiento previo a la decisión, pero podría registrarse después; requiere confirmación. |

Variables disponibles antes de la gestión (candidatas a priorización): ['canal', 'empresa_id', 'punto_venta_id', 'modelo_cotizado', 'precio_lista', 'fecha_registro'].

## 6. Catálogo

- Registros: 24 · Líneas únicas: 24.
- Marcas: {'Honda': 6, 'Bajaj': 6, 'Suzuki': 4, 'AKT': 4, 'Hero': 4}.
- Segmentos: {'Trabajo': 7, 'Doble propósito': 4, 'Deportiva': 7, 'Scooter': 4, 'Turismo': 2}.
- Cilindrajes: {'100': 2, '110': 3, '124': 3, '125': 4, '150': 2, '155': 1, '160': 1, '163': 1, '184': 1, '196': 1, '199': 2, '249': 1, '291': 1, '373': 1}.
- Precios: {'min': 4990000, 'max': 24900000, 'media': 10695417}.
- Unidades disponibles: {'total': 326, 'min': 2, 'max': 24}.
- Cobertura de puntos de venta por SKU: {'min': 3, 'max': 11}.
- Modelos del histórico sin catálogo: [].
- Inconsistencias de precio histórico vs catálogo: 0.
- Modelos de leads sin match: [].

## 7. Asesores

- Registros: 42.
- Por empresa: {'EMP-01': 16, 'EMP-02': 12, 'EMP-03': 14}.
- Por punto de venta: {'PV-001': 4, 'PV-002': 4, 'PV-003': 4, 'PV-004': 2, 'PV-005': 2, 'PV-006': 2, 'PV-007': 2, 'PV-008': 3, 'PV-009': 3, 'PV-010': 2, 'PV-011': 4, 'PV-012': 4, 'PV-013': 2, 'PV-014': 2, 'PV-015': 2}.
- Activos: {'SI': 40, 'NO': 2} · Inactivos: [{'asesor_id': 'AS-037', 'punto_venta_id': 'PV-013', 'empresa_id': 'EMP-03'}, {'asesor_id': 'AS-040', 'punto_venta_id': 'PV-014', 'empresa_id': 'EMP-03'}].
- Capacidad diaria: {12: 9, 15: 10, 18: 8, 20: 10, 25: 5}.
- Capacidad diaria por punto de venta: {'PV-001': 77, 'PV-002': 63, 'PV-003': 66, 'PV-004': 32, 'PV-005': 40, 'PV-006': 35, 'PV-007': 24, 'PV-008': 60, 'PV-009': 55, 'PV-010': 27, 'PV-011': 60, 'PV-012': 86, 'PV-013': 12, 'PV-014': 20, 'PV-015': 37}.
- Puntos sin asesor activo: [].

## 8. Inconsistencias detectadas y clasificación

Clasificación usada:

- **Corregible automáticamente**: se puede normalizar sin decisión de negocio (deduplicar filas idénticas, unificar mayúsculas/acentos, canonizar teléfonos, mapear ciudades con alias evidentes).
- **Requiere regla de negocio**: hay que definir una política (fechas ambiguas, duplicados de cliente, valores faltantes, unión de datasets).
- **Debe conservarse como dato original**: no es un error; se documenta y se preserva (cobertura parcial, desbalance de clases, referencias válidas).
- **Requiere revisión humana**: caso a caso (teléfono inválido, conversaciones sin match, email duplicado, inconsistencia cronológica).

| ID | Dataset | Campo | Tipo | Clasificación | Afectados | Descripción |
| --- | --- | --- | --- | --- | --- | --- |
| Q01 | leads | lead_id | duplicados | Corregible automáticamente | 2 | Filas completamente duplicadas (mismo lead_id y mismos valores). |
| Q02 | leads | canal | formatos | Corregible automáticamente | 255 | El mismo canal aparece con mayúsculas/minúsculas distintas. |
| Q03 | leads | estado_gestion | formatos | Corregible automáticamente | 281 | El mismo estado aparece con mayúsculas/minúsculas distintas. |
| Q04 | leads | fecha_registro / fecha_primer_contacto | fechas | Requiere regla de negocio | 265 | Fechas con barra realmente ambiguas entre DD/MM/YYYY y MM/DD/YYYY (día y mes <= 12); no se pueden resolver sin regla. |
| Q05 | leads | fecha_registro | fechas | Corregible automáticamente | 974 | Formatos de fecha mezclados (ISO-T, ISO con espacio, DD-MM-YYYY). |
| Q06 | leads | fecha_primer_contacto | integridad | Requiere revisión humana | 29 | fecha_primer_contacto anterior a fecha_registro. |
| Q07 | leads | telefono | formatos | Corregible automáticamente | 847 | Teléfonos con espacios, guiones, paréntesis y prefijo 57/+57. |
| Q08 | leads | telefono | valores_invalidos | Requiere revisión humana | 1 | Teléfonos con longitud distinta a 10-12 dígitos. |
| Q09 | leads | telefono | duplicados | Requiere regla de negocio | 140 | Teléfono normalizado compartido por más de un lead_id (280 leads involucrados). |
| Q10 | leads | email | valores_faltantes | Requiere regla de negocio | 700 | Email faltante en 46.57% de los leads. |
| Q11 | leads | email | duplicados | Requiere revisión humana | 1 | Email repetido entre leads distintos. |
| Q12 | leads | ciudad | formatos | Corregible automáticamente | 25 | Ciudades con variantes de mayúsculas/acentos y abreviaturas (Bogotá D.C., Sta Marta, B/quilla...). |
| Q13 | leads | ciudad | valores_faltantes | Requiere regla de negocio | 79 | Ciudad faltante. |
| Q14 | leads | modelo_interes_texto | formatos | Requiere regla de negocio | 115 | Modelo escrito solo como marca o de forma parcial/ambigua (no permite elegir un SKU único). |
| Q15 | leads | modelo_interes_texto | formatos | Corregible automáticamente | 1,308 | Modelo con typos de marca (Bajai, Hnda, Heroo, Suzuky), formato A.K.T y sufijo de año; normalizables a un SKU. |
| Q16 | leads | modelo_interes_texto | valores_faltantes | Requiere regla de negocio | 80 | Modelo de interés faltante. |
| Q17 | leads | campania | valores_faltantes | Debe conservarse como dato original | 434 | Campaña no informada; se conserva como ausencia. |
| Q18 | leads | fecha_primer_contacto | integridad | Requiere regla de negocio | 86 | Leads con estado de gestión distinto de 'Sin gestión' pero sin fecha_primer_contacto. |
| Q19 | leads | fecha_registro / fecha_primer_contacto | fechas | Requiere revisión humana | 1 | Valores de fecha con formato no reconocible (p. ej. día imposible). |
| Q20 | leads | canal | valores_faltantes | Requiere regla de negocio | 1 | Canal vacío: no se puede asignar a una fuente de adquisición. |
| Q21 | leads | nombre_cliente | formatos | Corregible automáticamente | 281 | Nombres con espacios sobrantes y mezcla de mayúsculas/minúsculas. |
| Q22 | leads | nombre_cliente / telefono | duplicados | Requiere regla de negocio | 93 | Posibles clientes repetidos (nombre normalizado + teléfono normalizado iguales). |
| R01 | todos | punto_venta_id / empresa_id | referencias | Debe conservarse como dato original | 0 | Sin referencias a puntos de venta inexistentes ni combinaciones empresa/punto incoherentes entre datasets. |
| R02 | catalogo_motos | puntos_venta_disponibles | referencias | Debe conservarse como dato original | 0 | Todos los puntos de venta del catálogo existen en asesores.csv. |
| R03 | leads / historico_cierres | lead_id | llave_compartida | Requiere regla de negocio | 0 | La intersección de lead_id entre leads (LD-) e histórico (HX-) es cero: no se pueden unir directamente. |
| C01 | conversaciones | lead_id | referencia_rota | Requiere revisión humana | 12 | Conversaciones cuyo lead_id no existe en leads.csv (IDs fuera del rango LD-00001..LD-01501). |
| C02 | conversaciones | lead_id | duplicados | Requiere regla de negocio | 25 | lead_id con más de una conversación. No es posible decidir sin regla si son sesiones distintas o duplicados. |
| C03 | leads | lead_id | cobertura | Debe conservarse como dato original | 861 | Leads sin conversación asociada. Coherente con que solo WhatsApp tiene transcripción. |
| H01 | historico_cierres | horas_al_primer_contacto | data_leakage | Requiere regla de negocio | 179 | Nulo exactamente cuando desenlace='Sin gestión'. Usar o imputar esta variable fuga la etiqueta. |
| H02 | historico_cierres | numero_contactos | data_leakage | Requiere regla de negocio | 179 | Valor 0 exactamente cuando desenlace='Sin gestión'. Se comporta como consecuencia del desenlace. |
| H03 | historico_cierres | desenlace | desbalance_clases | Debe conservarse como dato original | 197 | Clase minoritaria 'Cerrado' = 197 de 2200 (8.95%). |
| K01 | catalogo_motos / historico_cierres | modelo_cotizado / marca+linea | consistencia | Debe conservarse como dato original | 0 | No se detectaron modelos de histórico fuera del catálogo (marca + línea). |
| K02 | catalogo_motos / historico_cierres | precio_lista | consistencia | Debe conservarse como dato original | 0 | No se detectaron precios del histórico distintos del precio de catálogo. |
| A01 | asesores | activo | estado | Debe conservarse como dato original | 2 | Asesores inactivos; todos los puntos de venta conservan al menos un asesor activo. |
| A02 | asesores | punto_venta_id / empresa_id | referencias | Debe conservarse como dato original | 0 | No se detectaron referencias inválidas ni combinaciones empresa/punto de venta incoherentes. |

Resumen por clasificación:

| Clasificación | N.º de hallazgos |
| --- | --- |
| Corregible automáticamente | 8 |
| Requiere regla de negocio | 13 |
| Requiere revisión humana | 5 |
| Debe conservarse como dato original | 9 |

## 9. Confirmación de no modificación de originales

El script `scripts/run_audit.py` abre los archivos en modo lectura (`r`/`rb`) y solo escribe en `docs/` y `reports/`.
Los hashes SHA-256 de la sección 0 permiten comprobar que `data/` quedó intacto tras ejecutar la auditoría.

## 10. Decisiones que necesitamos tomar antes de implementar

1. **Fechas ambiguas DD/MM vs MM/DD**: `leads.csv` mezcla formatos y tiene fechas con barra donde día y mes son ambos <= 12 (ver §2.4). ¿Cuál es el formato canónico? ¿Se descartan, se corrigen con una regla o se pide la fuente original?
2. **Duplicados y entidad cliente**: hay filas idénticas, teléfonos compartidos por más de un lead y emails repetidos (ver §2.1). ¿La unidad de análisis es el `lead_id`, la persona o la conversación? ¿Se fusionan o se mantienen?
3. **Unión `leads` ↔ `historico_cierres`**: la intersección de `lead_id` es cero (prefijos LD- vs HX-). ¿Se modelan como datasets independientes o se necesita una llave alternativa (teléfono/email/nombre+ciudad) y con qué tolerancia de error?
4. **Variable objetivo del histórico**: `desenlace` tiene 3 clases muy desbalanceadas (ver §5). ¿Se binariza `Cerrado` vs resto? ¿Se excluye `Sin gestión`? ¿Es un problema de clasificación de cierre o de priorización?
5. **Data leakage**: confirmar el momento de captura de `horas_al_primer_contacto`, `numero_contactos`, `pidio_cita`, `manifesto_cuota_inicial` y `forma_pago_declarada`. ¿Se excluyen del modelado o solo las dos primeras?
6. **Normalización de modelos**: parte de los leads menciona solo la marca o nombres parciales/ambiguos (ver §2.6). ¿Qué regla se aplica: descartar, pedir a negocio o asignar el modelo más probable del catálogo?
7. **Política de valores faltantes**: email, campaña, `fecha_primer_contacto`, ciudad y modelo tienen faltantes relevantes (ver §1, §2.3, §2.5). ¿Imputar, marcar como categoría o excluir del entrenamiento?
8. **Conversaciones sin match**: 12 conversaciones apuntan a `lead_id` inexistentes (bloque LD-9xxxx del 2026-08-15). ¿Se descartan, se corrigen o se revisan manualmente?
9. **Múltiples conversaciones por lead**: 25 `lead_id` tienen 2 conversaciones. ¿Son sesiones legítimas o duplicados? ¿Se concatenan o se elige una?
10. **Definición de priorización**: no está definido qué significa priorizar ni el horizonte temporal. ¿Score de probabilidad de cierre, orden de contacto, asignación a asesores?
11. **Asignación a asesores**: `leads.csv` no tiene `asesor_id`. ¿Cómo se asigna cada lead a un asesor y cómo entra `capacidad_diaria_leads` como restricción?
12. **Vigencia del catálogo**: `catalogo_motos.csv` parece un snapshot sin fecha. ¿El `precio_lista` y `unidades_disponibles` son vigentes y por SKU global o por punto de venta?
13. **Alcance de canales para NLP**: solo WhatsApp tiene transcriptciones. ¿El análisis de conversaciones se limita a WhatsApp o se espera cubrir los otros canales?
14. **Segmentación por empresa**: ¿el modelo debe ser único o entrenar/evaluar por separado para EMP-01, EMP-02 y EMP-03?
15. **Qué se considera éxito de la solución**: ¿métrica, umbral y comparación contra un baseline? ¿Existe una línea base de gestión actual?

## 11. Supuestos que NO pueden confirmarse solo con los datos

- Si los `lead_id` duplicados son errores de captura o re-registros de la misma persona.
- Si teléfonos/emails compartidos pertenecen a la misma persona, a un familiar o a un error; tampoco si un mismo cliente puede generar varios leads.
- La zona horaria y el origen real de los formatos de fecha (por qué aparecen MM/DD y DD/MM mezclados).
- El momento exacto de captura de las variables del histórico; por eso la clasificación de leakage es una hipótesis, no un hecho probado con los datos.
- Si `Sin gestión` es un desenlace definitivo o un estado pendiente sin actualizar.
- Si dos conversaciones del mismo `lead_id` son sesiones distintas o duplicados de ingesta.
- Si `unidades_disponibles` es inventario global del SKU o por punto de venta, y si el catálogo tiene fecha de vigencia.
- Si `email` y `campania` son obligatorios por canal; su ausencia podría ser estructural y no un defecto de calidad.
- Las reglas de negocio de priorización, SLA de contacto y criterios de cierre de la empresa.
- Si los datos sintéticos preservan las distribuciones y el comportamiento real de los clientes, asesores y mercados.
- Qué canales generan leads efectivamente (una parte importante de leads no tiene conversación, pero no sabemos si eso implica ausencia de interacción).

