# Modelo ArchiMate de SIMA

`SIMA.archimate` es el modelo de arquitectura empresarial de SIMA en el formato nativo de
[Archi](https://www.archimatetool.com/) (ArchiMate 3.2). Lo genera `build_model.py`, que es la fuente
de verdad: si cambia la arquitectura, se edita el script y se vuelve a generar; el archivo
`.archimate` no se edita a mano salvo para retocar la disposición de una vista.

## Contenido

| Capa | Elementos |
|---|---|
| Motivación | interesados (estudiante, docente), metas, requisitos (notación .mini, verificación, evaluación adaptativa) y el principio de transcripción local |
| Negocio | actores y rol, los seis procesos del ciclo del estudiante, el servicio de acompañamiento y los objetos de negocio |
| Aplicación | SIMA y sus componentes (vistas, núcleo adaptativo, pipeline, servicios de IA, cola y worker, refuerzo y resúmenes, créditos), cinco servicios de aplicación, interfaces, objetos de datos y los sistemas externos (proveedor de LLM, Whisper) |
| Tecnología | servidor, software de sistema, worker, dispositivo del estudiante, red, servicios tecnológicos y artefactos |

Cinco vistas con disposición calculada: motivación, negocio, aplicación, tecnología y una vista en capas.

## Abrir y exportar

1. Archi 5.10 (portable, con su propio JRE) está en `D:\tools\Archi\Archi.exe` en el equipo de Erick (instalado el 7-sep-2026 desde el
   release oficial de archimatetool.com; se puso en D: porque C: estaba sin espacio). En otro equipo: descargar el portable y descomprimir.
2. Archi → **File → Open** → `docs/archimate/SIMA.archimate`.
3. Para las imágenes de las vistas: **File → Report → HTML** (genera un sitio con cada vista en PNG) o, en cada vista,
   **File → Export → View As Image**.

Desde la línea de comandos (sin abrir la interfaz):

```bash
cd D:\tools\Archi
jre\bin\java -cp plugins\org.eclipse.equinox.launcher_1.7.100.v20251111-0406.jar org.eclipse.equinox.launcher.Main -application com.archimatetool.commandline.app -consoleLog -nosplash -data D:\tools\archi-data --loadModel D:\Tesis\SIMAApp\docs\archimate\SIMA.archimate --html.createReport D:\Tesis\SIMAApp\docs\archimate\report
```

El reporte deja un PNG por vista en `report/<id>/images/`; copias con nombre legible en `docs/img/archimate/`.
Validado el 7-sep-2026: el modelo carga sin errores y las cinco vistas se renderizan.

## Edición asistida por IA (opcional)

Existen servidores MCP para Archi que permiten que un asistente cree y modifique elementos y vistas
en el modelo abierto (por ejemplo, el plugin `archi-mcp-server` publicado en GitHub, que expone un
endpoint HTTP local). Son plugins de terceros que ejecutan código dentro de Archi: instalarlos es una
decisión del equipo. Este modelo no los necesita; se regenera con el script.
