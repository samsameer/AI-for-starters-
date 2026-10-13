# 49 · Map Assumptions and Resolve the Riskiest One First

> **Short answer:** Every roadmap item hides bets: users will trust it, the data is there, the model is accurate enough, someone will own it. Write those bets as falsifiable assumptions. Score each on impact, uncertainty and irreversibility, and test the highest open risk first with the cheapest experiment that could prove it wrong. The thresholds and the pass, fail and ambiguous decisions are fixed before the result arrives. Use this map to sequence work by uncertainty, not by enthusiasm.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~65 min

---

## 1. The problem

Teams sort backlogs by excitement or stakeholder volume. The riskiest unknown, such as "can we even identify the service from alert text?", gets discovered in week eight, after the UI, the integration and the launch plan are done.

AI products make this worse because the most important assumptions are statistical. "The model is accurate" is never simply true or false. It is true *at some threshold, for some population, at some cost*. If you don't make those parts explicit, you can't test them.

## 2. The concept

### Five assumption classes

| Class | Question |
|---|---|
| Value | Does the outcome matter enough? |
| Usability | Can the user understand and act on it? |
| Feasibility | Can the system produce it with the available data and constraints? |
| Viability | Can the organization sustain the cost, ownership and operation? |
| Safety | Can it fail without unacceptable consequence? |

### Falsifiable statements

Untestable: "the feature is useful".
Testable: "8 of 10 on-call engineers act on a read-only suggestion within 2 minutes without opening dashboards."

For System One decisions, a feasibility assumption needs **two** numbers, coverage and precision:

> On 200 replayed alerts, the decision model names the failing service with P ≥ 0.8 on at least 70% of them, and is right on at least 97% of those.

### Risk is not one number

Score each 1–5:

- **Impact:** how much damage if the assumption is false.
- **Uncertainty:** how weak the current evidence is.
- **Irreversibility:** how costly it is to learn the answer after you have committed.

The lab uses `risk = impact × uncertainty + irreversibility`. The formula isn't universal. Its job is to make the team argue explicitly about order.

```
assumptions ─► score ─► highest open risk ─► cheapest decisive experiment
                                                      │
                                    ┌─────────────────┼──────────────────┐
                                  pass             ambiguous            fail
                                    │                 │                   │
                              bounded build      more evidence     reframe or stop
```

### Experiments, not confirmation rituals

A real experiment has a claim that could be false, a realistic sample, an observable metric, a threshold chosen in advance, and **different** decisions for pass and fail. If pass and fail both lead to "build it", it is a ritual.

### Reversibility changes the order

Get evidence earlier for irreversible, high-consequence choices. An offline replay comes before a production integration. A human-approved suggestion comes before automatic action. The build should follow the shape of the uncertainty.

## 3. What changed by Oct 2026

- **Feasibility experiments got cheap.** Offline replay against a decision model costs very little: Clef-flash is priced at $0.038 per million input tokens on Workers AI, and the weights are Apache-2.0 for self-hosting. A 200-alert feasibility test is now a two-day job, not a quarter.
- **Vendor benchmarks don't answer your feasibility question.** Clef's launch numbers (BANKING77, CLINC150, BFCL) are self-reported, and agent benchmarks are known to be gameable (a 2026 Berkeley study reward-hacked eight of them). Your own replay set is the only evidence that counts for your workflow.
- **Safety assumptions have a vocabulary.** The OWASP Top 10 for Agentic Applications (Dec 2025) gives a checklist to mine for safety assumptions: goal hijack, tool misuse, privilege abuse, memory poisoning, cascading failures.
- **Viability includes the eval set.** Decision models need a maintained, labeled set and periodic threshold re-picks. Someone has to own that work, so it is an assumption to test.

## 4. Build it

`code/main.py` ranks five assumptions for the incident example:

- `risk_score()` validates the 1–5 ranges and computes risk.
- `lint()` flags unfalsifiable wording, missing experiment fields, and pass and fail branches that lead to the same decision.
- `next_experiment()` picks the highest-risk *open*, *well-formed* assumption, and breaks ties by cheaper experiment.

```bash
python3 code/main.py
```

What to look for:

- The decision-model feasibility assumption ranks first (26) and its replay experiment is selected.
- The safety assumption (auto-rollback) ranks a close second, but its experiment deliberately **keeps a human in the loop**. Irreversibility shapes the test, not just the order.
- The "value" assumption is marked tested, yet it gets linted as unfalsifiable with a ritual experiment. Old evidence can be weak evidence.
- After the replay passes, the next experiment moves to safety.

## 5. Use it in production

- Keep `assumption-map.json` next to the outcome frame and workflow evidence. Link each assumption to a workflow step (Lesson 48).
- Review the map at every stage gate (Lesson 53). A tested assumption is replaced by its evidence and the decision it drove.
- Use your tracing platform's datasets feature (LangSmith, Langfuse, Phoenix, Braintrust) to store the replay set so the experiment can be repeated.
- **2026 update:** for any assumption about a router, guard, judge or stop condition, express the experiment as a System One eval: labeled `(state, question, answer)` rows, a coverage and precision target at a threshold, and the cost matrix from Lesson 52. That makes the "is the model good enough?" assumption concrete and repeatable.

## 6. Architect's lens

1. **Sequence by risk, staff by enthusiasm.** Let people build what excites them *after* the assumption that could kill the project has been tested.
2. **Coverage × precision is the real feasibility number.** A model that is 99% precise on 10% of cases is a different product from one that is 95% precise on 90%. Write both numbers in the assumption.
3. **Stop thresholds protect sunk cost from itself.** Decide in advance what result makes you stop. After the result, everyone will have reasons to continue.
4. **Irreversibility is mostly organizational.** Data migrations, public APIs, customer promises and headcount are hard to undo. Code usually isn't.
5. **An assumption map is a communication tool.** It is the clearest way to explain to an executive why the first month produces evidence instead of features.

## 7. Exercises

1. Write five assumptions for a feature you want to build, at least one per class.
2. Add a safety assumption your feature list left out, using an OWASP Agentic risk as the prompt.
3. Define a threshold that would make you stop the build entirely.
4. Replace a large experiment (a 30-day pilot) with a cheaper decisive test that answers the same question.
5. Compare the risk ranking with your current roadmap order and explain every mismatch to a peer.

## 8. Key terms

| Term | Meaning |
|---|---|
| Assumption | A condition that must be true for the build to be valuable, usable, feasible, viable and safe |
| Falsifiable | Stated so that an observation could prove it wrong |
| Irreversibility | Cost of learning the truth after commitment |
| Coverage | Share of cases the model answers above threshold |
| Decisive experiment | The cheapest test whose result changes the next decision |

## 9. Quick check

<details><summary>1. Why can a "tested" assumption still be a problem?</summary>Its evidence may be weak: unfalsifiable wording, no threshold, or a test whose outcome could not have changed the decision.</details>
<details><summary>2. Why does a decision-model feasibility assumption need two numbers?</summary>Coverage says how much work it takes off humans. Precision says how safe that automated share is. You need both for a business case.</details>
<details><summary>3. How does irreversibility change the experiment, not just the order?</summary>It pushes the test toward reversible forms: replay, shadow mode, or a human-approved suggestion instead of automatic action.</details>

## References

- Boehm, *A Spiral Model of Software Development and Enhancement*: https://dl.acm.org/doi/10.1145/12944.12948
- Dardenne, van Lamsweerde, Fickas, *Goal-Directed Requirements Acquisition*: https://doi.org/10.1016/0167-6423(93)90021-G
- OWASP Top 10 for Agentic Applications 2026 (summary): https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
- Cloudflare Clef on Workers AI: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
