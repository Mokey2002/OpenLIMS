from django.contrib.auth import get_user_model
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.permissions import IsAuthenticated
from .serializers import UserLiteSerializer

User = get_user_model()


class UserLiteViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserLiteSerializer
    queryset = User.objects.all().order_by("username")
