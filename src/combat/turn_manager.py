"""Turn and round lifecycle management."""

from typing import Hashable, Iterable, List, Optional, Set

from src.models.condition import ConditionType
from src.models.entity import Entity
from .event_bus import EventBus
from .event_data import RoundEventData, TurnEventData
from .events import EventType
from .initiative import InitiativeTracker

# Conditions that prevent an entity from taking any meaningful action.
# Entities with any of these conditions have their turn skipped automatically.
_SKIP_CONDITIONS: frozenset[ConditionType] = frozenset(
    {
        ConditionType.UNCONSCIOUS,
        ConditionType.INCAPACITATED,
        ConditionType.PARALYZED,
        ConditionType.STUNNED,
        ConditionType.PETRIFIED,
    }
)


def _should_skip(entity: Entity) -> bool:
    """Return True if the entity's conditions prevent them from acting."""
    return any(c.condition_type in _SKIP_CONDITIONS for c in entity.conditions)


def sides_standing(combatants: Iterable[Entity]) -> int:
    """How many sides still have a living creature.

    A fight is over when one side is left, however many of it survive: a real combat
    ends the moment the last enemy falls. A creature with no team fights for itself,
    so a free-for-all goes on while two creatures stand.
    """
    sides: Set[Hashable] = set()
    for entity in combatants:
        if entity.is_alive():
            sides.add(
                entity.team if entity.team is not None else ("", entity.entity_id)
            )
    return len(sides)


class TurnManager:
    """Manages turn advancement, round tracking, and dead-entity skipping."""

    def __init__(
        self,
        event_bus: EventBus,
        initiative_tracker: InitiativeTracker,
        combatants: List[Entity],
    ) -> None:
        self._event_bus = event_bus
        self._initiative_tracker = initiative_tracker
        self._combatants = combatants
        self.round: int = 0
        self.turn: int = 0

    def start(self) -> None:
        """Begin the first round."""
        self.round = 1
        self.turn = 1
        self._event_bus.emit(
            EventType.ROUND_START, RoundEventData(round_num=self.round)
        )
        current = self._initiative_tracker.get_current_entity()
        # Combat cannot start without combatants, so initiative is never empty.
        assert current is not None, "Cannot start a turn with an empty initiative order"
        self._event_bus.emit(
            EventType.TURN_START,
            TurnEventData(
                entity=current,
                round_num=self.round,
                turn_num=self.turn,
            ),
        )

    def end_turn(self) -> bool:
        """End the current turn and advance.

        Returns:
            True if combat should continue, False once at most one side is left
            (:func:`sides_standing`).
        """
        current = self._initiative_tracker.get_current_entity()
        # Combat cannot start without combatants, so initiative is never empty.
        assert current is not None, "Cannot end a turn with an empty initiative order"
        self._event_bus.emit(
            EventType.TURN_END,
            TurnEventData(entity=current, round_num=self.round, turn_num=self.turn),
        )
        # Checked before advancing: a fight decided this turn (an end-of-turn effect
        # included) must not start another turn or round.
        if sides_standing(self._combatants) <= 1:
            return False

        next_entity = self._initiative_tracker.next_turn()
        self.turn += 1

        if self._initiative_tracker.current_turn_index == 0:
            self._event_bus.emit(
                EventType.ROUND_END, RoundEventData(round_num=self.round)
            )
            self.round += 1
            self.turn = 1
            self._event_bus.emit(
                EventType.ROUND_START, RoundEventData(round_num=self.round)
            )

        if sides_standing(self._combatants) <= 1:
            return False

        # Skip entities whose conditions prevent acting (unconscious, stunned, etc.).
        # Guard against the degenerate case where every remaining entity is
        # incapacitated.
        skips = 0
        max_skips = len(self._combatants)
        while next_entity is not None and _should_skip(next_entity):
            if skips >= max_skips:
                return False  # All entities are incapacitated; end combat.
            next_entity = self._initiative_tracker.next_turn()
            self.turn += 1
            skips += 1
            if self._initiative_tracker.current_turn_index == 0:
                self._event_bus.emit(
                    EventType.ROUND_END, RoundEventData(round_num=self.round)
                )
                self.round += 1
                self.turn = 1
                self._event_bus.emit(
                    EventType.ROUND_START, RoundEventData(round_num=self.round)
                )

        # The loop above only exits on a non-skipping entity; next_turn() returns
        # None only for an empty initiative order, which cannot occur here.
        assert next_entity is not None, "Cannot start a turn with no next entity"
        self._event_bus.emit(
            EventType.TURN_START,
            TurnEventData(entity=next_entity, round_num=self.round, turn_num=self.turn),
        )
        # A start-of-turn effect can decide the fight too.
        return sides_standing(self._combatants) > 1

    def get_current_entity(self) -> Optional[Entity]:
        """Get the entity whose turn it is."""
        return self._initiative_tracker.get_current_entity()
