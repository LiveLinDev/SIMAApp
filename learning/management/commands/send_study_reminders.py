from django.core.management.base import BaseCommand

from learning.reminders import send_reminders


class Command(BaseCommand):
    help = "Envia recordatorios de estudio por correo a quienes los activaron y no han estudiado hoy."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Solo muestra a quien se enviaria, sin enviar.")

    def handle(self, *args, **options):
        reminders = send_reminders(dry_run=options["dry_run"])
        verb = "Se enviarian" if options["dry_run"] else "Enviados"
        self.stdout.write(f"{verb} {len(reminders)} recordatorios.")
        for r in reminders:
            self.stdout.write(f"  - {r.user.email}: {r.subject}")
