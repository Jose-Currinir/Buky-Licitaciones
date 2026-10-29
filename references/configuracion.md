# Configuración privada del ticket

## Recorrido para el usuario

Explica que «ticket» es el código de acceso usado como token/API key. Entrega este enlace: https://www.chilecompra.cl/api/ → «Pide tu ticket» → aceptar condiciones e ingresar con Clave Única → completar formulario. El ticket llega al correo registrado. El usuario realiza ese acceso personalmente; no pidas Clave Única ni que pegue el ticket en el chat.

Después de identificar la empresa y elegir el espacio privado, entrega **un comando con rutas absolutas ya resueltas y correctamente entrecomilladas**. No ejecutes el diálogo sin que el usuario esté realizando la configuración: debe correr en su sesión local o en una terminal SSH interactiva. Ejemplo de forma, con marcadores que el asistente sustituye:

```bash
python3 "<SKILL_DIR>/scripts/ticket_config.py" --data-dir "<DATA_DIR>"
```

En macOS abre un diálogo nativo con entrada oculta; en una sesión SSH sin diálogo se puede indicar `--terminal`. Ubuntu de escritorio intenta Tkinter si está disponible. En Linux sin `DISPLAY` ni `WAYLAND_DISPLAY`, como Ubuntu Server, selecciona automáticamente entrada oculta por terminal sin exigir una opción adicional. Tanto el modo automático como `--terminal` requieren TTY: si no existe, falla antes de pedir el ticket y explica que el usuario debe ejecutarlo en una terminal interactiva. Puede añadir `--abrir-solicitud` solo cuando haya navegador local. No incorporar el valor del ticket al comando, argumentos, URL, historial de shell ni mensajes. El diálogo o `getpass` recibe la credencial directamente del usuario.

El archivo queda en `<DATA_DIR>/.env`, compartido por las empresas de ese usuario en ese espacio, no dentro de la instalación. Se escribe de forma atómica, con permisos 0600 en sistemas POSIX, sin borrar otras variables. Windows depende además de los permisos de la cuenta/carpeta. Al cancelar no cambia un ticket previo. El archivo es texto local: no afirmar cifrado ni subirlo a Git o exportaciones.

## Usar la credencial sin mostrarla

```bash
python3 "<SKILL_DIR>/scripts/ticket_config.py" --data-dir "<DATA_DIR>" --estado
python3 "<SKILL_DIR>/scripts/mercado_publico.py" proveedor --rut "<RUT>" --env-file "<DATA_DIR>/.env" --out "<DATA_DIR>/consultas/identidad.json"
```

--estado comprueba configuración local, **no** autenticación. La primera consulta API real comprueba acceso; registrar solo resultado/código, fecha y recurso. No leer .env con herramientas que impriman su contenido ni copiarlo al contexto del asistente. El cliente lo carga internamente. La variable MERCADO_PUBLICO_TICKET del entorno prevalece sobre --env-file; si hay discrepancia, explica esa prioridad sin mostrar valores. No se ejecuta .env como script ni se interpretan expansiones shell.

## Cambios y errores

401/403 requieren revisar vigencia/permisos del ticket; ofrecer repetir el comando para reemplazarlo. 429 requiere respetar cuota, no rotar tickets para eludirla. Cancelar o no tener ticket permite continuar con datos aportados/fuentes públicas y marcar limitaciones. No modificar archivos de configuración global del asistente.

El ticket queda excluido de revisiones, manifiestos y respaldos autocontenidos. Un respaldo de credenciales se gestiona separadamente por el usuario; al restaurar un expediente, configurar ticket de nuevo.
