from datetime import datetime, timezone

from app.extensions import db
from app.models.plan import Plan, PlanName
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus


def get_active_subscription(user_id) -> Subscription | None:
    return db.session.execute(
        db.select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_free_plan() -> Plan | None:
    return db.session.execute(
        db.select(Plan).where(
            Plan.name == PlanName.FREE,
            Plan.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()


def create_free_subscription_no_commit(user_id) -> dict:
    """
    Add a Free subscription to the session without committing.
    The caller is responsible for db.session.commit() to keep the
    surrounding operation atomic.
    Returns {"error": str} if the Free plan is missing.
    """
    free_plan = get_free_plan()
    if not free_plan:
        return {
            "error": (
                "Free plan not found. Run `flask seed-db` to seed plans "
                "before onboarding users."
            )
        }

    subscription = Subscription(
        user_id=user_id,
        plan_id=free_plan.id,
        billing_cycle=BillingCycle.FREE,
        start_date=datetime.now(timezone.utc),
        expiry_date=None,  # Free plan never expires
        status=SubscriptionStatus.ACTIVE,
    )
    db.session.add(subscription)
    db.session.flush()  # assigns subscription.id without committing
    return {"subscription": subscription}


def activate_paid_subscription(
    user_id,
    plan_id,
    billing_cycle: str,
    start_date: datetime,
    expiry_date: datetime,
) -> Subscription:
    """
    Cancel any existing ACTIVE subscriptions for the user, then create a
    fresh paid subscription and commit the whole operation atomically.
    Called after successful Razorpay payment verification.
    """
    # Cancel all currently active subscriptions (Free or previous paid)
    active_subs = db.session.execute(
        db.select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    ).scalars().all()

    for sub in active_subs:
        sub.status = SubscriptionStatus.CANCELLED
        sub.updated_at = datetime.now(timezone.utc)

    new_sub = Subscription(
        user_id=user_id,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        start_date=start_date,
        expiry_date=expiry_date,
        status=SubscriptionStatus.ACTIVE,
    )
    db.session.add(new_sub)
    db.session.flush()  # get new_sub.id before caller commits
    return new_sub
