from django.contrib import admin
from .models import Conversation, Message, ConversationAnalysis

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ['sender', 'text', 'timestamp']
    readonly_fields = ['timestamp']

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'created_at', 'is_analyzed', 'message_count']
    list_filter = ['is_analyzed', 'created_at']
    search_fields = ['title']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [MessageInline]
    def message_count(self, obj):
        return obj.messages.count()
    message_count.short_description = 'Messages'

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation', 'sender', 'text_preview', 'timestamp']
    list_filter = ['sender', 'timestamp']
    search_fields = ['text', 'conversation__title']
    readonly_fields = ['timestamp']
    def text_preview(self, obj):
        return obj.text[:50] + '...' if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Message'

@admin.register(ConversationAnalysis)
class ConversationAnalysisAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'conversation', 'overall_score', 'sentiment',
        'resolution', 'escalation_needed', 'created_at'
    ]
    list_filter = ['sentiment', 'resolution', 'escalation_needed', 'created_at']
    search_fields = ['conversation__title']
    readonly_fields = ['created_at', 'updated_at']
