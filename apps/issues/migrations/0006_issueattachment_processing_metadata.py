from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("issues", "0005_issue_public_title_issue_public_title_approved_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="issueattachment",
            name="original_size_bytes",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="stored_size_bytes",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="processed_width",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="processed_height",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="stored_format",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="issueattachment",
            name="processing_version",
            field=models.PositiveSmallIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
