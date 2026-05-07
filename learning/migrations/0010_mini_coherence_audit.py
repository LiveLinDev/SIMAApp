from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0009_transcript_repair_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="mini_coherence_prompt",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="mini_coherence_trace",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
