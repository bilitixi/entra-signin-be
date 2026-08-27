import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class Role(models.TextChoices):
    ICIB_ADMIN = "icib_admin", "ICIB Admin"
    EMPLOYER_ADMIN = "employer_admin", "Employer Admin"
    EMPLOYEE = "employee", "Employee"


class User(AbstractBaseUser, PermissionsMixin):
    """Local user record, linked to an Entra ID identity on first sign-in.

    Accounts are provisioned locally first (roster intake / POST /users);
    Entra sign-in only ever links to an existing row by email, it never
    creates one — see BACKEND_API_FLOW.md §3.2 and auth/views.py:callback.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.EMPLOYEE)

    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    dob = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)

    # Set on first successful Entra sign-in; used afterwards to detect
    # identity mismatch (README §2.1, AUTHENTICATION.md). default=None is
    # required, not just null=True — without an explicit default, Django's
    # CharField falls back to "" (not None) whenever a User is created
    # without passing this field (e.g. manage.py shell), which broke the
    # `entra_object_id is None` check in auth/views.py:callback and caused
    # every such user's first sign-in to be rejected as identity_mismatch.
    entra_object_id = models.CharField(
        max_length=64, null=True, blank=True, unique=True, default=None
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email
