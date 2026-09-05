import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from learning.job_queue import claim_next_job, process_claimed, queue_mode, reset_stale_processing


class Command(BaseCommand):
    help = (
        "Worker de trabajos fuera del proceso web (SIMA_QUEUE_MODE=db): reclama en la base de datos "
        "los LessonJob, ReinforcementJob y SummaryJob en cola y los procesa uno a uno."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Procesa lo que haya en cola y termina (util para el Programador de tareas).")
        parser.add_argument("--interval", type=float, default=3.0, help="Segundos entre sondeos cuando la cola esta vacia (default 3).")
        parser.add_argument("--max-jobs", type=int, default=0, help="Termina tras procesar N trabajos (0 = sin limite).")
        parser.add_argument("--stale-minutes", type=int, default=120, help="Trabajos en PROCESSING sin actividad por mas de N minutos vuelven a la cola (default 120).")
        parser.add_argument("--force", action="store_true", help="Correr aunque SIMA_QUEUE_MODE no sea 'db' (riesgo de procesar dos veces).")

    def handle(self, *args, **options):
        if queue_mode() != "db" and not options["force"]:
            raise CommandError(
                "SIMA_QUEUE_MODE=%r: el proceso web ya tiene su propio worker en memoria. "
                "Pon SIMA_QUEUE_MODE=db en .env (y reinicia el web) o usa --force." % queue_mode()
            )
        stale = reset_stale_processing(options["stale_minutes"])
        if stale:
            self.stdout.write(f"{stale} trabajo(s) atascados en PROCESSING volvieron a la cola.")
        self.stdout.write(f"Worker listo (modo {queue_mode()}, backend por defecto {getattr(settings, 'CLOUD_MODEL', '')}). Ctrl+C para salir.")
        processed = 0
        try:
            while True:
                claimed = claim_next_job()
                if claimed is None:
                    if options["once"]:
                        break
                    time.sleep(max(0.5, options["interval"]))
                    continue
                kind, job_id, backend = claimed
                self.stdout.write(f"-> {kind} #{job_id} ({backend})")
                started = time.monotonic()
                process_claimed(kind, job_id, backend)
                processed += 1
                self.stdout.write(f"   listo en {time.monotonic() - started:.1f}s")
                if options["max_jobs"] and processed >= options["max_jobs"]:
                    break
        except KeyboardInterrupt:
            self.stdout.write("Worker detenido.")
        self.stdout.write(self.style.SUCCESS(f"Procesados {processed} trabajo(s)."))
