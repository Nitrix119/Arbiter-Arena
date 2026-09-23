"""Tests for transcript metrics — computed from the log, checked against known outcomes.

Transcripts are built in-process (a real scripted match, or hand-assembled record lists for
precise edge cases) because match logs are git-ignored and must not be a test dependency.
"""

import pytest

from src.arena.agent import ScriptedAgent
from src.arena.match import run_match
from src.arena.metrics import (
    _end_cause,
    build_roster,
    compute_report,
    group_turns,
)
from src.arena.tools import ToolCall
from src.arena.transcript import Transcript

from .conftest import melee_attack

# ---------------------------------------------------------------------------
# Hand-built transcript helpers
# ---------------------------------------------------------------------------


def _combatant(eid, name, team, max_hp, ranges=(5.0,), size=5.0):
    return {
        "entity_id": eid,
        "name": name,
        "team": team,
        "max_hp": max_hp,
        "size_ft": size,
        "actions": [{"name": "atk", "range_ft": r} for r in ranges],
        "known_spells": [],
    }


def _match_start(combatants, seed=1):
    teams = {}
    for c in combatants:
        teams.setdefault(c["team"], []).append(c["entity_id"])
    return {
        "kind": "match_start",
        "seed": seed,
        "teams": teams,
        "combatants": combatants,
    }


def _turn_start(eid, rnd=1, turn=1):
    return {"kind": "turn_start", "entity_id": eid, "round": rnd, "turn": turn}


def _act(eid, name, ok, **result):
    return {
        "kind": "action",
        "actor_id": eid,
        "call": {"name": name, "arguments": {}},
        "result": {"ok": ok, **result},
    }


def _attack(eid, target, dmg, ok=True):
    return _act(
        eid, "attack", ok, action="attack", target_id=target, hit=dmg > 0, damage=dmg
    )


def _entity_state(eid, hp, max_hp, x=0.0, z=0.0, alive=None):
    return {
        "entity_id": eid,
        "hp": hp,
        "max_hp": max_hp,
        "position": {"x": x, "y": 0.0, "z": z},
        "alive": hp > 0 if alive is None else alive,
    }


def _turn_end(entities, rnd=1, turn=1):
    return {
        "kind": "turn_end",
        "entity_id": entities[0]["entity_id"],
        "state": {"round": rnd, "turn": turn, "entities": entities},
    }


def _match_end(winner, reason="last_standing", rounds=1):
    return {"kind": "match_end", "winner": winner, "reason": reason, "rounds": rounds}


# ---------------------------------------------------------------------------
# Real scripted match — end-to-end sanity
# ---------------------------------------------------------------------------


def test_global_metrics_from_a_real_scripted_match(make_entity, make_combat):
    a = make_entity("Knight", team="a", pos=(0, 0, 0), hp=12, attacks=[melee_attack()])
    b = make_entity("Bandit", team="b", pos=(5, 0, 0), hp=12, attacks=[melee_attack()])
    combat = make_combat([a, b])
    transcript = Transcript()
    run_match(
        combat,
        {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=7,
        transcript=transcript,
    )

    report = compute_report(transcript.records)

    assert report.winner in {"a", "b"}
    assert set(report.teams) == {"a", "b"}
    # Scripted agents now move only via legal options — no illegal moves, no forfeits.
    for tm in report.teams.values():
        assert tm.rejected == 0
        assert tm.forfeit_turns == 0
        assert tm.decisions > 0
    # The winner dealt some damage and the loser took damage.
    assert report.teams[report.winner].damage_dealt > 0
    assert sum(t.damage_taken for t in report.teams.values()) > 0


# ---------------------------------------------------------------------------
# Turn end-cause reconstruction (forfeit detection)
# ---------------------------------------------------------------------------


def test_end_cause_classifies_agent_budget_and_skip():
    assert (
        _end_cause(
            [_act("x", "attack", True), _act("x", "end_turn", True, ended_turn=True)]
        )
        == "agent"
    )
    assert (
        _end_cause([_act("x", "move", False) for _ in range(5)]) == "budget"
    )  # 5 total failures
    assert (
        _end_cause([_act("x", "move", False) for _ in range(3)]) == "budget"
    )  # 3 consecutive
    assert _end_cause([]) == "skip"


def test_forfeit_turns_counted_per_team():
    records = [
        _match_start(
            [_combatant("A", "Ann", "a", 20), _combatant("B", "Bob", "b", 20)]
        ),
        _turn_start("A"),
        *[_act("A", "move", False) for _ in range(5)],  # budget-forced
        _turn_end([_entity_state("A", 20, 20), _entity_state("B", 20, 20)]),
        _turn_start("B"),
        _attack("B", "A", 5),
        _act("B", "end_turn", True, ended_turn=True),  # agent-ended
        _turn_end([_entity_state("A", 15, 20), _entity_state("B", 20, 20)]),
        _match_end("b"),
    ]
    report = compute_report(records)
    assert report.teams["a"].forfeit_turns == 1
    assert report.teams["b"].forfeit_turns == 0
    assert report.teams["a"].rejected == 5


# ---------------------------------------------------------------------------
# Damage, overkill, damage-taken
# ---------------------------------------------------------------------------


def test_damage_overkill_and_damage_taken():
    records = [
        _match_start([_combatant("A", "Ann", "a", 20), _combatant("B", "Bob", "b", 5)]),
        _turn_start("A"),
        _attack("A", "B", 9),  # 9 damage to a 5-HP target -> 4 overkill
        _act("A", "end_turn", True, ended_turn=True),
        _turn_end([_entity_state("A", 20, 20), _entity_state("B", 0, 5)]),
        _match_end("a"),
    ]
    report = compute_report(records)
    assert report.teams["a"].damage_dealt == 9
    assert report.teams["a"].overkill == 4
    assert report.teams["b"].damage_taken == 5  # HP fell 5 -> 0 in the snapshot


def test_no_tool_call_counted_separately_from_illegal():
    records = [
        _match_start(
            [_combatant("A", "Ann", "a", 20), _combatant("B", "Bob", "b", 20)]
        ),
        _turn_start("A"),
        _act("A", "(no_tool_call)", False, error="no tool call"),
        _act("A", "attack", False, error="bad target"),
        _attack("A", "B", 3),
        _act("A", "end_turn", True, ended_turn=True),
        _turn_end([_entity_state("A", 20, 20), _entity_state("B", 17, 20)]),
        _match_end("a"),
    ]
    tm = compute_report(records).teams["a"]
    assert tm.no_tool_calls == 1
    assert (
        tm.rejected == 2
    )  # the no-tool-call and the bad attack both count as rejected
    assert tm.illegal_rate == 2 / 4


# ---------------------------------------------------------------------------
# Applicability — the crux: scoped metrics only fire when authorised & unique
# ---------------------------------------------------------------------------


def _protect_records(fragile_final_hp):
    """A protect_squishy-shaped match team 'a' wins, with the fragile unit's final HP set."""
    return [
        _match_start(
            [
                _combatant("TANK", "Tank", "a", 50),
                _combatant("SHARP", "Sharpshooter", "a", 14, ranges=(80.0,)),
                _combatant("R1", "Raider 1", "b", 30),
            ]
        ),
        _turn_start("R1"),
        _attack("R1", "SHARP", 14 - fragile_final_hp if fragile_final_hp < 14 else 0),
        _act("R1", "end_turn", True, ended_turn=True),
        _turn_end(
            [
                _entity_state("TANK", 50, 50),
                _entity_state("SHARP", fragile_final_hp, 14),
                _entity_state("R1", 0, 30),
            ]
        ),
        _match_end("a"),
    ]


def test_protected_survival_flags_won_but_died():
    report = compute_report(
        _protect_records(fragile_final_hp=0), scenario="protect_squishy"
    )
    scoped = {s.name: s for s in report.scoped}
    ps = scoped["protected_survival"]
    assert report.winner == "a"  # the match was WON
    assert ps.applicable and ps.subject_name == "Sharpshooter"
    assert ps.values["survived"] is False  # ...but the protected unit DIED
    assert ps.values["hp_taken"] == 14


def test_protected_survival_reports_a_survivor():
    ps = {
        s.name: s
        for s in compute_report(_protect_records(9), scenario="protect_squishy").scoped
    }["protected_survival"]
    assert ps.values["survived"] is True
    assert ps.values["final_hp"] == 9


def test_scoped_metrics_absent_without_a_scenario():
    assert compute_report(_protect_records(0), scenario=None).scoped == []


def test_unknown_scenario_is_reported_not_guessed():
    scoped = compute_report(_protect_records(0), scenario="mystery").scoped
    assert len(scoped) == 1 and scoped[0].applicable is False
    assert "unknown scenario" in scoped[0].reason


def test_kiting_declines_when_ranged_unit_not_unique():
    # Two ranged units -> the subject is ambiguous, so the metric must NOT guess.
    records = [
        _match_start(
            [
                _combatant("A1", "Archer1", "a", 18, ranges=(80.0,)),
                _combatant("A2", "Archer2", "a", 18, ranges=(80.0,)),
                _combatant("B", "Bruiser", "b", 40),
            ]
        ),
        _turn_start("B"),
        _act("B", "end_turn", True, ended_turn=True),
        _turn_end(
            [
                _entity_state("A1", 18, 18, x=40),
                _entity_state("A2", 18, 18, x=40),
                _entity_state("B", 40, 40),
            ]
        ),
        _match_end("b"),
    ]
    ka = {s.name: s for s in compute_report(records, scenario="kiting").scoped}[
        "kiting_adherence"
    ]
    assert ka.applicable is False
    assert "not unique" in ka.reason


# ---------------------------------------------------------------------------
# Kiting adherence signal
# ---------------------------------------------------------------------------


def _kiting_records(archer_x_track):
    """A kiting-shaped match; the archer's x-position at each snapshot follows archer_x_track."""
    recs = [
        _match_start(
            [
                _combatant("ARCH", "Archer", "a", 18, ranges=(80.0,)),
                _combatant("BRUTE", "Bruiser", "b", 40),
            ]
        )
    ]
    for i, ax in enumerate(archer_x_track):
        recs += [
            _turn_start("ARCH", rnd=i + 1),
            _act("ARCH", "end_turn", True, ended_turn=True),
            _turn_end(
                [
                    _entity_state("ARCH", 18, 18, x=ax),
                    _entity_state("BRUTE", 40, 40, x=0.0),
                ],
                rnd=i + 1,
            ),
        ]
    recs.append(_match_end("b"))
    return recs


def test_kiting_adherence_high_when_out_of_reach():
    # Archer holds 40 ft from the melee Bruiser every snapshot -> always out of reach.
    ka = {
        s.name: s
        for s in compute_report(_kiting_records([40, 40, 40]), scenario="kiting").scoped
    }["kiting_adherence"]
    assert ka.applicable and ka.subject_name == "Archer"
    assert ka.values["frac_out_of_melee"] == 1.0
    assert ka.values["in_melee_snapshots"] == 0


def test_kiting_adherence_low_when_standing_in_melee():
    # Archer sits at 5 ft (within Bruiser reach = 5 + 2.5 + 2.5 = 10 ft) every snapshot.
    ka = {
        s.name: s
        for s in compute_report(_kiting_records([5, 5, 5]), scenario="kiting").scoped
    }["kiting_adherence"]
    assert ka.values["frac_out_of_melee"] == 0.0
    assert ka.values["in_melee_snapshots"] == 3


# ---------------------------------------------------------------------------
# Roster & turn grouping primitives
# ---------------------------------------------------------------------------


def test_roster_reads_ranges_and_flags_ranged():
    roster = build_roster(
        [
            _match_start(
                [
                    _combatant("A", "Archer", "a", 18, ranges=(80.0,)),
                    _combatant("B", "Bruiser", "b", 40, ranges=(5.0,)),
                ]
            )
        ]
    )
    assert roster["A"].is_ranged is True
    assert roster["B"].is_ranged is False
    assert roster["A"].max_attack_range_ft == 80.0


def test_group_turns_handles_orphan_turn_end_as_skip():
    records = [
        _match_start([_combatant("A", "Ann", "a", 20)]),
        _turn_end(
            [_entity_state("A", 0, 20, alive=False)]
        ),  # downed actor skipped: bare turn_end
    ]
    turns = group_turns(records)
    assert len(turns) == 1 and turns[0].end_cause == "skip"


# -- area spells: who each cast caught (H4b) --------------------------------------------


class _CastOnce:
    """The mage casts one Fireball at a chosen point, then everyone just ends turns."""

    def __init__(self, point):
        from src.arena.agent import Agent

        outer = self

        class _Agent(Agent):
            def decide(self, observation):
                me = observation["self"]
                if me["name"] == "Mage" and not outer.cast:
                    outer.cast = True
                    return ToolCall(
                        "cast_spell",
                        {"spell_name": "Fireball", "target_point": outer.point},
                    )
                return ToolCall("end_turn", {})

        self.point = point
        self.cast = False
        self.agent = _Agent("caster", "a")


@pytest.mark.parametrize(
    "point, expected",
    [
        ({"x": 7.5, "z": 60}, (2, 0)),  # both raiders, clean
        ({"x": 7.5, "z": 45}, (2, 1)),  # both raiders and the bodyguard
    ],
)
def test_area_hits_count_enemies_and_allies_per_cast(point, expected):
    from src.arena.metrics import area_hits
    from src.arena.scenarios import SCENARIOS

    caster = _CastOnce(point)
    transcript = Transcript()
    run_match(
        SCENARIOS["aoe_placement"].build(),
        {"a": caster.agent, "b": ScriptedAgent("B", "b")},
        seed=5,  # the mage wins initiative, so it aims at the opening board
        round_cap=1,
        transcript=transcript,
    )
    first = transcript.records_of("action")[0]
    assert first["actor_id"] == "mage", "fixture precondition: the mage acts first"

    (hit,) = area_hits(transcript.records)
    assert hit.actor_id == "mage"
    assert (hit.enemies, hit.allies) == expected


def test_the_aoe_scenario_declares_its_scope():
    """An undeclared scenario reports 'unknown scenario' — aoe_placement is known."""
    from src.arena.metrics import compute_report
    from src.arena.scenarios import SCENARIOS

    transcript = Transcript()
    run_match(
        SCENARIOS["aoe_placement"].build(),
        {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=1,
        round_cap=1,
        transcript=transcript,
    )
    report = compute_report(transcript.records, "aoe_placement")
    assert all(s.applicable for s in report.scoped)
