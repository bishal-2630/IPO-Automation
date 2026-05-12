from .models import Account, ApplicationLog, FCMToken
from .serializers import AccountSerializer, ApplicationLogSerializer, FCMTokenSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.decorators import action
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from .tasks import run_all_accounts_task
from rest_framework import serializers, viewsets, status
from rest_framework.serializers import ModelSerializer
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Account, ApplicationLog, FCMToken, Profile
import os


class UserSerializer(ModelSerializer):
    profile_image_url = serializers.CharField(source='profile.profile_image_url', read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'profile_image_url']


class FCMTokenViewSet(viewsets.ModelViewSet):
    serializer_class = FCMTokenSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = FCMToken.objects.all()

    def create(self, request, *args, **kwargs):
        token = request.data.get('token')
        device_id = request.data.get('device_id')
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

        fcm_token_obj, created = FCMToken.objects.update_or_create(
            token=token,
            defaults={
                'user': request.user,
                'device_id': device_id
            }
        )
        serializer = self.get_serializer(fcm_token_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Account.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ApplicationLogViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationLogSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ApplicationLog.objects.filter(account__owner=self.request.user).order_by('-timestamp')

    @action(detail=False, methods=['post'], url_path='mark-as-read')
    def mark_as_read(self, request):
        unreads = self.get_queryset().filter(is_read=False)
        unreads.update(is_read=True)
        return Response({'status': 'marked as read'})


class RegisterView(APIView):
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email', '')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        if not username or not password:
            return Response({'error': 'Please provide username and password'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.create_user(username=username, password=password, email=email, first_name=first_name, last_name=last_name)
        token, created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if user:
            token, created = Token.objects.get_or_create(user=user)
            return Response({'token': token.key}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid Credentials'}, status=status.HTTP_401_UNAUTHORIZED)


class UserProfileView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class DeleteUserView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        user.delete()
        return Response({"status": "User account deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


class ManualTriggerView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        run_all_accounts_task.delay()
        return Response({"status": "Automation triggered for all active accounts"}, status=status.HTTP_200_OK)


class SecureTriggerView(APIView):
    """
    Endpoint to trigger automation from external services like Cron-job.org.
    Requires a secret token in the X-Trigger-Token header.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        token = request.headers.get('X-Trigger-Token')
        expected_token = os.environ.get('TRIGGER_TOKEN')

        if not expected_token or token != expected_token:
            return Response({"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        run_all_accounts_task.delay()
        return Response({"status": "Automation triggered successfully"}, status=status.HTTP_200_OK)


class HealthView(APIView):
    def get(self, request):
        from cryptography.fernet import Fernet
        key = os.environ.get("ENCRYPTION_KEY", "").strip()
        key_valid = False
        error_msg = None
        try:
            if key:
                Fernet(key.encode())
                key_valid = True
        except Exception as e:
            error_msg = str(e)

        return Response({
            "status": "online",
            "version": "v3.17-final",
            "encryption_key_length": len(key),
            "encryption_key_valid": key_valid,
            "encryption_error": error_msg,
            "branch": "user-part-1"
        })


def home_view(request):
    from django.http import HttpResponse
    return HttpResponse("""
        <div style='background: #1a1a1a; color: #00ff00; padding: 20px; font-family: monospace;'>
            <h1>🚀 IPO AUTOMATION BACKEND</h1>
            <p style='color: #ff00ff; font-size: 20px;'>VERSION: v3.18</p>
            <p>Branch: user-part-1</p>
            <p>Access the API at <a href='/api/' style='color: #00ffff;'>/api/</a>.</p>
        </div>
    """)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()
