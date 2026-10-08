"""Cheap fraud screening before a charge."""
from __future__ import annotations

import re

HIGH_VALUE_EUR = 5000
_TEST_ACCOUNT = re.compile(r"^(test|qa)[a-z0-9._-]*@example\.com$")


def is_suspicious(email: str, amount: float) -> bool:
    """Flag very large charges and internal test accounts used on production."""
    return amount > HIGH_VALUE_EUR or bool(_TEST_ACCOUNT.match(email))
