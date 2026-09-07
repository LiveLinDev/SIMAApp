#!/usr/bin/env bash
# Regenera el modelo (modo --merge: conserva las vistas editadas en Archi), lo valida con la linea de comandos de
# Archi y copia los PNG de las vistas a docs/img/archimate/. Uso: bash docs/archimate/render_views.sh
set -e
ARCHI="${ARCHI:-D:/tools/Archi}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
REPORT="$REPO/docs/archimate/report_tmp"
PYTHONIOENCODING=utf-8 python "$REPO/docs/archimate/build_model.py" --merge
rm -rf "$REPORT"
LAUNCHER=$(ls "$ARCHI"/plugins/org.eclipse.equinox.launcher_*.jar | head -1)
(cd "$ARCHI" && ./jre/bin/java.exe -cp "$LAUNCHER" org.eclipse.equinox.launcher.Main -application com.archimatetool.commandline.app \
  -consoleLog -nosplash -data "${ARCHI}-data" --loadModel "$REPO/docs/archimate/SIMA.archimate" --html.createReport "$REPORT" 2>&1 \
  | grep -iE "Loaded model|Report generated|Exception|Caused")
IMG=$(ls -d "$REPORT"/*/images | head -1)
PYTHONIOENCODING=utf-8 python - "$IMG" "$REPO/docs/img/archimate" <<'EOF'
import os, re, sys, shutil, unicodedata
img, out = sys.argv[1], sys.argv[2]
model = open(os.path.join(img, "..", "..", "..", "SIMA.archimate"), encoding="utf-8").read()
for name, vid in re.findall(r'ArchimateDiagramModel" name="([^"]+)" id="([^"]+)"', model):
    src = os.path.join(img, vid + ".png")
    if not os.path.exists(src):
        continue
    slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    shutil.copy(src, os.path.join(out, slug + ".png"))
    print("->", slug + ".png")
EOF
rm -rf "$REPORT"
