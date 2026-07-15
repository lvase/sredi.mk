from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0002_submissionratelimit"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="suspicious_reasons",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
