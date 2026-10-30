# Evaluación y decisión

## Qué lee el motor

`viabilidad.py` decide con estos datos. Regístralos con los comandos de SKILL.md («Enseñarle al motor»); no edites JSON a mano.

| Dato | Comando | Efecto |
| --- | --- | --- |
| `catalogo` | `catalogo --agregar/--quitar` | Coincidencia completa: razón a favor. Parcial: pendiente de confirmar. Ninguna: ajuste bajo. |
| `exclusiones` | `catalogo --excluir/--permitir` | Coincidencia: bloqueo. |
| `regiones_atencion` | `condiciones --regiones` | Entrega fuera de esas regiones: bloqueo. Región irreconocible: pendiente. |
| `horas_preparacion` | `condiciones --horas-preparacion` | Menos horas hasta el cierre que las necesarias: bloqueo. |
| `margen_minimo` | `condiciones --margen-minimo` | Margen estimado menor: bloqueo. |
| `tamano_empresa` | `giros` (SII) o `condiciones --emt/--no-emt` | Compra Ágil en primer llamado: una gran empresa queda bloqueada; una empresa de menor tamaño suma una razón a favor. |
| `requisitos[]` de la oportunidad | `requisito agregar/marcar` | Obligatorio `no_cumple`: bloqueo. Cualquier otro estado distinto de `cumple`: pendiente. |
| `margen_estimado` de la oportunidad | `costos --costo --precio` | Se compara con el margen mínimo. |

Decisión: con un bloqueo, **no participar**; con pendientes, **participar condicionado**; sin ninguno, **participar**. Los requisitos y costos se conservan cuando una sincronización trae una observación oficial nueva.

## Matriz de cumplimiento

Usa assets/matriz-cumplimiento.csv. Extrae requisitos atómicos: no mezcles garantía, vigencia y monto en una fila si necesitan evidencias distintas. Incluye criterios de exclusión, anexos, firmas/poderes, inscripción y habilidad, experiencia demostrable, certificaciones, visitas, muestras, cobertura, plazos, garantías, multas y condiciones de pago, solo cuando apliquen al proceso.

Comprueba la condición de proveedor y tamaño de empresa con evidencia vigente. En Compra Ágil distingue primer y segundo llamado; verifica elegibilidad efectiva en la ficha y reglas vigentes. No asumas que una empresa puede participar por ser local o por tener un RUT. El umbral es de hasta 100 UTM (Decreto 661, art. 97; revisado el 2026-10-30); usa el valor oficial del período y la regla de cálculo aplicable, sin fijar una equivalencia permanente en CLP. Plazos, garantías y habilitación por mecanismo: [mecanismos.md](mecanismos.md).

Separa admisibilidad de evaluación. Transcribe fórmula y ponderaciones con página y versión. Verifica que sumen lo esperado por las bases, reglas de redondeo, desempate, mínimos y puntajes tope. Calcula escenarios solo con datos conocidos; cuando dependan de ofertas ajenas usa rangos y supuestos explícitos, no probabilidades de ganar inventadas. Si falta una fórmula no la reemplaces por un ranking propio presentado como oficial.

Prioriza oportunidades por ajuste al catálogo, factibilidad de entrega, margen y caja, esfuerzo de preparación, experiencia acreditable y riesgos contractuales. Si usas un score interno, etiqueta sus pesos como criterio comercial del usuario y mantenlo separado del puntaje oficial. Precio más bajo no implica automáticamente adjudicación.

Entrega una recomendación argumentada y trazable. Un requisito obligatorio incumplido lleva a no participar o resolverlo por una vía permitida antes de cierre; nunca a ocultarlo. Un requisito pendiente mantiene la decisión condicionada. Revisa modificaciones y foro antes de fijar la conclusión.
