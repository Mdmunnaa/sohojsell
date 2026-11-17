from django.core.management import call_command
from django.db import migrations


def create_table(apps, schema_editor):
    """store/ratelimit.py-এর ডাটাবেস-ক্যাশের টেবিল (sp_ratelimit); আগে থেকে থাকলে কিছু করে না।"""
    call_command('createcachetable', database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("store", "0062_bug_audit_fixes"),
    ]

    operations = [migrations.RunPython(create_table, migrations.RunPython.noop)]
