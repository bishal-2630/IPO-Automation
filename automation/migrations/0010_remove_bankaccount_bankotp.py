from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('automation', '0009_bankotp_user_alter_bankotp_account'),
    ]

    operations = [
        migrations.DeleteModel(
            name='BankOTP',
        ),
        migrations.DeleteModel(
            name='BankAccount',
        ),
    ]
