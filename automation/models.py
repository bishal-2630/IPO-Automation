from django.db import models
from django.contrib.auth.models import User
from .encryption import encrypt_password, decrypt_password
import os


class Account(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='meroshare_accounts')
    meroshare_user = models.CharField(max_length=100, unique=True)
    meroshare_pass = models.CharField(max_length=500)  # stored encrypted
    boid = models.CharField(max_length=20, blank=True, null=True, help_text="16-digit BOID for checking IPO results")
    dp_name = models.CharField(max_length=255)
    crn = models.CharField(max_length=20)
    tpin = models.CharField(max_length=10)
    bank_name = models.CharField(max_length=255)
    owner_name = models.CharField(max_length=50, blank=True, null=True, help_text="e.g., Mom, Dad, Me")
    kitta = models.IntegerField(default=10)
    is_active = models.BooleanField(default=True)
    last_applied = models.DateTimeField(auto_now=True)

    def set_meroshare_pass(self, plain_password: str):
        self.meroshare_pass = encrypt_password(plain_password)

    def get_meroshare_pass(self) -> str:
        return decrypt_password(self.meroshare_pass)

    def __str__(self):
        return self.meroshare_user


class FCMToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fcm_tokens')
    token = models.TextField(unique=True)
    device_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.device_id or 'Unknown Device'}"


class ApplicationLog(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=255)
    status = models.CharField(max_length=100)
    remark = models.TextField(blank=True, null=True)
    is_read = models.BooleanField(default=False)
    is_listed = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account.meroshare_user} - {self.company_name} ({self.status})"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_image_url = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return self.user.username


class PasswordResetOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.otp}"

    def is_valid(self):
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() < self.created_at + timedelta(seconds=300)


class BankAccount(models.Model):
    linked_account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name='bank_account')
    bank = models.CharField(max_length=100, help_text="Bank code/name")
    phone_number = models.CharField(max_length=20)
    bank_password = models.CharField(max_length=500) # stored encrypted
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Bank for {self.linked_account.meroshare_user}"

    def set_bank_password(self, plain_password: str):
        self.bank_password = encrypt_password(plain_password)

    def get_bank_password(self) -> str:
        return decrypt_password(self.bank_password)
