# 13 · Stateful Graphs: Durable Execution and Checkpoints

> **Short answer:** Model the agent as a state machine. Nodes are functions that return partial updates, edges (fixed or conditional) pick the next node, reducers merge updates into typed state, and a checkpointer saves that state after every node. That one design gives you crash recovery, human approval pauses and "time travel" forks almost for free. LangGraph is the reference implementation in 2026. Reach for it when a run is long, expensive or needs a human in the middle.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

A 40-step agent run fails at step 38: the issue tracker timed out. If your framework assumes every run starts fresh, you either redo 37 steps (paying for the model calls again and maybe repeating side effects) or you hand-roll retry logic around a library that was never built for it.

The same gap shows up for humans. "Pause before sending the refund, wait two days for a manager, then continue" is impossible if the run's state only lives in a Python call stack.

The fix is to make state a first-class, serializable object and persist it at well-defined boundaries. Then "resume", "pause" and "fork" all reduce to "load a checkpoint and keep going".

## 2. The concept

### Four parts of a graph

| Part | What it is | In LangGraph |
|---|---|---|
| State | A typed dict or Pydantic model every node reads | `StateGraph(MyState)` |
| Node | `(state) -> partial update` | `graph.add_node("classify", fn)` |
| Edge | Fixed or conditional transition | `add_edge`, `add_conditional_edges` |
| Reducer | How an update merges into a key | `Annotated[list, operator.add]` |

`START` and `END` are sentinel nodes that mark the boundary.

```
            START
              │
          classify ──route──┬────────┬────────┐
                            ▼        ▼        ▼
                          refund    bug     sales
                            └────────┼────────┘
                                     ▼
                              human_review   ◄── interrupt: wait for a person
                                     │
                                   send
                                     │
                                    END
   checkpoint written after every box: (thread, seq, node, next, state)
```

### Checkpoints are the product

After each node returns, the runtime merges the update, chooses the next node, and writes `(thread_id, step, next_node, state)` to a checkpointer (in-memory, SQLite, Postgres, Redis or your own). Three capabilities fall out:

1. **Durable execution.** On a crash, load the latest checkpoint for the thread and continue from `next_node`. Completed nodes do not run again.
2. **Human-in-the-loop.** A node calls `interrupt(...)`; the runtime saves state and returns. Later, `Command(resume=value)` re-enters that node with the human's answer.
3. **Time travel.** Every checkpoint is addressable. Load an older one, change something, and run forward on a new branch of history.

### Short-term and long-term memory

Thread state (messages, scratch values) is short-term memory and lives in checkpoints. Facts that must outlive a thread go to a separate long-term store keyed by user or namespace. Keep the two apart: checkpoints are for replay, stores are for recall.

### Multi-agent topologies

| Topology | Shape | Note |
|---|---|---|
| Supervisor | One router dispatches to specialists | LangChain now suggests building this with tool calls for tighter context control, rather than the `langgraph-supervisor` helper |
| Swarm | Agents hand off to each other through shared tools | No central router |
| Hierarchical | Supervisors of supervisors, as nested subgraphs | A subgraph is just a node |

### Where it goes wrong

- **Partial state.** If tool results or memory writes are not in state, a resume will not restore them.
- **Non-deterministic nodes.** Wall-clock reads, random seeds and live API calls make a replay differ from the original. Capture them in state.
- **Side effects before the checkpoint.** A node that charges a card and then crashes will charge again on resume. Make side effects idempotent (idempotency keys) or split them into their own node.
- **Edge soup.** If every edge is conditional, nobody can reason about the graph. Prefer straight lines with a few branches.

## 3. What changed by Oct 2026

- **LangGraph 1.2.x is current** (1.2.15 in mid-October). The 1.2 line added type-safe `version="v2"` streaming and invoke outputs, per-node timeouts, a `trace_policy` option and a delta channel for large, append-heavy state.
- **`create_agent` in LangChain 1.x is the default way to get a tool-calling agent;** it runs on the LangGraph runtime. Older `create_react_agent` examples are legacy.
- **Deep Agents (0.7.x)** packages a LangGraph-based harness with planning, subagents, a virtual filesystem and middleware. LangSmith offers managed Deep Agents and sandboxes, so the "graph plus checkpointer" now has a hosted option.
- **Graph engines are everywhere.** Google ADK 2.x has a graph-based workflow engine, Microsoft Agent Framework 1.x has typed workflows with checkpoints (Lesson 14), and Vercel's `WorkflowAgent` makes each tool call a durable step. The idea in this lesson is no longer framework-specific.
- **Append-only state matters more.** Current frontier models preserve reasoning across turns and providers cache prompt prefixes, so editing earlier history invalidates both. Treat message lists as append-only, and checkpoint rather than rewrite.
- **2026 update, System One routers:** a conditional edge such as `classify → refund | bug | sales` is a `choice` question. A decision model (Jev or Clef, Lessons 55–56) returns calibrated probabilities in tens of milliseconds; route in code on a threshold and send low-confidence cases to the human node.

## 4. Build it

`code/main.py` is a stdlib re-implementation of the core runtime:

- `StateGraph` with `add_node`, `add_edge`, `add_conditional_edges` and per-key reducers (`log` appends, everything else replaces).
- `SqliteCheckpointer` backed by an in-memory `sqlite3` database. It writes one row per node with the thread, sequence number, node, next node and JSON state.
- `Interrupt` and `Command(resume=...)` for human approval.
- `CompiledGraph.stream` yields `(node, update)` pairs, resumes from the latest checkpoint, or forks from any earlier sequence number.

```bash
python3 code/main.py
```

What to look for:

1. The refund ticket stops at `__interrupt__` and resumes with `approve`.
2. The bug ticket crashes once in the `bug` node. The rerun does **not** execute `classify` again; it starts from the saved `next=bug`.
3. The checkpoint history table shows one row per node, including the interrupt.
4. The time-travel fork reloads the interrupt checkpoint, answers `reject`, and produces a different ending on the same thread.

## 5. Use it in production

- **LangGraph 1.2** with `langgraph-checkpoint-postgres` (or SQLite for single-node services). Use `interrupt()` plus `Command(resume=...)` for approvals, and stream with `version="v2"` for typed events.
- **LangSmith Deployment / managed Deep Agents** when you want the graph hosted with task queues, cron and a checkpointer already wired.
- **Durable-execution engines** (Temporal, Restate, Vercel Workflows) when the workflow spans services and days and you would rather journal steps than checkpoint a graph.
- **Alternatives with the same shape:** Google ADK 2.x graph workflows, Microsoft Agent Framework workflows, Mastra workflows (Lesson 18).

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

def human_review(state):
    decision = interrupt({"draft": state["draft"]})
    return {"approved": decision == "approve"}

graph = StateGraph(TicketState)
graph.add_node("classify", classify)
graph.add_node("human_review", human_review)
graph.add_edge(START, "classify")
app = graph.compile(checkpointer=SqliteSaver.from_conn_string("ckpt.db"))
config = {"configurable": {"thread_id": "t-42"}}
app.invoke({"ticket": "charged twice"}, config)
app.invoke(Command(resume="approve"), config)
```

## 6. Architect's lens

1. **Checkpoint granularity is a cost dial.** One checkpoint per node is the default. Big states (long message lists, documents) make every write expensive. Keep large blobs in object storage and put references in state.
2. **Idempotency beats exactly-once.** No checkpointer can make an external side effect exactly-once. Give every write an idempotency key derived from `(thread_id, node, step)` so a replay is harmless.
3. **Version your state schema.** A checkpoint written by last week's graph must load in this week's graph. Add fields with defaults, never rename keys silently, and test resume across deploys.
4. **Measure resume, not only success.** Track resume rate, steps saved per resume and the age of interrupted threads. A pile of week-old interrupts is a product problem, not a runtime one.
5. **Graphs are for the parts you can name.** Put the predictable skeleton in the graph and let a tool-calling agent loop live inside one node. A graph that tries to encode every model decision becomes unmaintainable.

## 7. Exercises

1. Add a confidence score to `classify`. Below 0.7, route straight to `human_review` and let the human set `route`.
2. Replace the in-memory database with a file and kill the process between the crash and the resume. Does it still work?
3. Add a parallel fan-out: `refund` and `notify` run in the same step and both append to `log`. Why does a reducer matter here?
4. Add a per-node timeout that raises if a node runs longer than N seconds and leaves the last checkpoint intact.
5. Port the toy to LangGraph 1.2 and compare the streamed event shapes with this script's output.

## 8. Key terms

| Term | Meaning |
|---|---|
| State graph | Typed state plus nodes, edges and reducers |
| Reducer | Function that merges a node's update into one state key |
| Checkpointer | Storage that saves state after every node |
| Thread | One conversation or run; the key for its checkpoints |
| Interrupt | A pause that saves state and waits for outside input |
| `Command(resume=…)` | The input that continues an interrupted thread |
| Time travel | Re-running from an earlier checkpoint on a new branch |
| Durable execution | Continuing after a crash without redoing finished work |

## 9. Quick check

<details><summary>1. After a crash in node 5, which nodes run again on resume?</summary>Only node 5 and later. Nodes 1–4 already have checkpoints, and the latest checkpoint records that the next node is 5.</details>
<details><summary>2. Why can resuming charge a customer twice, and how do you stop it?</summary>If the node made the charge and then crashed before its checkpoint was written, the resume runs the node again. Use an idempotency key per thread and step, or move the charge into its own small node.</details>
<details><summary>3. What is the difference between a checkpoint and a long-term memory store?</summary>A checkpoint is a snapshot of one thread's state for replay and resume. A store holds facts that should survive across threads, such as user preferences.</details>

## References

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph persistence and checkpointers: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph releases: https://github.com/langchain-ai/langgraph/releases
- Deep Agents: https://docs.langchain.com/oss/python/deepagents/overview
- Google ADK: https://google.github.io/adk-docs/
