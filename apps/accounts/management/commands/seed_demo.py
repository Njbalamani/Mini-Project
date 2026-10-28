from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.calendar_manager.models import CalendarEvent
from apps.subscriptions.models import Plan, Subscription
from apps.tasks.models import Task

User = get_user_model()


class Command(BaseCommand):
    help = "Create default plans, a demo user and sample data for manual review."

    def handle(self, *args, **options):
        free, _ = Plan.objects.get_or_create(
            slug="free",
            defaults={
                "name": "Free", "description": "Core productivity tools with limited AI usage.",
                "price_cents": 0, "is_premium": False,
                "limits": {"ai_messages": 30, "tasks": 50, "workflows": 2, "documents": 3},
            },
        )
        premium, _ = Plan.objects.get_or_create(
            slug="premium",
            defaults={
                "name": "Premium",
                "description": "Unlimited AI, advanced workflows, documents and analytics.",
                "price_cents": 1200, "is_premium": True,
                "limits": {"ai_messages": -1, "tasks": -1, "workflows": 50, "documents": 100},
            },
        )
        self.stdout.write(self.style.SUCCESS("Plans ready."))

        demo, created = User.objects.get_or_create(
            email="demo@nexamind.local",
            defaults={"full_name": "Demo User", "is_email_verified": True},
        )
        if created:
            demo.set_password("demo-pass-123")
            demo.save()
            Subscription.objects.create(user=demo, plan=free)
        self.stdout.write(self.style.SUCCESS("Demo user ready (demo@nexamind.local / demo-pass-123)."))

        admin_user, created_admin = User.objects.get_or_create(
            email="admin@nexamind.local",
            defaults={"full_name": "System Admin", "is_email_verified": True,
                      "is_staff": True, "is_superuser": True},
        )
        if created_admin:
            admin_user.set_password("admin-pass-123")
            admin_user.save()
        self.stdout.write(self.style.SUCCESS("Admin user ready (admin@nexamind.local / admin-pass-123)."))

        if created and not Task.objects.filter(owner=demo).exists():
            base = timezone.now()
            Task.objects.create(owner=demo, title="Prepare project presentation",
                                description="Assemble the final deck with charts and demo video.",
                                priority=Task.Priority.HIGH, status=Task.Status.IN_PROGRESS,
                                category="Work", due_date=base + timezone.timedelta(days=2))
            Task.objects.create(owner=demo, title="Review weekly analytics",
                                description="Check the productivity dashboard and note trends.",
                                priority=Task.Priority.MEDIUM, category="Work",
                                due_date=base + timezone.timedelta(days=1))
            Task.objects.create(owner=demo, title="Grocery run",
                                description="Buy essentials for the week.",
                                priority=Task.Priority.LOW, category="Personal",
                                due_date=base + timezone.timedelta(hours=6))
            Task.objects.create(owner=demo, title="Respond to mentor email",
                                status=Task.Status.DONE, priority=Task.Priority.MEDIUM,
                                category="Personal", completed_at=base)
            CalendarEvent.objects.create(
                owner=demo, title="Team standup", start=base + timezone.timedelta(hours=3),
                end=base + timezone.timedelta(hours=3, minutes=30), location="Zoom",
            )
            CalendarEvent.objects.create(
                owner=demo, title="Design review", start=base + timezone.timedelta(days=1, hours=10),
                end=base + timezone.timedelta(days=1, hours=11),
            )
            self.stdout.write(self.style.SUCCESS("Sample data seeded for the demo user."))
        else:
            self.stdout.write(self.style.WARNING("Sample data skipped (demo user already existed)."))