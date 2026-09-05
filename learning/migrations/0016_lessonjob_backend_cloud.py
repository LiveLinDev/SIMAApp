from django.db import migrations


def anthropic_to_cloud(apps, schema_editor):
    LessonJob = apps.get_model("learning", "LessonJob")
    LessonJob.objects.filter(ai_backend__in=["anthropic", "deepseek", "claude"]).update(ai_backend="cloud")


def cloud_to_anthropic(apps, schema_editor):
    LessonJob = apps.get_model("learning", "LessonJob")
    LessonJob.objects.filter(ai_backend="cloud").update(ai_backend="anthropic")


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0015_remove_profile_daily_goal_userpreference"),
    ]

    operations = [
        migrations.RunPython(anthropic_to_cloud, cloud_to_anthropic),
    ]
