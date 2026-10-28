from django.contrib import admin

from .models import CalendarEvent, EventReminder


class EventReminderInline(admin.TabularInline):
    model = EventReminder
    extra = 0


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "start", "end", "recurrence", "source")
    list_filter = ("source", "recurrence", "all_day")
    search_fields = ("title", "location")
    inlines = [EventReminderInline]


admin.site.register(EventReminder)
