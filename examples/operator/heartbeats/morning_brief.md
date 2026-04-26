# Morning Brief Heartbeat

**When:** daily 07:00
**Owner:** operator persona
**Output:** brief to ops channel + commit to .claude/learning/observations.json

## Steps
1. Read overnight messages (mocked in this example)
2. Spawn a 3-member parallel council on the day's top decision
3. Record the council's verdict to ReasoningBank
4. Echo the verdict + cost summary to stdout

## Success criteria
- Council reaches verdict within 4 turns per member
- Telemetry shows < $0.10 cost
- Healing circuits remain CLOSED
