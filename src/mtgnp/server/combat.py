"""Combat sub-state machine (RFC §9).

Steps: BEGIN_COMBAT -> DECLARE_ATTACKERS -> DECLARE_BLOCKERS ->
ASSIGN_DAMAGE_ORDER (only if an attacker is multi-blocked) ->
FIRST_STRIKE_DAMAGE (only if first/double strike present) -> COMBAT_DAMAGE ->
END_OF_COMBAT. Each opens a priority window (COMBAT_DAMAGE never rests in one
-- it resolves and transitions to END_OF_COMBAT on entry).

Two window kinds, not one (RFC §9.3-9.5 examples): a *declaration* grant, sent
to whichever player must next send a declaration PDU (AP for attackers, NAP for
blockers, AP for damage order), and a *response* window opened after a valid
declaration, which always goes to AP first (RFC §9.4's DECLARE_ATTACKERS
example). Getting these two swapped for DECLARE_BLOCKERS deadlocks the game:
NAP would never hold priority to send its own declaration.

`priority.handle_pass` delegates here (via `advance_step`) instead of calling
`turn.advance` whenever `state.phase` is one of `COMBAT_PHASES` --
`turn._PHASE_ORDER` has no entries for the combat sub-phases, so `turn.advance`
would raise/skip if it ever saw one.

Imports priority/turn/sba by module reference: priority.py imports this module
locally inside handle_pass (not at top level) to avoid a load-time cycle, same
pattern turn.py already uses to reach this module.
"""

from __future__ import annotations

from typing import Callable

import mtgnp.server.priority as priority
import mtgnp.server.sba as sba
import mtgnp.server.turn as turn
from mtgnp.protocol.errors import ErrorCode
from mtgnp.protocol.pdus import CombatDamageResult, DamageEvent, Error, PhaseTransition
from mtgnp.server.engine import Outbound
from mtgnp.server.state import (
    GameState,
    Lifecycle,
    Permanent,
    Phase,
    find_permanent,
    reset_end_of_turn,
)

# Every phase whose pass-pass close must route to advance_step rather than
# turn.advance. BEGIN_COMBAT is included: the pass that closes ITS window is
# what triggers entry into DECLARE_ATTACKERS. COMBAT_DAMAGE is excluded: it
# resolves and transitions on entry, so it never rests in a priority window
# and handle_pass never actually observes it.
COMBAT_PHASES = {
    Phase.BEGIN_COMBAT,
    Phase.DECLARE_ATTACKERS,
    Phase.DECLARE_BLOCKERS,
    Phase.ASSIGN_DAMAGE_ORDER,
    Phase.FIRST_STRIKE_DAMAGE,
    Phase.END_OF_COMBAT,
}


def _other(state: GameState, player_id: str) -> str:
    return next(pid for pid in state.players if pid != player_id)


def _transition(state: GameState, from_phase: str, to_phase: Phase) -> Outbound:
    state.seq_num += 1
    outbound = Outbound(
        recipient="ALL",
        pdu=PhaseTransition(
            seq_num=state.seq_num,
            from_phase=from_phase,
            to_phase=to_phase.value,
            active_player=state.active_player,
            turn=state.turn,
        ),
    )
    state.phase = to_phase
    return outbound


def _illegal_action(
    connection_id: str, state: GameState, message: str, pdu
) -> list[Outbound]:
    state.seq_num += 1
    return [
        Outbound(
            recipient=connection_id,
            pdu=Error(
                seq_num=state.seq_num,
                code=ErrorCode.ILLEGAL_ACTION.value,
                message=message,
                rejected_action=pdu.model_dump(),
            ),
        )
    ]


def _multiply_blocked_attackers(state: GameState) -> list[str]:
    counts: dict[str, int] = {}
    for attacker_id in state.blockers.values():
        counts[attacker_id] = counts.get(attacker_id, 0) + 1
    # state.attackers preserves declaration order -> deterministic worklist
    return [
        attacker_id
        for attacker_id in state.attackers
        if counts.get(attacker_id, 0) >= 2
    ]


def _needs_first_strike_step(state: GameState) -> bool:
    creature_ids = set(state.attackers) | set(state.blockers)
    for creature_id in creature_ids:
        permanent = find_permanent(state, creature_id)
        if permanent is not None and (
            permanent.first_strike or permanent.double_strike
        ):
            return True
    return False


def _apply_combat_damage(
    state: GameState, include: Callable[[Permanent], bool]
) -> list[dict]:
    """Deal damage from every creature for which `include(permanent)` is True:
    attackers to their blocker(s) (split per RFC §9's no-trample rule, decision
    5) or to the defending player if unblocked, and blockers back to their
    attacker at full power. `state.blockers` is the sole source of "blocked"
    status and is never recomputed from who's still alive, so an attacker
    whose blocker(s) died earlier this combat (e.g. in the FS step) still
    deals no damage to the player (RFC §9.7: no trample)."""
    events: list[dict] = []
    blockers_by_attacker: dict[str, list[str]] = {}
    for blocker_id, attacker_id in state.blockers.items():
        blockers_by_attacker.setdefault(attacker_id, []).append(blocker_id)

    for attacker_id, target in state.attackers.items():
        attacker = find_permanent(state, attacker_id)
        if attacker is None or not include(attacker):
            continue
        power = (attacker.power or 0) + attacker.power_bonus
        blocker_ids = blockers_by_attacker.get(attacker_id)
        if not blocker_ids:
            state.players[target].life -= power
            events.append({"source": attacker_id, "target": target, "amount": power})
            continue

        order = state.damage_order.get(attacker_id, blocker_ids)
        remaining = power
        for index, blocker_id in enumerate(order):
            blocker = find_permanent(state, blocker_id)
            if blocker is None:
                continue  # blocker already dead; its share of damage goes nowhere (no trample)
            if index == len(order) - 1:
                amount = remaining
            else:
                lethal_needed = max(
                    (blocker.toughness or 0)
                    + blocker.toughness_bonus
                    - (blocker.damage or 0),
                    0,
                )
                amount = min(remaining, lethal_needed)
            remaining = max(remaining - amount, 0)
            if amount > 0:
                blocker.damage = (blocker.damage or 0) + amount
                events.append(
                    {"source": attacker_id, "target": blocker_id, "amount": amount}
                )

    for blocker_id, attacker_id in state.blockers.items():
        blocker = find_permanent(state, blocker_id)
        if blocker is None or not include(blocker):
            continue
        attacker = find_permanent(state, attacker_id)
        if attacker is None:
            continue  # attacker already dead
        power = (blocker.power or 0) + blocker.power_bonus
        attacker.damage = (attacker.damage or 0) + power
        events.append({"source": blocker_id, "target": attacker_id, "amount": power})

    return events


def _enter_end_of_combat(state: GameState) -> list[Outbound]:
    outbounds = turn.broadcast_state(state)
    outbounds.append(_transition(state, state.phase.value, Phase.END_OF_COMBAT))
    outbounds += priority.grant(state, state.active_player)
    return outbounds


def begin_combat(state: GameState) -> list[Outbound]:
    """§9.2: turn.py has already broadcast the PRECOMBAT_MAIN -> BEGIN_COMBAT
    transition and set state.phase before calling this; just open the
    priority window."""
    return priority.grant(state, state.active_player)


def handle_declare_attackers(
    state: GameState, connection_id: str, pdu
) -> list[Outbound]:
    """§9.3. Atomic: any illegal entry rejects the whole PDU (same
    all-or-nothing pattern as turn.handle_play_land/handle_discard)."""
    errors = priority.validate_priority(state, connection_id, pdu)
    if errors:
        return errors

    ap = state.priority_holder
    opponent = _other(state, ap)
    battlefield = {p.id: p for p in state.players[ap].battlefield}

    for declared in pdu.attackers:
        permanent = battlefield.get(declared.creature_id)
        if (
            permanent is None
            or permanent.power is None
            or permanent.tapped
            or (
                permanent.summoning_sick
                and not (permanent.temp_haste or permanent.haste)
            )
            or declared.target != opponent
        ):
            return _illegal_action(
                connection_id, state, "Illegal attacker declaration.", pdu
            )

    for declared in pdu.attackers:
        battlefield[declared.creature_id].tapped = True
        state.attackers[declared.creature_id] = declared.target
        state.pending_attack_trigger.append((declared.creature_id, ap))

    if not pdu.attackers:
        return _enter_end_of_combat(state)

    outbounds = turn.broadcast_state(state)
    outbounds += priority.grant(state, ap)
    return outbounds


def handle_declare_blockers(
    state: GameState, connection_id: str, pdu
) -> list[Outbound]:
    """§9.4. Atomic (decision 3): tapped blocker, blocking_id not a declared
    attacker, or a creature blocking twice rejects the whole PDU."""
    errors = priority.validate_priority(state, connection_id, pdu)
    if errors:
        return errors

    nap = state.priority_holder
    battlefield = {p.id: p for p in state.players[nap].battlefield}
    attacker_ids = set(state.attackers)

    seen: set[str] = set()
    for declared in pdu.blockers:
        permanent = battlefield.get(declared.creature_id)
        if (
            permanent is None
            or permanent.tapped
            or declared.blocking_id not in attacker_ids
            or declared.creature_id in seen
        ):
            return _illegal_action(
                connection_id, state, "Illegal blocker declaration.", pdu
            )
        seen.add(declared.creature_id)

    state.blockers = {
        declared.creature_id: declared.blocking_id for declared in pdu.blockers
    }

    outbounds = turn.broadcast_state(state)
    outbounds += priority.grant(state, state.active_player)
    return outbounds


def handle_assign_damage_order(
    state: GameState, connection_id: str, pdu
) -> list[Outbound]:
    """§9.5: one PDU per multiply-blocked attacker. Re-grants AP a fresh
    declaration token after each ordering until the worklist
    (`pending_damage_order`) is empty, then opens the final response
    window (to AP, decision 4)."""
    errors = priority.validate_priority(state, connection_id, pdu)
    if errors:
        return errors

    ap = state.priority_holder
    if pdu.attacker_id not in state.pending_damage_order:
        return _illegal_action(
            connection_id, state, "Attacker is not awaiting a damage order.", pdu
        )

    actual_blockers = {
        bid for bid, aid in state.blockers.items() if aid == pdu.attacker_id
    }
    if set(pdu.blocker_order) != actual_blockers or len(pdu.blocker_order) != len(
        actual_blockers
    ):
        return _illegal_action(
            connection_id,
            state,
            "blocker_order must be a permutation of the attacker's blockers.",
            pdu,
        )

    state.damage_order[pdu.attacker_id] = pdu.blocker_order
    state.pending_damage_order.remove(pdu.attacker_id)

    if state.pending_damage_order:
        return priority.grant(state, ap)

    outbounds = turn.broadcast_state(state)
    outbounds += priority.grant(state, ap)
    return outbounds


def resolve_first_strike_damage(state: GameState) -> list[Outbound]:
    """§9.6: damage from first/double-strike creatures only, then SBA, then
    GSU (no COMBAT_DAMAGE_RESULT here -- only the regular damage step emits
    that), then a priority window. Rests at FIRST_STRIKE_DAMAGE; does not
    advance further itself."""
    _apply_combat_damage(state, lambda p: p.first_strike or p.double_strike)
    sba_out = sba.resolve(state)
    if state.lifecycle != Lifecycle.IN_GAME:
        return sba_out

    outbounds = turn.broadcast_state(state)
    outbounds += priority.grant(state, state.active_player)
    return outbounds


def resolve_combat_damage(state: GameState) -> list[Outbound]:
    """§9.7: damage from every creature except plain first-strikers (already
    dealt in the FS step), then SBA, then COMBAT_DAMAGE_RESULT, GSU,
    transition to END_OF_COMBAT, and a priority window -- in that order per
    the §9.7 example transcript."""
    events = _apply_combat_damage(
        state, lambda p: not p.first_strike or p.double_strike
    )

    before_ids = {p.id for player in state.players.values() for p in player.battlefield}
    sba_out = sba.resolve(state)
    after_ids = {p.id for player in state.players.values() for p in player.battlefield}
    died = sorted(before_ids - after_ids)

    state.seq_num += 1
    result = Outbound(
        recipient="ALL",
        pdu=CombatDamageResult(
            seq_num=state.seq_num,
            damage_events=[DamageEvent(**event) for event in events],
            life_totals={pid: player.life for pid, player in state.players.items()},
            creatures_died=died,
        ),
    )

    if state.lifecycle != Lifecycle.IN_GAME:
        return [result, *sba_out]

    return [result, *_enter_end_of_combat(state)]


def advance_step(state: GameState) -> list[Outbound]:
    """Both players passed with an empty stack while `state.phase` is one of
    `COMBAT_PHASES`: close that step's window and move to the next one."""
    current = state.phase

    if current == Phase.BEGIN_COMBAT:
        outbounds = [_transition(state, current.value, Phase.DECLARE_ATTACKERS)]
        return outbounds + priority.grant(state, state.active_player)

    if current == Phase.DECLARE_ATTACKERS:
        outbounds = [_transition(state, current.value, Phase.DECLARE_BLOCKERS)]
        return outbounds + priority.grant(state, _other(state, state.active_player))

    if current == Phase.DECLARE_BLOCKERS:
        multiply_blocked = _multiply_blocked_attackers(state)
        if multiply_blocked:
            state.pending_damage_order = multiply_blocked
            outbounds = [_transition(state, current.value, Phase.ASSIGN_DAMAGE_ORDER)]
            return outbounds + priority.grant(state, state.active_player)
        if _needs_first_strike_step(state):
            outbounds = [_transition(state, current.value, Phase.FIRST_STRIKE_DAMAGE)]
            return outbounds + resolve_first_strike_damage(state)
        outbounds = [_transition(state, current.value, Phase.COMBAT_DAMAGE)]
        return outbounds + resolve_combat_damage(state)

    if current == Phase.ASSIGN_DAMAGE_ORDER:
        if _needs_first_strike_step(state):
            outbounds = [_transition(state, current.value, Phase.FIRST_STRIKE_DAMAGE)]
            return outbounds + resolve_first_strike_damage(state)
        outbounds = [_transition(state, current.value, Phase.COMBAT_DAMAGE)]
        return outbounds + resolve_combat_damage(state)

    if current == Phase.FIRST_STRIKE_DAMAGE:
        outbounds = [_transition(state, current.value, Phase.COMBAT_DAMAGE)]
        return outbounds + resolve_combat_damage(state)

    # END_OF_COMBAT (§9.8): clear combat state and combat damage, hop to
    # POSTCOMBAT_MAIN directly (not reachable via turn._PHASE_ORDER lookup),
    # and grant AP priority there -- mirrors turn._finish_cleanup's manual
    # advance. permanent.damage is zeroed again by _finish_cleanup at the
    # true Cleanup step; that's not dead code, it also covers any non-combat
    # damage accrued afterward (RFC §9.8 is a deliberate double-clear).
    for player in state.players.values():
        for permanent in player.battlefield:
            reset_end_of_turn(permanent, damage_only=True)
    state.attackers = {}
    state.blockers = {}
    state.damage_order = {}
    state.pending_damage_order = []

    outbounds = turn.broadcast_state(state)
    outbounds.append(_transition(state, current.value, Phase.POSTCOMBAT_MAIN))
    outbounds += priority.grant(state, state.active_player)
    return outbounds
