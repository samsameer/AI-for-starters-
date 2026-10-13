from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Box:
    eid: str
    x: int
    y: int
    w: int = 120
    h: int = 32

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


PRICES = {"headphones": 199, "keyboard": 129, "mouse": 59}

LAYOUT = [
    Box("add:headphones", 40, 200),
    Box("add:keyboard", 40, 240),
    Box("add:mouse", 40, 280),
    Box("remove:keyboard", 200, 240),
    Box("checkout", 40, 400),
]


@dataclass
class ShopApp:
    cart: dict[str, int] = field(default_factory=dict)
    orders: list[dict[str, int]] = field(default_factory=list)

    def element_at(self, x: int, y: int) -> str | None:
        return next((b.eid for b in LAYOUT if b.contains(x, y)), None)

    def click(self, x: int, y: int) -> str:
        eid = self.element_at(x, y)
        if eid is None:
            return "nothing"
        verb, _, item = eid.partition(":")
        if verb == "add":
            self.cart[item] = self.cart.get(item, 0) + 1
        elif verb == "remove":
            self.cart.pop(item, None)
        elif verb == "checkout" and self.cart:
            self.orders.append(dict(self.cart))
            self.cart.clear()
        return eid


@dataclass(frozen=True)
class Step:
    intended: str
    x: int
    y: int


def at(eid: str, dx: int = 0, dy: int = 0) -> Step:
    box = next(b for b in LAYOUT if b.eid == eid)
    cx, cy = box.center
    return Step(eid, cx + dx, cy + dy)


@dataclass(frozen=True)
class Task:
    tid: str
    goal: str
    gold: tuple[str, ...]
    agent_steps: tuple[Step, ...]
    agent_final_message: str
    state_check: Callable[[ShopApp], bool]


TASKS = [
    Task("buy_headphones", "buy the headphones", ("add:headphones", "checkout"),
         (at("add:headphones"), at("checkout")), "Order placed.",
         lambda app: app.orders == [{"headphones": 1}]),
    Task("buy_bundle", "buy keyboard and mouse together", ("add:keyboard", "add:mouse", "checkout"),
         (at("add:keyboard"), at("remove:keyboard"), at("add:keyboard"), at("add:mouse"), at("checkout")),
         "Order placed.", lambda app: app.orders == [{"keyboard": 1, "mouse": 1}]),
    Task("buy_mouse", "buy only the mouse", ("add:mouse", "checkout"),
         (at("add:mouse", dy=-30), at("remove:keyboard"), at("add:mouse"), at("checkout")),
         "Order placed.", lambda app: app.orders == [{"mouse": 1}]),
    Task("buy_mouse_fast", "buy only the mouse, quickly", ("add:mouse", "checkout"),
         (at("add:mouse", dy=-30), at("checkout")),
         "Order placed.", lambda app: app.orders == [{"mouse": 1}]),
    Task("buy_keyboard", "buy the keyboard", ("add:keyboard", "checkout"),
         (at("add:keyboard"),), "Order placed for the keyboard.",
         lambda app: app.orders == [{"keyboard": 1}]),
]


@dataclass
class Result:
    tid: str
    strict_ok: bool
    lenient_ok: bool
    steps: int
    gold: int
    grounding_misses: int
    failure: str


def run(task: Task) -> Result:
    app = ShopApp()
    misses = 0
    for step in task.agent_steps:
        hit = app.click(step.x, step.y)
        if hit != step.intended:
            misses += 1
    strict_ok = task.state_check(app)
    lenient_ok = "order placed" in task.agent_final_message.lower()
    if strict_ok:
        failure = "-"
    elif misses:
        failure = "grounding"
    else:
        failure = "planning"
    return Result(task.tid, strict_ok, lenient_ok, len(task.agent_steps), len(task.gold), misses, failure)


def main() -> None:
    print("WebArena/OSWorld-style harness: pixel actions, state-based evaluation, gold trajectories\n")
    results = [run(t) for t in TASKS]
    for r in results:
        eff = r.steps / r.gold
        print(f"  {r.tid:15} strict={str(r.strict_ok):5} lenient={str(r.lenient_ok):5} "
              f"steps={r.steps} gold={r.gold} over_gold={eff:.2f}x misses={r.grounding_misses} failure={r.failure}")
    strict = sum(r.strict_ok for r in results)
    lenient = sum(r.lenient_ok for r in results)
    solved = [r for r in results if r.strict_ok]
    mean_eff = sum(r.steps / r.gold for r in solved) / len(solved)
    print(f"\n  success (state check)        {strict}/{len(results)}")
    print(f"  success (final-message check) {lenient}/{len(results)}  <- what a gameable evaluator reports")
    print(f"  mean steps over gold on solved tasks {mean_eff:.2f}x")
    print(f"  failures: grounding={sum(r.failure == 'grounding' for r in results)} planning={sum(r.failure == 'planning' for r in results)}")
    print("\nscore the world state, not the agent's claim; report efficiency next to success")


if __name__ == "__main__":
    main()
