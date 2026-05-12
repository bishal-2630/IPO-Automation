from rest_framework import serializers
from .models import Account, ApplicationLog, FCMToken
from .encryption import encrypt_password


class FCMTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = FCMToken
        fields = ['token', 'device_id']


class AccountSerializer(serializers.ModelSerializer):
    # Accept plain password on write, never return it on read
    meroshare_pass = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Account
        fields = [
            'id', 'meroshare_user', 'meroshare_pass', 'dp_name',
            'crn', 'tpin', 'bank_name', 'owner_name',
            'kitta', 'is_active', 'last_applied', 'boid'
        ]
        read_only_fields = ['owner', 'last_applied']

    def create(self, validated_data):
        plain = validated_data.pop('meroshare_pass', None)
        instance = Account(**validated_data)
        if plain:
            instance.set_meroshare_pass(plain)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        plain = validated_data.pop('meroshare_pass', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if plain:
            instance.set_meroshare_pass(plain)
        instance.save()
        return instance


class ApplicationLogSerializer(serializers.ModelSerializer):
    account_user = serializers.CharField(source='account.meroshare_user', read_only=True)
    owner_name = serializers.CharField(source='account.owner_name', read_only=True)

    class Meta:
        model = ApplicationLog
        fields = ['id', 'account', 'account_user', 'owner_name', 'company_name', 'status', 'remark', 'is_read', 'timestamp']
