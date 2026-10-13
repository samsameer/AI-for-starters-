from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

Context = dict[str, Any]
SkillFn = Callable[[Context], str]


@dataclass
class Skill:
    name: str
    description: str
    body: str
    fn: SkillFn
    version: int = 1
    tags: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    history: list[tuple[int, str]] = field(default_factory=list)

    def metadata(self) -> str:
        return f"{self.name}: {self.description}"


class SkillCycleError(Exception):
    pass


NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


class SkillLibrary:
    def __init__(self) -> None:
        self.skills: dict[str, Skill] = {}
        self.pins: dict[str, dict[str, int]] = {}
        self.versions: dict[tuple[str, int], Skill] = {}

    def register(self, skill: Skill) -> str:
        if not NAME_PATTERN.match(skill.name):
            raise ValueError(f"invalid skill name {skill.name!r}")
        for other in self.skills.values():
            if other.name != skill.name and words(other.description) == words(skill.description):
                return f"dedup: {skill.name} collapses into {other.name}"
        existing = self.skills.get(skill.name)
        if existing is not None:
            skill.version = existing.version + 1
            skill.history = existing.history + [(existing.version, existing.body)]
        self.skills[skill.name] = skill
        self.versions[(skill.name, skill.version)] = skill
        self.pins[skill.name] = {dep: self.skills[dep].version for dep in skill.depends_on if dep in self.skills}
        verb = "refined" if existing else "registered"
        return f"{verb} {skill.name} v{skill.version} pins={self.pins[skill.name]}"

    def catalog(self) -> list[str]:
        return [s.metadata() for s in self.skills.values()]

    def search(self, query: str, top_k: int = 3, tag: str | None = None) -> list[tuple[float, Skill]]:
        query_words = words(query)
        scored: list[tuple[float, Skill]] = []
        for skill in self.skills.values():
            if tag and tag not in skill.tags:
                continue
            doc_words = words(f"{skill.name.replace('-', ' ')} {skill.description}")
            shared = query_words & doc_words
            if shared:
                scored.append((len(shared) / len(query_words | doc_words), skill))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return scored[:top_k]

    def resolve(self, name: str, version: int | None = None) -> Skill:
        if version is not None:
            return self.versions[(name, version)]
        return self.skills[name]

    def plan(self, name: str) -> list[tuple[str, int]]:
        order: list[tuple[str, int]] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(skill_name: str, version: int | None, path: list[str]) -> None:
            if skill_name in visiting:
                raise SkillCycleError(" -> ".join(path + [skill_name]))
            if skill_name in done:
                return
            visiting.add(skill_name)
            skill = self.resolve(skill_name, version)
            pinned = self.pins.get(skill_name, {}) if version is None else {}
            for dep in skill.depends_on:
                visit(dep, pinned.get(dep), path + [skill_name])
            visiting.discard(skill_name)
            done.add(skill_name)
            order.append((skill_name, skill.version))

        visit(name, None, [])
        return order

    def execute(self, name: str) -> tuple[bool, list[str], Context]:
        context: Context = {"resources": {}, "inventory": []}
        log: list[str] = []
        for skill_name, version in self.plan(name):
            skill = self.resolve(skill_name, version)
            try:
                log.append(f"ran {skill_name}@{version}: {skill.fn(context)}")
            except Exception as error:
                log.append(f"error in {skill_name}@{version}: {error}")
                return False, log, context
        return True, log, context


def mine_ore(context: Context) -> str:
    context["resources"]["ore"] = context["resources"].get("ore", 0) + 3
    return "+3 ore"


def gather_sticks(context: Context) -> str:
    context["resources"]["stick"] = context["resources"].get("stick", 0) + 2
    return "+2 stick"


def place_table(context: Context) -> str:
    context["has_table"] = True
    return "crafting table placed"


def craft_pickaxe(context: Context) -> str:
    if not context.get("has_table"):
        raise RuntimeError("no crafting table")
    resources = context["resources"]
    if resources.get("ore", 0) < 3 or resources.get("stick", 0) < 2:
        raise RuntimeError(f"need ore>=3 stick>=2, have {resources}")
    resources["ore"] -= 3
    resources["stick"] -= 2
    context["inventory"].append("iron_pickaxe")
    return "crafted iron_pickaxe"


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def main() -> None:
    library = SkillLibrary()

    section("1. register primitive skills")
    primitives = [
        Skill("mine-ore", "mine iron ore from nearby rock", "call mine(3) and check inventory", mine_ore, tags=("gather",)),
        Skill("gather-sticks", "gather sticks from trees or planks", "call gather('stick', 2)", gather_sticks, tags=("gather",)),
        Skill("place-crafting-table", "place a crafting table at the current position", "call place('table')", place_table, tags=("setup",)),
    ]
    for skill in primitives:
        print("  " + library.register(skill))
    print("  " + library.register(Skill("mine-iron", "mine iron ore from nearby rock", "dup", mine_ore)))

    section("2. compose v1 of a higher-order skill (missing a dependency)")
    print("  " + library.register(Skill(
        "craft-iron-pickaxe", "craft an iron pickaxe using ore and a crafting table",
        "steps: mine-ore, place-crafting-table, craft", craft_pickaxe,
        tags=("craft",), depends_on=("mine-ore", "place-crafting-table"),
    )))

    section("3. progressive disclosure: catalog first, body on demand")
    catalog_text = "\n".join(library.catalog())
    print(f"  catalog tokens (always loaded): {token_estimate(catalog_text)}")
    for score, skill in library.search("I need a pickaxe made of iron"):
        print(f"  {score:.2f}  {skill.name}@{skill.version}  body tokens if loaded: {token_estimate(skill.body)}")

    section("4. execute v1 and read the failure signal")
    ok, log, _ = library.execute("craft-iron-pickaxe")
    for line in log:
        print(f"  {line}")
    print(f"  success={ok}")

    section("5. refine to v2 using the error as feedback")
    print("  " + library.register(Skill(
        "craft-iron-pickaxe", "craft an iron pickaxe using ore, sticks and a crafting table",
        "steps: mine-ore, gather-sticks, place-crafting-table, craft", craft_pickaxe,
        tags=("craft",), depends_on=("mine-ore", "gather-sticks", "place-crafting-table"),
    )))
    ok, log, context = library.execute("craft-iron-pickaxe")
    for line in log:
        print(f"  {line}")
    print(f"  success={ok} inventory={context['inventory']}")

    section("6. version pinning protects parents from silent upgrades")
    print("  " + library.register(Skill("mine-ore", "mine iron ore from nearby rock quickly", "call mine(5)", mine_ore, tags=("gather",))))
    print(f"  plan for craft-iron-pickaxe: {library.plan('craft-iron-pickaxe')}")

    section("7. cycle detection on compose")
    library.register(Skill("skill-a", "alpha step", "a", mine_ore, depends_on=("skill-b",)))
    library.register(Skill("skill-b", "beta step", "b", mine_ore, depends_on=("skill-a",)))
    try:
        library.plan("skill-a")
    except SkillCycleError as error:
        print(f"  rejected cycle: {error}")

    section("8. invalid names are refused at write time")
    try:
        library.register(Skill("Craft Pickaxe!", "bad", "x", mine_ore))
    except ValueError as error:
        print(f"  {error}")

    print("\nloop: retrieve -> compose -> execute -> feed error back -> new version, pinned.")


if __name__ == "__main__":
    main()
