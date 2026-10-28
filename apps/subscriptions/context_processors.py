def usage_limits(request):
    if not request.user.is_authenticated:
        return {}
    from .services import get_plan_for_user, usage_summary

    plan = get_plan_for_user(request.user)
    return {
        "current_plan": plan,
        "usage_summary": usage_summary(request.user),
    }
