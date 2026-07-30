---
name: loop-vs-graph
description: the test for whether a problem needs a loop or a graph
type: pattern
date: 2026-07-29
confidence: high
reach: global
---

**Loop** governs behaviour *inside* one node: the agent picks tools, acts,
checks the intermediate result, revises the plan, and repeats until a verifier
approves. In `mam.py` this is a node's `verify` block with `max_rounds`.

**Graph** governs coordination *between* nodes: explicit dependencies,
branching, parallel stages, checkpoints, and result assembly. In `mam.py` this
is `needs` plus the topological scheduler.

**The test:** does the agent need to improve a result *within* one step? Design
a loop. Does work need to be handed *between* components? Design a graph.

**How to apply:** loop = node behaviour, graph = system coordination. They
compose — the router sends input to a node, the node runs its own loop, the
verifier decides whether the edge is traversed. Graphs may contain cycles
(a BLOCK verdict feeding back into build); loops may not span nodes.
