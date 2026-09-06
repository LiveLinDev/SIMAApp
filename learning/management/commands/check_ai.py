"""
Diagnostico del proveedor de IA y del entorno antes de probar SIMA.

    python manage.py check_ai            # configuracion, BD, migraciones, paquetes
    python manage.py check_ai --ping     # + una llamada minima al proveedor
    python manage.py check_ai --mini     # + genera items .mini con un texto de muestra y valida el formato
    python manage.py check_ai --mini --file apuntes.txt --runs 3 --items 8

Sale con codigo 1 si algo bloquea la prueba (sin clave, sin conexion, formato invalido).
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from learning.job_queue import queue_mode
from learning.parse_mini import filter_incoherent_items, filter_nonuniform_items, normalize_mini_text, validate_mini_parse
from learning.services import call_ai, cloud_backend_available, extract_mini_lines, generate_items

# USD por millon de tokens (entrada, salida) a septiembre de 2026; solo para estimar.
PRICES = {
    "qwen": (0.14, 0.42), "deepseek": (0.22, 0.66), "openai": (0.05, 0.40), "gemini": (0.25, 1.50),
    "groq": (0.15, 0.60), "mistral": (0.15, 0.60), "anthropic": (1.00, 5.00),
}

SAMPLE_TEXT = """
Clase de biologia celular: energia en la celula. Hoy vamos a ver como obtiene energia una celula y por que
la fotosintesis y la respiracion celular son procesos complementarios. La fotosintesis ocurre en los
cloroplastos de las celulas vegetales. En la membrana de los tilacoides, la clorofila capta la luz y esa
energia se usa para romper moleculas de agua; se libera oxigeno como producto y se forman ATP y NADPH.
Luego, en el estroma, el ciclo de Calvin usa ese ATP y ese NADPH para fijar dioxido de carbono y producir
glucosa. La ecuacion general es: seis moleculas de dioxido de carbono mas seis de agua, con luz, dan una
glucosa y seis oxigenos.

La respiracion celular hace el camino inverso y ocurre en tres etapas. La glucolisis sucede en el citoplasma:
una glucosa se parte en dos piruvatos y se obtienen dos ATP netos; no necesita oxigeno. El ciclo de Krebs
ocurre en la matriz de la mitocondria: el piruvato se convierte en acetil-CoA, se libera dioxido de carbono
y se cargan transportadores de electrones, NADH y FADH2. Finalmente, la cadena de transporte de electrones,
en la membrana interna de la mitocondria, usa esos transportadores para bombear protones y la ATP sintasa
produce la mayor parte del ATP; el oxigeno es el aceptor final de electrones y se forma agua. Por eso, sin
oxigeno, la celula recurre a la fermentacion, que regenera NAD+ pero rinde solo los dos ATP de la glucolisis.
En el musculo se produce fermentacion lactica; en las levaduras, fermentacion alcoholica.

Para el examen: ubiquen cada etapa en su lugar de la celula, recuerden quien es el aceptor final de electrones
y comparen el rendimiento de ATP con y sin oxigeno.
"""


class Command(BaseCommand):
    help = "Comprueba la configuracion de IA y el entorno; con --ping y --mini prueba el proveedor de verdad."

    def add_arguments(self, parser):
        parser.add_argument("--ping", action="store_true", help="Hace una llamada minima al proveedor de nube.")
        parser.add_argument("--mini", action="store_true", help="Genera items .mini con un texto de muestra y valida el formato.")
        parser.add_argument("--file", help="Texto de clase a usar con --mini (por defecto una muestra de biologia).")
        parser.add_argument("--items", type=int, default=6, help="Items a pedir con --mini (default 6).")
        parser.add_argument("--runs", type=int, default=1, help="Repeticiones de --mini para medir cuantas veces respeta el formato.")
        parser.add_argument("--model", help="Probar otro modelo del mismo proveedor sin tocar .env (p. ej. llama-3.3-70b-versatile).")

    # ------------------------------------------------------------------ util
    def ok(self, text):
        self.stdout.write(self.style.SUCCESS(f"  [OK] {text}"))

    def warn(self, text):
        self.stdout.write(self.style.WARNING(f"  [!!] {text}"))

    def fail(self, text):
        self.stdout.write(self.style.ERROR(f"  [XX] {text}"))
        self.failed = True

    @staticmethod
    def _mask(key: str) -> str:
        return f"{key[:4]}...{key[-3:]} ({len(key)} caracteres)" if key and len(key) > 8 else ("(vacia)" if not key else "***")

    # ------------------------------------------------------------------ pasos
    def handle(self, *args, **options):
        self.failed = False
        if options.get("model"):
            settings.CLOUD_MODEL = options["model"]  # solo en este proceso
        provider = getattr(settings, "CLOUD_PROVIDER", "")
        self.stdout.write("Configuracion de IA")
        self.stdout.write(f"  proveedor     : {provider} ({getattr(settings, 'CLOUD_LABEL', '')})")
        self.stdout.write(f"  modelo        : {getattr(settings, 'CLOUD_MODEL', '')}")
        self.stdout.write(f"  endpoint      : {getattr(settings, 'CLOUD_API_BASE', '') or '(SDK nativo)'}")
        self.stdout.write(f"  clave         : {self._mask(getattr(settings, 'CLOUD_API_KEY', ''))}")
        self.stdout.write(f"  MINI directo  : {getattr(settings, 'CLOUD_DIRECT_MINI', False)} (False = con verificacion factual)")
        self.stdout.write(f"  verificacion  : {getattr(settings, 'VERIFICATION_DEFAULT_MODE', 'web')}")
        self.stdout.write(f"  max_tokens    : {getattr(settings, 'CLOUD_MAX_TOKENS', 0)} - timeout {getattr(settings, 'CLOUD_API_TIMEOUT', 0)} s")
        self.stdout.write(f"  Whisper       : {getattr(settings, 'WHISPER_MODEL', '')} - cola {queue_mode()} - DEBUG {settings.DEBUG}")
        self.stdout.write("")
        self.stdout.write("Entorno")
        if cloud_backend_available():
            self.ok("hay una clave real de nube configurada")
        else:
            self.fail("CLOUD_API_KEY no tiene una clave real: la nube no esta disponible")
        for package, why in (("openai", "proveedores compatibles con OpenAI"), ("whisper", "transcripcion de audio"), ("psycopg", "PostgreSQL")):
            if importlib.util.find_spec(package):
                self.ok(f"paquete {package} instalado ({why})")
            elif package == "openai" and provider != "anthropic":
                self.fail(f"falta el paquete {package}: pip install -r requirements.txt")
            else:
                self.warn(f"falta el paquete {package} ({why})")
        try:
            connection.ensure_connection()
            self.ok(f"base de datos conectada ({connection.settings_dict.get('NAME')})")
            plan = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
            if plan:
                self.fail(f"{len(plan)} migracion(es) sin aplicar: python manage.py migrate")
            else:
                self.ok("migraciones al dia")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"base de datos: {exc.__class__.__name__}: {exc}")

        if options["ping"] and not self.failed:
            self.stdout.write("")
            self.stdout.write("Ping al proveedor")
            started = time.monotonic()
            try:
                reply = call_ai("Responde exactamente con la palabra OK.", backend="cloud", role="verification")
                elapsed = time.monotonic() - started
                if reply and reply.strip():
                    self.ok(f"respondio en {elapsed:.1f} s: {reply.strip()[:60]!r}")
                else:
                    self.fail("el proveedor respondio vacio")
            except Exception as exc:  # noqa: BLE001
                self.fail(f"{exc}")

        if options["mini"] and not self.failed:
            self.stdout.write("")
            text = Path(options["file"]).read_text(encoding="utf-8") if options["file"] else SAMPLE_TEXT
            words = len(text.split())
            self.stdout.write(f"Generacion .mini de prueba ({words} palabras, {options['items']} items, {options['runs']} corrida(s))")
            good_runs = 0
            for run in range(1, max(1, options["runs"]) + 1):
                started = time.monotonic()
                try:
                    prompt, raw, backend = generate_items(text, backend="cloud", items_requested=options["items"])
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"corrida {run}: {exc}")
                    continue
                elapsed = time.monotonic() - started
                mini = extract_mini_lines(raw) or raw
                coherent, dropped, _ = filter_incoherent_items(mini)
                uniform, bad_opts, _ = filter_nonuniform_items(coherent)
                try:
                    assessment = validate_mini_parse(normalize_mini_text(uniform, stage="check_ai"), stage="check_ai")
                    parsed = len(assessment.items)
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"corrida {run}: el .mini no se pudo parsear: {exc}")
                    continue
                in_tokens, out_tokens = len(prompt) // 4, len(raw) // 4
                price = PRICES.get(provider)
                cost = f" - ~${(in_tokens * price[0] + out_tokens * price[1]) / 1e6:.4f}" if price else ""
                line = (f"corrida {run}: {parsed} items validos de {options['items']} pedidos - {len(dropped)} incoherentes - "
                        f"{len(bad_opts)} con opciones malformadas - {elapsed:.1f} s - ~{in_tokens + out_tokens} tokens{cost}")
                if parsed >= max(3, int(options["items"] * 0.6)):
                    good_runs += 1
                    self.ok(line)
                else:
                    self.warn(line)
                if run == 1 and parsed:
                    first = assessment.items[0]
                    self.stdout.write(f"     ejemplo: [{first.bloom}] {first.topic}: {first.statement[:110]}")
            if options["runs"] > 1:
                self.stdout.write(f"  formato respetado en {good_runs} de {options['runs']} corridas")
            if good_runs == 0:
                self.fail("ninguna corrida produjo un .mini utilizable: revisa el modelo o CLOUD_MAX_TOKENS")

        self.stdout.write("")
        if self.failed:
            self.stdout.write(self.style.ERROR("Hay problemas que bloquean la prueba (ver [XX])."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Todo listo para probar SIMA con este proveedor."))
