# Mecanismos de compra, garantías y habilitación

Resumen operativo del Reglamento de la Ley 19.886 (Decreto 661 de Hacienda, 2024), según el texto de la Biblioteca del Congreso generado el 2025-02-26 y revisado el 2026-10-30. Antes de una afirmación que decida una oferta, verifica el artículo vigente y las bases del proceso: **las bases y sus modificaciones mandan dentro del marco legal**. Los montos en UTM se convierten con el valor oficial del mes que corresponda (ver [fuentes.md](fuentes.md)).

## Qué hace la skill con cada mecanismo

| Mecanismo | Quién puede ofertar | Qué hace Buky |
| --- | --- | --- |
| **Compra Ágil** (≤ 100 UTM, art. 97) | Por regla general, empresas de menor tamaño y proveedores locales. Si ninguna cotiza, la entidad puede abrirla al resto | Sincroniza (API v2), evalúa y recuerda cierres |
| **Licitación pública** (art. 46 y siguientes) | Cualquier proveedor que cumpla las bases | Consulta por código o fecha (API v1), evalúa y recuerda cierres |
| **Licitación privada** (art. 64–69) | Solo los proveedores invitados; procede de forma excepcional | No se sincroniza: evalúa si el usuario aporta la invitación y las bases |
| **Trato directo** (art. 71–77) | El proveedor elegido por una causal fundada (único proveedor, sin interesados, emergencia, confidencialidad, entre otras) | No es una oportunidad abierta: solo orienta si el usuario ya fue contactado |
| **Convenio Marco** (art. 85–96) | Proveedores adjudicados en el convenio; compras sobre 1.000 UTM son **Grandes Compras** y se comunican a todos los adjudicados de la categoría (art. 90) | No sincroniza la tienda ni Grandes Compras; orienta y evalúa con los antecedentes aportados |
| **Compra por cotización** (art. 99–100) | Al menos tres cotizaciones en casos tasados | Igual que la licitación privada |

Si el usuario pregunta por un mecanismo que no se sincroniza, dilo y trabaja con lo que aporte; no lo presentes como una oportunidad abierta.

## Plazos mínimos de publicación en licitación pública (art. 46)

| Monto de la contratación | Plazo mínimo entre llamado y cierre |
| --- | --- |
| ≥ 5.000 UTM | 30 días corridos |
| ≥ 1.000 y < 5.000 UTM | 20 días corridos (hasta 10 si es de simple y objetiva especificación) |
| ≥ 100 y < 1.000 UTM | 10 días corridos (hasta 5 si es simple) |
| < 100 UTM | 5 días corridos |

El cierre no puede vencer en día inhábil, en lunes ni en el día siguiente a un inhábil antes de las 15:00. Si la ficha muestra un plazo menor, márcalo para verificar en vez de asumir un error.

## Garantías

- **Seriedad de la oferta (art. 52)**: excepcional, por interés público y solo en licitaciones **superiores a 5.000 UTM**, hasta el **3 %** del monto de la licitación. Debe ser pagadera a la vista, irrevocable y a primer requerimiento, y las bases no pueden restringir el tipo de instrumento. Si una licitación menor la exige, adviértelo como posible irregularidad y no la des por válida ni inválida sin revisar.
- **Fiel y oportuno cumplimiento (art. 121)**: obligatoria en contrataciones **superiores a 1.000 UTM**, por el **5 %** del precio final neto ofertado, salvo ofertas temerarias, contrataciones riesgosas o normas especiales. Bajo ese monto la entidad puede exigirla fundadamente por riesgo. En servicios cubre además obligaciones laborales y previsionales, y sigue vigente hasta 60 días hábiles después de terminado el contrato.
- Puede otorgarse con uno o varios instrumentos financieros de la misma naturaleza, en forma física o electrónica (boleta de garantía, vale vista, póliza o certificado de fianza, según acepten las bases).

Registra cada garantía exigida como requisito con `requisito agregar` e incluye su costo financiero en `costos`.

## Habilitación del proveedor

- Para contratar, el proveedor acredita su situación financiera y técnica con la **inscripción en el Registro de Proveedores**, y la entidad debe contratar con proveedores **hábiles** (art. 120). Distingue estar inscrito de estar hábil y verifica la fecha de la consulta.
- Un mismo oferente no puede ofertar en el mismo proceso de forma individual y además a través de una **Unión Temporal de Proveedores** (art. 48).
- **Empresa de menor tamaño** es la definida en el artículo segundo de la Ley 20.416; **proveedor local** es una empresa de menor tamaño con domicilio principal (el registrado en el SII) en la región de entrega (art. 4, números 14 y 25). Ambas condiciones dan preferencia en Compra Ágil: confírmalas con evidencia antes de usarlas en la evaluación. `giros` obtiene del SII el tramo de ventas (tramos 2 a 9 = micro, pequeña o mediana; 10 a 13 = gran empresa; 1 = sin información) y el domicilio; el tramo corresponde al último año comercial publicado, no al actual.
- Inhabilidades, prohibiciones y declaraciones juradas dependen de la ley y de cada proceso: revisa el texto vigente y las bases, y no presumas que el proveedor está libre de ellas.

## Límites de esta guía

No reemplaza la lectura de la ley, el reglamento, las directivas de ChileCompra ni las bases. No cubre reclamos ante el Tribunal de Contratación Pública ni contratos de obra pública con normativa propia. Ante una duda legal relevante, recomienda consultar a un abogado y cita el artículo que sustenta cada afirmación.
