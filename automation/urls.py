from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AccountViewSet, ApplicationLogViewSet, RegisterView, LoginView,
    FCMTokenViewSet, ManualTriggerView, SecureTriggerView, HealthView,
    UserProfileView, DeleteUserView,
)

router = DefaultRouter()
router.register(r'accounts', AccountViewSet, basename='account')
router.register(r'logs', ApplicationLogViewSet, basename='applicationlog')
router.register(r'fcm-tokens', FCMTokenViewSet, basename='fcm-token')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/profile/', UserProfileView.as_view(), name='profile'),
    path('auth/delete-account/', DeleteUserView.as_view(), name='delete-account'),
    path('run-all/', ManualTriggerView.as_view(), name='run-all'),
    path('trigger-automation/', SecureTriggerView.as_view(), name='secure-trigger'),
    path('health/', HealthView.as_view(), name='health'),
]
