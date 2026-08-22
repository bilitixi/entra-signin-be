from django.conf import settings
from django.core.mail import send_mail


def send_account_setup_email(email, display_name, temp_password):
    """Emails a newly-provisioned user their temp password and a link to
    sign in. Entra forces a password change on that first sign-in
    (forceChangePasswordNextSignIn, set at creation time in
    accounts/graph.py) — that's the "set up your account" step; this email
    is just what gets them there instead of an admin relaying the password
    by hand.
    """
    sign_in_url = f"{settings.BACKEND_BASE_URL.rstrip('/')}/api/v1/auth/login"
    subject = "Set up your account"
    greeting = f"Hi {display_name}," if display_name else "Hi,"
    body = (
        f"{greeting}\n\n"
        "An account has been created for you. Sign in here to finish setting it up:\n"
        f"{sign_in_url}\n\n"
        "Use this temporary password the first time you sign in — you'll be "
        "asked to choose your own password (and set up multi-factor "
        "authentication) right away:\n\n"
        f"    {temp_password}\n\n"
        "This password is only ever sent in this email.\n"
    )
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )
