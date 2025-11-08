from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet, AnalysisViewSet, ReportViewSet

router = DefaultRouter()
router.register(r'conversations', ConversationViewSet, basename='conversation')
router.register(r'analyse', AnalysisViewSet, basename='analyse')
router.register(r'reports', ReportViewSet, basename='report')

urlpatterns = [
    path('', include(router.urls)),
]
