# Perfiles: alta, directorio y conocimiento continuo

## Primera interacción

1. Consultar el directorio local con `buky.py perfiles`. Si existe un perfil, retomarlo sin repetir el alta; si hay varios, confirmar cuál atender. El tipo `empresa` y `persona_natural` conviven sin compartir datos.
2. Si no existe ninguno, preguntar primero «¿Quieres trabajar como empresa o como persona natural?». Después pedir el RUT correspondiente y validar módulo 11. Un RUT válido matemáticamente no prueba existencia, identidad, inicio de actividades, habilidad ni representación.
3. Para una empresa, investigar razón social y nombre comercial. Para una persona natural, confirmar su nombre legal; no inventar una razón social ni exigir inicio de actividades para explorar. Preguntar si tiene inicio cuando sea relevante para ofertar y guardar `true`, `false` o `null` solo según respuesta/evidencia.
4. Consultar BuscarProveedor si hay ticket y registrar código de proveedor e identidad encontrada. Si no hay ticket, continuar con fuentes públicas oficiales y documentos aportados, dejando la consulta API pendiente. No volver a pedir un ticket configurado ni pedir su valor en el chat.
5. Cruzar RUT e identidad con fuentes disponibles y documentos aportados. Presentar la coincidencia y pedir confirmación breve antes de enlazar antecedentes. Homónimos o falta de resultados requieren aclaración; nunca crear una identidad ficticia.
6. Inicializar el tipo correcto mediante `buky.py perfil crear` o `base_empresa.py init`. Guardar la confirmación como hecho `identidad_confirmada` con fuente «usuario» y fecha. Unificar consultas posteriores por RUT, nunca por nombre solamente.

## Directorio y cambio de perfil

```bash
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json perfiles
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json perfil crear --rut "<RUT>" --tipo empresa
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json perfil crear --rut "<RUT>" --tipo persona_natural
python3 "<SKILL_DIR>/scripts/buky.py" --data-dir "<DATA_DIR>" --json perfil actualizar --rut "<RUT>" --nombre "<NOMBRE_CONFIRMADO>" --inicio-actividades
```

No agregar `--inicio-actividades` ni `--no-inicio-actividades` hasta que el usuario lo confirme. Sin esa opción, el estado queda desconocido. El comando de actualización también acepta `--no-inicio-actividades`; toda modificación conserva una revisión.

## Investigación inicial

Producir un perfil preliminar con identidad, nombre comercial si existe, sitios oficiales, actividad declarada y observada, productos/servicios, cobertura geográfica y ventas públicas verificadas. Separar lo declarado de lo que los contratos demuestran. Un giro amplio no implica capacidad para cualquier contrato.

Buscar primero en Mercado Público/Datos Abiertos, sitios oficiales y documentos aportados. Para antecedentes tributarios, registro, EMT o representación usar fuentes oficiales disponibles y documentos vigentes; no afirmar habilidad, ventas privadas o beneficiarios finales si la fuente no los acredita. No sortear login ni CAPTCHA; pedir el documento pertinente cuando sea necesario.

Transformar lo descubierto en catálogo: familias, sinónimos, términos técnicos, códigos verificados, exclusiones y ejemplos. Validarlo mediante unas pocas oportunidades de muestra y correcciones del usuario; no tomar una palabra común como señal suficiente de afinidad.

## Nutrir la base

Guardar cada afirmación con fuente/enlace o archivo, ubicación, fecha de consulta, estado (documentado / declarado / inferido / pendiente) y vigencia si procede. Los datos inferidos quedan separados de los confirmados y no acreditan requisitos. Conservar hechos contradictorios hasta resolverlos.

Preguntar progresivamente por productos realmente ofrecidos, capacidad, stock/plazos, zonas, certificaciones, equipo, experiencia, capital de trabajo y preferencias. No hacer un formulario extenso antes de aportar resultados ni pedir contraseñas, firma electrónica o costos privados para una búsqueda inicial.

Antes de reutilizar evidencia revisar vigencia y alcance. Certificados, ofertas, CV, fichas y contratos enriquecen el perfil; conservar originales, índice y trazabilidad. No ingerir datos indiscriminadamente. Al cambiar de perfil, cambiar de base: no filtrar márgenes, documentos, recordatorios ni oportunidades entre RUT.

Salida inicial: perfil identificado, tipo y estado de inicio cuando corresponda, actividad entendida, catálogo preliminar, fuentes, lagunas y siguiente acción. Una búsqueda sin resultados significa cobertura insuficiente, no que el perfil no exista o carezca de experiencia.
