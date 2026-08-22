from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Manager for the email-based, Entra-linked User model.

    There is no local password login (see AUTHENTICATION.md) — accounts are
    provisioned via roster intake / POST /users and signed in exclusively
    through Entra ID, so this manager never sets a usable password.
    """

    use_in_migrations = True

    def _create_user(self, email, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "icib_admin")
        user = self._create_user(email, **extra_fields)
        if password:
            user.set_password(password)
            user.save(using=self._db)
        return user
