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

## Edición asistida por IA con el plugin MCP (instalado)

Archi tiene instalado el plugin **ArchiMate MCP Server** v1.8.0 (`fanievh/archi-mcp-server`, licencia MIT) en
`D:\tools\Archi\dropins`. Expone el modelo abierto en Archi por HTTP local (`http://127.0.0.1:18090/mcp`,
solo loopback) con 69 herramientas: consultar, crear, anidar, ruteo ortogonal con evasión de obstáculos,
evaluación objetiva de la disposición (`assess-layout`) y exportación a PNG/SVG.

Uso:

1. Abrir el modelo en Archi y, en la barra de menú, **MCP Server → Start MCP Server**.
2. **Approval Mode** (mismo menú) decide si cada cambio del asistente queda en cola para aprobarlo en la vista
   *Pending Approvals* o se aplica directo. Es un control del humano: el asistente no puede cambiarlo.
3. Claude Code lo encuentra por el `.mcp.json` del repo (`archi` → `http://127.0.0.1:18090/mcp`).
4. El plugin **no guarda el modelo**: tras una sesión hay que guardar en Archi (Ctrl+S).

Flujo aplicado el 7-sep-2026 sobre copias de las vistas (las originales del script se conservan):

| Vista | Original | Con ruteo MCP | Qué se hizo |
|---|---|---|---|
| 2b. Negocio | pobre (14 terminales diagonales) | aceptable | `auto-route-connections` con `autoNudge` |
| 3b. Aplicación | pobre (15 terminales, 10 cruces por cajas) | aceptable | ídem |
| 4b. Tecnología | pobre (hub con 8 asignaciones) | disposición excelente | software y artefactos **anidados** dentro del nodo `Servidor de SIMA` (la contención reemplaza las asignaciones nodo→parte, como recomienda el ArchiMate Cookbook), `auto-connect-view` sin Assignment/Composition, ruteo |
| 5b. Capas | pobre (9 terminales diagonales) | buena | ruteo |

El modo `auto-layout-and-route` (ELK) se probó y se descartó: mejora las métricas pero reordena los grupos y
rompe la convención de capas (negocio arriba, tecnología abajo). Las imágenes con ruteo están en
`docs/img/archimate/mcp/`. Ojo: `build_model.py` regenera el archivo completo, así que las vistas "b" se pierden
al regenerar; lo que persiste son los PNG y este procedimiento.
