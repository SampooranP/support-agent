"""Deterministic guardrails around the agent.

- Personal data: a reply may only contain the signed-in customer's own email address and phone
  number, plus the store's public support contacts. Anything else is redacted before the reply is
  stored, as a backstop to the tool layer, which already only returns the customer's own data.
- Unconfirmed claims: a reply that says a refund was issued or an email sent, when no approved
  action of that kind has run in the conversation, is flagged (logged and traced) for review.
- Rate limits: caps on messages per conversation and per customer.
"""

import re
import time
from collections import deque
from dataclasses import dataclass, field

# Published in docs/faq.md, so always allowed in replies.
SUPPORT_EMAILS = {"support@lumenandpine.example"}
SUPPORT_PHONES = {"18005550142"}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# North American phone numbers: 555-0142, (512) 555-0148, 1-800-555-0142, +1 512 555 0148 ...
PHONE = re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\d-])")
REDACTED = "[redacted]"

# Phrases that say an action is finished. Deliberately narrow: "your refund request has been sent for
# review" is the correct thing to say while an approval is pending and must not match.
CLAIMS = {
    "issue_refund": re.compile(
        r"\brefund\b[^.\n]{0,40}?\b(?:has been|have been|was|is now|is)\s+(?:approved and\s+)?"
        r"(?:issued|processed|completed|credited|done|complete)\b"
        r"|\b(?:I(?:'ve| have)|we(?:'ve| have))\s+(?:issued|processed|refunded)\b"
        r"|\$[\d,.]+\*{0,2}\s+(?:has|have)\s+(?:gone|been (?:sent|returned|credited))\s+back\b",
        re.IGNORECASE,
    ),
    "send_email": re.compile(
        r"\b(?:I(?:'ve| have)|we(?:'ve| have))\s+(?:sent you an? email|emailed you)\b"
        r"|\b(?:the|an|your|this|that) email (?:has been|was) sent\b",
        re.IGNORECASE,
    ),
}
# "no refund has been issued yet" is the opposite of a claim, and "once approved, the refund is issued"
# (quoting the policy) describes what will happen, not what has.
NEGATION = re.compile(r"\b(?:no|not|never|nothing|hasn't|haven't|wasn't|isn't|won't|didn't|can't|cannot|"
                      r"once|when|after|if|until|before)\b[^.\n]{0,25}$", re.IGNORECASE)
# The condition can also come after: "the refund is issued once the tent arrives".
CONDITION_AFTER = re.compile(r"\s+(?:once|when|after|as soon as|if|until)\b(?!\s+again)", re.IGNORECASE)


def _digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return digits if len(digits) == 11 else "1" + digits


def foreign_personal_data(text: str, customer_email: str, customer_phone: str | None) -> list[str]:
    """Emails and phone numbers in text that belong to neither the customer nor the store."""
    allowed_emails = SUPPORT_EMAILS | {customer_email.lower()}
    allowed_phones = SUPPORT_PHONES | ({_digits(customer_phone)} if customer_phone else set())
    found = [e for e in EMAIL.findall(text) if e.lower() not in allowed_emails]
    found += [p for p in PHONE.findall(text) if _digits(p) not in allowed_phones]
    return found


def redact(text: str, items: list[str]) -> str:
    for item in sorted(set(items), key=len, reverse=True):
        text = text.replace(item, REDACTED)
    return text


def unconfirmed_claims(text: str, executed_tools: set[str]) -> list[str]:
    """Tool names whose completion the text claims, though no approved action of that kind ran."""
    claimed = []
    for tool, pattern in CLAIMS.items():
        if tool in executed_tools:
            continue
        for match in pattern.finditer(text):
            sentence_start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
            if CONDITION_AFTER.match(text, match.end()):
                continue
            if not NEGATION.search(text[sentence_start:match.start() + len(match.group().split()[0])]):
                claimed.append(tool)
                break
    return claimed


@dataclass
class RateLimiter:
    """Sliding-window limit: at most `limit` hits per key within `window_s` seconds."""

    limit: int
    window_s: float
    _hits: dict[str, deque] = field(default_factory=dict)
    _calls: int = 0

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._calls += 1
        if self._calls % 500 == 0:
            self.prune(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def prune(self, now: float | None = None) -> None:
        """Drop keys with no recent hits, so memory stays bounded."""
        now = time.monotonic() if now is None else now
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] > self.window_s]:
            del self._hits[key]
