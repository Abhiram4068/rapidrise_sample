from django.db import models
import random
import string


def generate_designation_id():
    while True:
        code = ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=4)
        )

        if not Designation.objects.filter(id=code).exists():
            return code


class Designation(models.Model):
    id = models.CharField(
        primary_key=True,
        max_length=4,
        default=generate_designation_id,
        editable=False,
        unique=True
    )

    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name