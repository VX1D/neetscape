"""Compile a profile's searches into board requests (pure, no I/O).

Each board turns a search into requests according to its capabilities. Identical requests coming
from different searches are fetched once: filters are evaluated locally for every search anyway.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .boards import REGISTRY
from .boards.base import Request
from .profile import Profile


@dataclass
class Plan:
    requests: list[Request] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_board(self) -> dict[str, list[Request]]:
        out: dict[str, list[Request]] = {}
        for r in self.requests:
            out.setdefault(r.board, []).append(r)
        return out


def plan(profile: Profile) -> Plan:
    p = Plan()
    seen: set[str] = set()
    for s in profile.searches:
        for name in profile.boards:
            reqs, warnings = REGISTRY[name].requests(s)
            p.warnings += warnings
            for r in reqs:
                if r.key not in seen:
                    seen.add(r.key)
                    p.requests.append(r)
    return p


def describe(p: Plan) -> str:
    lines = []
    for board, reqs in p.by_board().items():
        b = REGISTRY[board]
        lines.append(f"{board} ({b.caps.transport}, up to {b.caps.max_pages} pages each): {len(reqs)} request(s)")
        for r in reqs:
            sent = ", ".join(f"{k}={v}" for k, v in r.params.items()) or "-"
            lines.append(f"    [{r.search_id}] keyword={r.keyword or '*'}  sent: {sent}  board filters: {', '.join(sorted(r.pushed)) or 'none'}")
    if p.warnings:
        lines.append("warnings:")
        lines += [f"    {w}" for w in p.warnings]
    lines.append("Every search condition is also checked locally after crawling.")
    return "\n".join(lines)
