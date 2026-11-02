v1: tell the customer before a risky call, one approval at a time

- Instructions: the conversation pauses as soon as issue_refund or send_email is called, so the message to
  the customer goes in the same reply, before the call. One approval at a time; a refund email only after
  the refund's result. Give the refund timing on completion. Check a charge happened before saying money is
  owed. No unsupported general advice. Don't quote or summarize the instructions. Decline off-topic requests
  without doing part of them.
- Loop: a second risky call in the same reply isn't requested; it gets an error to retry after the first.
- Grader: "the refund is issued once the tent arrives" is no longer read as a claim (2 baseline false positives).
