from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0008_lessonjob_audit_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="transcript_repair_prompt",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="transcript_repair_trace",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
