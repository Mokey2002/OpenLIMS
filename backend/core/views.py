from django.contrib.auth import get_user_model
from rest_framework.viewsets import ReadOnlyModelViewSet, ModelViewSet
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import MeSerializer
from .permissions import IsAdminOnly
from .serializers import UserLiteSerializer, UserCreateSerializer

User = get_user_model()


class UserLiteViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = UserLiteSerializer
    queryset = User.objects.all().order_by("username")


class UserAdminViewSet(ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = UserCreateSerializer
    queryset = User.objects.all().order_by("username")

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)
