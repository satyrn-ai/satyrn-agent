from django.db import models
from django.utils import timezone


class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=40, blank=True, default="")
    notes = models.CharField(max_length=2000, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"


class FollowUp(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="follow_ups",
    )
    summary = models.CharField(max_length=200)
    due_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
