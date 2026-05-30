from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0057_alter_filesharelink_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharebundle',
            name='accessed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
