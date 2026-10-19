from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("municipalities", "0003_public_branding_and_notice")]

    operations = [
        migrations.AddField(
            model_name="municipality",
            name="statistics_version",
            field=models.PositiveBigIntegerField(default=1, editable=False),
        )
    ]
