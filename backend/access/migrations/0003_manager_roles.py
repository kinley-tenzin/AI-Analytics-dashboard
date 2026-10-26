"""ADR-044: the website is for managers. Rename the module viewer groups to manager groups (their
members keep their access and gain dashboard authoring for their module) and retire the separate
Dashboard Creator group (its members must be given a current role by the administrator)."""

from django.db import migrations

RENAMES = {
    "DrukSmart HR Viewer": "DrukSmart HR Manager",
    "DrukSmart Accounts Viewer": "DrukSmart Accounts Manager",
}
RETIRED = ["DrukSmart Dashboard Creator"]


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for old, new in RENAMES.items():
        group = Group.objects.filter(name=old).first()
        if group is None:
            continue
        target = Group.objects.filter(name=new).first()
        if target is None:
            group.name = new
            group.save()
        else:  # both exist (e.g. seed_roles ran first): move the members, drop the old group
            target.user_set.add(*group.user_set.all())
            group.delete()
    Group.objects.filter(name__in=RETIRED).delete()


def backwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for old, new in RENAMES.items():
        Group.objects.filter(name=new).update(name=old)


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0002_login_failure"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
