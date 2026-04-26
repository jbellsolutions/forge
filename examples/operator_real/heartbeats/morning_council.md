---
schedule: "07:00 weekdays"
agent: operator_real
priority: A
---

# Morning Council

Spawn the 3-member parallel council to decide today's top "ship or wait"
question. Record verdict to vault + ReasoningBank. Promote any memory that
crosses the confidence threshold.

## Success criteria
- Council reaches majority verdict within 4 turns per member
- Verdict written to `decisions/`
- Telemetry shows < $0.10 spent
