from django.db import migrations, models


def rename_roles_forward(apps, schema_editor):
    # CharField `choices` aren't enforced at the DB level, so existing rows
    # still hold the old literal strings "staff"/"member" — rewrite them to
    # match the new choice values before the field's metadata changes below.
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="staff").update(role="employer_admin")
    User.objects.filter(role="member").update(role="employee")


def rename_roles_backward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="employer_admin").update(role="staff")
    User.objects.filter(role="employee").update(role="member")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_user_entra_object_id"),
    ]

    operations = [
        migrations.RunPython(rename_roles_forward, rename_roles_backward),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("icib_admin", "ICIB Admin"),
                    ("employer_admin", "Employer Admin"),
                    ("employee", "Employee"),
                ],
                default="employee",
                max_length=32,
            ),
        ),
    ]
