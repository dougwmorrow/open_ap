---
id: <%= tp.system.prompt("Edge case ID (e.g., S15)") %>
type: edge_case
series: <%= tp.system.prompt("Series letter (M/S/I/N/P/G/D/F/V)") %>
status: 🔴-open
created: <%= tp.date.now("YYYY-MM-DD") %>
related_decisions: []
mitigation_phase: 
---

## <%= tp.system.prompt("Edge case ID") %>: <%= tp.system.prompt("short description") %>

**Series**: <%= tp.system.prompt("Series letter") %>
**Status**: 🔴 Open

### Description

<%= tp.system.prompt("describe the edge case") %>

### Trigger conditions

- 

### Mitigation

- 

### Test coverage

- Tier: <1, 2, 3, 4, 5>
- Test file: 

### Related

- Decisions: 
- Other edge cases: 
- Runbooks: 

### Discovery

How was this edge case identified? (Agent research / production incident / code review / pattern from CLAUDE.md / etc.)
