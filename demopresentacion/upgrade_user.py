import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sima.settings")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.contrib.auth.models import User
from learning.models import Profile
from learning.credits import grant_plan_credits

username = sys.argv[1] if len(sys.argv) > 1 else "demouser"

try:
    user = User.objects.get(username=username)
except User.DoesNotExist:
    print(f"User {username} not found")
    sys.exit(1)

profile, _ = Profile.objects.get_or_create(user=user)
profile.plan = "basic"
profile.api_classes_used = 0
profile.save()
grant_plan_credits(profile)
print(f"Upgraded {username} to basic. Credits: {profile.credit_balance}")
