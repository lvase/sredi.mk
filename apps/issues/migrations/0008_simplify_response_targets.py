import django.db.models.deletion
from django.db import migrations, models


def consolidate_response_targets(apps, schema_editor):
    SlaPolicy = apps.get_model("issues", "SlaPolicy")
    Municipality = apps.get_model("municipalities", "Municipality")

    for municipality_id in Municipality.objects.values_list("id", flat=True).iterator():
        policies = SlaPolicy.objects.filter(municipality_id=municipality_id).order_by(
            "category_id", "id"
        )
        target = policies.filter(category__isnull=True).first() or policies.first()
        if target:
            policies.exclude(pk=target.pk).delete()
        else:
            SlaPolicy.objects.create(
                municipality_id=municipality_id,
                triage_hours=24,
                first_response_hours=48,
                resolution_hours=240,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0007_scalability_reliability"),
    ]

    operations = [
        migrations.RunPython(
            consolidate_response_targets,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="slapolicy",
            name="unique_default_sla_per_mun",
        ),
        migrations.RemoveConstraint(
            model_name="slapolicy",
            name="unique_category_sla_per_mun",
        ),
        migrations.RemoveField(
            model_name="slapolicy",
            name="category",
        ),
        migrations.RemoveField(
            model_name="slapolicy",
            name="first_response_hours",
        ),
        migrations.RenameField(
            model_name="slapolicy",
            old_name="triage_hours",
            new_name="review_hours",
        ),
        migrations.AlterField(
            model_name="slapolicy",
            name="municipality",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="response_target",
                to="municipalities.municipality",
            ),
        ),
        migrations.RenameModel(
            old_name="SlaPolicy",
            new_name="ResponseTarget",
        ),
        migrations.AlterModelOptions(
            name="responsetarget",
            options={
                "verbose_name": "response target",
                "verbose_name_plural": "response targets",
            },
        ),
    ]
