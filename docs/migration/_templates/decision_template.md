---
id: D<%= tp.system.prompt("D-number (e.g., 50)") %>
type: decision
status: 🟡-proposed
phase: <%= tp.system.prompt("phase (e.g., phase1)") %>
created: <%= tp.date.now("YYYY-MM-DD") %>
locked: 
owner: <%= tp.system.prompt("owner") %>
depends_on: []
related_edge_cases: []
supersedes: 
superseded_by: 
---

## D<%= tp.system.prompt("D-number (e.g., 50)") %>: <%= tp.system.prompt("short title") %>

**Status**: 🟡 Proposed
**Driver**: <%= tp.system.prompt("what prompted this decision (a user message, agent finding, upstream constraint)") %>

**Decision**: <%= tp.system.prompt("the actual choice") %>

**Rationale**: 

**Trade-offs accepted**:

**Affects**:
- Decisions: 
- Edge cases: 
- Runbooks: 
- Schema: 
- Code modules: 

**Reversibility**: <reversible | hard | one-way>

**See also**: 
