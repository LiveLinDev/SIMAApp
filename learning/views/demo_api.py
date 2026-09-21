"""
API de demostración para la página mini-format.pmoluna.com/sima/: procesa una clase real en SIMA (DeepSeek,
lector mini-format) y devuelve el avance y los resultados para mostrarlos en vivo.

Activa por defecto; SIMA_DEMO_API=0 la apaga. La clave del modelo nunca sale de SIMA: la página envía el texto
de la clase y recibe resultados. Solo se aceptan peticiones del sitio de mini-format (CORS y comprobación del
encabezado Origin) con cuerpo JSON, una clase a la vez y como máximo SIMA_DEMO_API_DIARIO clases por día
(30 por defecto), para acotar el gasto del proveedor.

  GET  /api/mini/estado/          SIMA disponible, modelo y lector activos
  POST /api/mini/clase/           {"titulo", "texto"} -> {"id"}
  GET  /api/mini/clase/<id>/      estado, registro del proceso, lectura_trace y preguntas generadas
"""
from __future__ import annotations

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..job_queue import enqueue_lesson_job
from ..models import Course, LessonJob, Profile
from ..services import lectura_mini

ORIGENES = {"https://mini-format.pmoluna.com", "http://localhost:4321", "http://127.0.0.1:4321"}
MAX_CARACTERES = 150_000
EN_CURSO = (LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING)


def _habilitada() -> bool:
    return os.environ.get("SIMA_DEMO_API", "1").strip() != "0"


def _limite_diario() -> int:
    try:
        return max(0, int(os.environ.get("SIMA_DEMO_API_DIARIO", "30")))
    except ValueError:
        return 30


def _cors(request, respuesta):
    origen = request.headers.get("Origin", "")
    if origen in ORIGENES:
        respuesta["Access-Control-Allow-Origin"] = origen
        respuesta["Vary"] = "Origin"
        respuesta["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        respuesta["Access-Control-Allow-Headers"] = "Content-Type"
        # acceso desde un sitio público a un servidor local (Private Network Access)
        respuesta["Access-Control-Allow-Private-Network"] = "true"
        respuesta["Access-Control-Max-Age"] = "600"
    return respuesta


def _api(vista):
    @csrf_exempt
    def envoltura(request, *args, **kwargs):
        if not _habilitada():
            raise Http404
        if request.method == "OPTIONS":
            return _cors(request, JsonResponse({}, status=204))
        origen = request.headers.get("Origin", "")
        if request.method == "POST" and (origen not in ORIGENES or request.content_type != "application/json"):
            return _cors(request, JsonResponse({"error": "origen no permitido"}, status=403))
        return _cors(request, vista(request, *args, **kwargs))
    return envoltura


def _usuario_demo():
    usuario, _ = get_user_model().objects.get_or_create(username="demo")
    perfil, _ = Profile.objects.get_or_create(user=usuario)
    if perfil.plan != "unlimited":
        perfil.plan = "unlimited"
        perfil.save(update_fields=["plan"])
    curso, _ = Course.objects.get_or_create(user=usuario, name="Biología celular")
    return usuario, curso


@_api
def estado(request):
    return JsonResponse({
        "sima": True,
        "lector": lectura_mini.lector_activo(),
        "proveedor": getattr(settings, "CLOUD_LABEL", ""),
        "modelo": getattr(settings, "CLOUD_MODEL", ""),
        "limite_salida": getattr(settings, "CLOUD_MAX_TOKENS", 0),
        "max_caracteres": MAX_CARACTERES,
    })


@_api
def crear_clase(request):
    if request.method != "POST":
        return JsonResponse({"error": "usa POST"}, status=405)
    try:
        datos = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)
    texto = str(datos.get("texto", "")).strip()
    titulo = str(datos.get("titulo", "")).strip()[:140] or "Clase desde mini-format"
    if len(texto.split()) < 150:
        return JsonResponse({"error": "la clase necesita al menos 150 palabras"}, status=400)
    if len(texto) > MAX_CARACTERES:
        return JsonResponse({"error": f"la clase supera {MAX_CARACTERES} caracteres"}, status=400)
    usuario, curso = _usuario_demo()
    activa = LessonJob.objects.filter(user=usuario, status__in=EN_CURSO).order_by("-id").first()
    if activa:
        return JsonResponse({"error": "ya hay una clase en proceso", "id": activa.pk}, status=409)
    hoy = timezone.localdate()
    if LessonJob.objects.filter(user=usuario, created_at__date=hoy).count() >= _limite_diario():
        return JsonResponse({"error": "se alcanzó el límite diario de clases de demostración"}, status=429)
    job = LessonJob.objects.create(
        user=usuario, course=curso, title=titulo, mode=LessonJob.Mode.API, source_text=texto,
        ai_backend="cloud", status=LessonJob.Status.QUEUED, processing_stage="En cola",
        processing_log="En cola - Clase recibida desde mini-format.pmoluna.com/sima/.",
    )
    enqueue_lesson_job(job.pk, backend="cloud")
    return JsonResponse({"id": job.pk}, status=201)


def _preguntas(job) -> list:
    banco = job.corrected_output or job.toon_output
    if not banco:
        return []
    try:
        from minifmt import parse
        return list(parse(banco, lectura_mini.contrato(), strict=False).records)
    except Exception:  # noqa: BLE001 - la vista no debe caer por un banco ilegible
        return []


@_api
def detalle_clase(request, pk: int):
    job = LessonJob.objects.filter(pk=pk, user__username="demo").first()
    if not job:
        return JsonResponse({"error": "no existe"}, status=404)
    terminado = job.status not in EN_CURSO
    fin = job.updated_at if terminado else timezone.now()
    return JsonResponse({
        "id": job.pk,
        "titulo": job.title,
        "estado": job.status,
        "terminado": terminado,
        "etapa": job.processing_stage,
        "registro": job.processing_log.splitlines()[-40:],
        "segundos": round((fin - job.created_at).total_seconds()),
        "palabras": len(job.source_text.split()),
        "lectura": job.lectura_trace or {},
        "preguntas": _preguntas(job) if terminado else [],
        "error": job.error,
    })
