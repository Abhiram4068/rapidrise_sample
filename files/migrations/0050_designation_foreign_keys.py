from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


LEGACY_SLUG_TO_NAME = {
    "project_manager": "Project Manager",
    "team_lead": "Team Lead",
    "delivery_manager": "Delivery Manager",
    "product_manager": "Product Manager",
    "operations_manager": "Operations Manager",
    "program_manager": "Program Manager",
}


def _resolve_designation(Designation, value):
    if not value:
        return None
    value = str(value).strip()
    by_pk = Designation.objects.filter(pk=value).first()
    if by_pk:
        return by_pk
    name = LEGACY_SLUG_TO_NAME.get(value)
    if name:
        by_name = Designation.objects.filter(name__iexact=name).first()
        if by_name:
            return by_name
    by_name = Designation.objects.filter(name__iexact=value).first()
    if by_name:
        return by_name
    return Designation.objects.filter(name__icontains=value.replace("_", " ")).first()


def migrate_designation_values(apps, schema_editor):
    User = apps.get_model("files", "User")
    Designation = apps.get_model("administration", "Designation")
    DesignationChangeRequest = apps.get_model("files", "DesignationChangeRequest")

    for user in User.objects.all().iterator():
        legacy = getattr(user, "designation_legacy", None)
        if legacy:
            desig = _resolve_designation(Designation, legacy)
            if desig:
                user.designation_id = desig.pk
                user.save(update_fields=["designation_id"])

    for req in DesignationChangeRequest.objects.all().iterator():
        current_legacy = getattr(req, "current_designation_legacy", None)
        requested_legacy = getattr(req, "requested_designation_legacy", None)
        current = _resolve_designation(Designation, current_legacy)
        requested = _resolve_designation(Designation, requested_legacy)
        if current:
            req.current_designation_id = current.pk
        if requested:
            req.requested_designation_id = requested.pk
        req.save(update_fields=["current_designation_id", "requested_designation_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0002_alter_designation_id"),
        ("files", "0049_chunkuploadsession"),
    ]

    operations = [
        migrations.RenameField(
            model_name="user",
            old_name="designation",
            new_name="designation_legacy",
        ),
        migrations.AddField(
            model_name="user",
            name="designation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="administration.designation",
            ),
        ),
        migrations.RenameField(
            model_name="designationchangerequest",
            old_name="current_designation",
            new_name="current_designation_legacy",
        ),
        migrations.RenameField(
            model_name="designationchangerequest",
            old_name="requested_designation",
            new_name="requested_designation_legacy",
        ),
        migrations.AddField(
            model_name="designationchangerequest",
            name="current_designation",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="designation_changes_from",
                to="administration.designation",
            ),
        ),
        migrations.AddField(
            model_name="designationchangerequest",
            name="requested_designation",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="designation_changes_to",
                to="administration.designation",
            ),
        ),
        migrations.RunPython(migrate_designation_values, migrations.RunPython.noop),
        migrations.RemoveField(model_name="user", name="designation_legacy"),
        migrations.RemoveField(model_name="designationchangerequest", name="current_designation_legacy"),
        migrations.RemoveField(model_name="designationchangerequest", name="requested_designation_legacy"),
        migrations.AlterField(
            model_name="designationchangerequest",
            name="current_designation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="designation_changes_from",
                to="administration.designation",
            ),
        ),
        migrations.AlterField(
            model_name="designationchangerequest",
            name="requested_designation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="designation_changes_to",
                to="administration.designation",
            ),
        ),
    ]
