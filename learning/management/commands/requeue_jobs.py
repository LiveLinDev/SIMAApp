from django.core.management.base import BaseCommand

from learning.job_queue import requeue_orphaned_jobs
from learning.models import LessonJob


class Command(BaseCommand):
    help = "Reencola los trabajos que quedaron en QUEUED o PROCESSING sin worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo lista los trabajos huerfanos, sin reencolarlos.",
        )

    def handle(self, *args, **options):
        pending = LessonJob.objects.filter(
            status__in=[LessonJob.Status.QUEUED, LessonJob.Status.PROCESSING]
        ).order_by("created_at")
        if not pending.exists():
            self.stdout.write("No hay trabajos pendientes.")
            return
        for job in pending:
            self.stdout.write(f"  #{job.pk}  {job.status:<11} {job.ai_backend:<10} {job.title}")
        if options["dry_run"]:
            self.stdout.write(f"{pending.count()} trabajo(s) pendiente(s); no se reencolaron (--dry-run).")
            return
        count = requeue_orphaned_jobs(reason="reencolado manual")
        self.stdout.write(self.style.SUCCESS(f"Reencolados {count} trabajo(s)."))
