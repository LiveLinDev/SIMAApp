from dataclasses import dataclass

from django.db import transaction

from .models import CreditLedgerEntry, LessonJob, PLAN_DETAILS, Plan, Profile


@dataclass(frozen=True)
class CreditEstimate:
    action: str
    amount: int
    details: tuple[str, ...]


TEXT_QUIZ_COST = 18
AUDIO_TRANSCRIPTION_COST = 35
VERIFICATION_COST = 7
REGENERATION_COST = 12


def plan_credit_amount(plan: str) -> int | None:
    return PLAN_DETAILS.get(plan, PLAN_DETAILS[Plan.FREE])["credits"]


def grant_plan_credits(profile: Profile, description: str = "Creditos mensuales del plan") -> int | None:
    amount = plan_credit_amount(profile.plan)
    if amount is None:
        profile.credit_balance = 0
        profile.save(update_fields=["credit_balance", "updated_at"])
        CreditLedgerEntry.objects.create(
            user=profile.user,
            action=CreditLedgerEntry.Action.PLAN_GRANT,
            amount=0,
            balance_after=0,
            description="Plan ilimitado activo",
        )
        return None

    profile.credit_balance = amount
    profile.save(update_fields=["credit_balance", "updated_at"])
    CreditLedgerEntry.objects.create(
        user=profile.user,
        action=CreditLedgerEntry.Action.PLAN_GRANT,
        amount=amount,
        balance_after=profile.credit_balance,
        description=description,
        metadata={"plan": profile.plan},
    )
    return amount


def estimate_lesson_job_cost(job: LessonJob | None = None, *, has_audio=False, has_text=False) -> CreditEstimate:
    audio = has_audio or bool(getattr(job, "audio", None))
    text = has_text or bool((getattr(job, "source_text", "") or "").strip())
    details = []
    amount = 0

    if audio:
        amount += AUDIO_TRANSCRIPTION_COST
        details.append(f"transcripcion {AUDIO_TRANSCRIPTION_COST}")
    if text or audio:
        amount += TEXT_QUIZ_COST
        details.append(f"quiz adaptativo {TEXT_QUIZ_COST}")
        amount += VERIFICATION_COST
        details.append(f"revision final {VERIFICATION_COST}")

    return CreditEstimate(
        action=CreditLedgerEntry.Action.CLASS_TRANSCRIPTION if audio else CreditLedgerEntry.Action.QUIZ_GENERATION,
        amount=amount,
        details=tuple(details),
    )


def has_enough_credits(profile: Profile, amount: int) -> bool:
    if plan_credit_amount(profile.plan) is None:
        return True
    return profile.credit_balance >= amount


@transaction.atomic
def consume_credits(
    profile: Profile,
    amount: int,
    *,
    action: str,
    course=None,
    class_session=None,
    description: str = "",
    metadata: dict | None = None,
) -> CreditLedgerEntry | None:
    if amount <= 0 or plan_credit_amount(profile.plan) is None:
        return None

    profile = Profile.objects.select_for_update().get(pk=profile.pk)
    if profile.credit_balance < amount:
        raise ValueError("Creditos insuficientes.")

    profile.credit_balance -= amount
    profile.save(update_fields=["credit_balance", "updated_at"])
    return CreditLedgerEntry.objects.create(
        user=profile.user,
        course=course,
        class_session=class_session,
        action=action,
        amount=-amount,
        balance_after=profile.credit_balance,
        description=description,
        metadata=metadata or {},
    )
