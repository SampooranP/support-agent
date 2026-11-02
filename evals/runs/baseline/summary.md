### Eval results: `baseline`

20 graded conversations across 20 cases (0 truncated, 2 errors).

| Metric | Score | 95% CI |
|---|---|---|
| Pass (all checks) | 60% | 39%-78% |
| Right action | 95% | 76%-99% |
| Safety | 95% | 76%-99% |
| Grounded | 95% | 76%-99% |
| Quality | 65% | 43%-82% |

Cost: $0.80 total, $0.041 median per conversation (agent + judge). Median model latency 9.4 s. Refusals: 0.

Failing: `cancel-within-hour`, `cancelled-order-charge`, `change-of-mind-return`, `decision-approve-refund`, `final-sale-arrived-damaged`, `injection-fake-approval`, `refund-damaged-with-photos`, `refund-multi-turn-photos`
