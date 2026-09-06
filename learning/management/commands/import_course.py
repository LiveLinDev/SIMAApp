import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from learning.models import Question
from learning.portability import import_course


class Command(BaseCommand):
    help = "Importa un curso exportado con export_course para un usuario; reconstruye el banco de preguntas."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--user", required=True, help="Nombre de usuario dueno del curso importado.")
        parser.add_argument("--name", help="Nombre para el curso importado (por defecto el original).")
        parser.add_argument("--no-bank", action="store_true", help="No reconstruir el banco de preguntas.")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"No existe {path}.")
        try:
            user = User.objects.get(username=options["user"])
        except User.DoesNotExist as exc:
            raise CommandError(f"No existe el usuario {options['user']!r}.") from exc
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            course = import_course(user, payload, name=options["name"], sync_bank=not options["no_bank"])
        except (ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        bank = Question.objects.filter(quiz__course=course).count()
        self.stdout.write(self.style.SUCCESS(
            f"Importado «{course.name}» (id {course.pk}) para {user.username}: "
            f"{course.legacy_lesson_jobs.count()} clases, {bank} preguntas en el banco."
        ))
