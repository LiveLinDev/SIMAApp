from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0007_lessonjob_processing_log_verification_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="correction_trace",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="tags",
            field=models.CharField(blank=True, max_length=260),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="verification_trace",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
