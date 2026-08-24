from django.urls import path

from . import views

urlpatterns = [
    path("auth/login", views.login, name="auth-login"),
    path("auth/callback", views.callback, name="auth-callback"),
    path("auth/logout", views.logout, name="auth-logout"),
    path("auth/me", views.me, name="auth-me"),
    path(
        "auth/entra-connector/attribute-collection-submit",
        views.attribute_collection_submit,
        name="auth-attribute-collection-submit",
    ),
    path("users", views.users_collection, name="users-collection"),
    path("users/<uuid:user_id>", views.user_detail, name="user-detail"),
]
