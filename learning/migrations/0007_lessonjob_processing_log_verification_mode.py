from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0006_alter_lessonjob_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="processing_log",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="verification_mode",
            field=models.CharField(
                choices=[
                    ("web", "Fuentes web"),
                    ("eduqg", "EduQG local"),
                    ("hybrid", "Web + EduQG"),
                ],
                default="web",
                max_length=20,
            ),
        ),
    ]
