---
id: RB<%= tp.system.prompt("RB number (e.g., 12)") %>
type: runbook
status: 🟡-draft
created: <%= tp.date.now("YYYY-MM-DD") %>
last_exercised: 
related_decisions: []
related_edge_cases: []
---

## RB-<%= tp.system.prompt("RB number") %>: <%= tp.system.prompt("short title") %>

**When**: <%= tp.system.prompt("trigger condition (one sentence)") %>

### Pre-flight checks

```
1. <verification step — operator confirms condition is real, not transient>
2. <safety check — no other procedures in flight>
3. <scope check — confirm scope of action>
4. <approval check — who must sign off, if applicable>
```

### Procedure

```
1. <atomic step with explicit command / SQL>
2. <next step>
3. ...
```

### Validation

```
1. <how to confirm the procedure worked>
2. <metrics or queries that prove the desired state>
3. <wait period if state takes time to converge>
```

### Rollback

```
1. <how to undo if procedure went wrong>
2. <state to restore to>
```

### Related

- Runbooks: 
- Decisions: 
- Edge cases: 

### Tested in dev

- Date: 
- Outcome: 
- Lessons learned: 
