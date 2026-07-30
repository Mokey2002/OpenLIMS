from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .llm import configured_model_info, enhance_with_llm
from .tools import route_assistant_message


class AssistantChatSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)


class AssistantChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = serializer.validated_data["message"]

        result = route_assistant_message(
            message=message,
            user=request.user,
        )

        result = enhance_with_llm(
            message=message,
            tool_result=result,
        )

        return Response(result, status=status.HTTP_200_OK)

class AssistantStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(configured_model_info(), status=status.HTTP_200_OK)

