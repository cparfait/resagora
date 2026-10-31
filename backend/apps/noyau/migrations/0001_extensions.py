from django.contrib.postgres.operations import BtreeGistExtension, UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Extensions PostgreSQL : btree_gist (contrainte d'exclusion RG-01) et unaccent (recherche)."""

    initial = True
    dependencies: list[tuple[str, str]] = []
    operations = [BtreeGistExtension(), UnaccentExtension()]
