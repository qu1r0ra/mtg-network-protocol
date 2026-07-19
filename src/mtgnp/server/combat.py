"""Combat sub-state machine (RFC §9).

Steps: BEGIN_COMBAT -> DECLARE_ATTACKERS -> DECLARE_BLOCKERS ->
ASSIGN_DAMAGE_ORDER (only if an attacker is multi-blocked) ->
FIRST_STRIKE_DAMAGE (only if first/double strike present) -> COMBAT_DAMAGE ->
END_OF_COMBAT. Each opens a priority window.

Rules enforced: summoning-sick/tapped creatures cannot attack (ILLEGAL_ACTION);
declaring an attacker taps it; blocking does not tap; no trample (blocked attacker
deals damage only to blockers); double-strike deals in both damage steps; SBAs
checked after each damage step. Broadcasts COMBAT_DAMAGE_RESULT.
"""

from __future__ import annotations

# handle_declare_attackers(state, player_id, pdu) -> [...]   # §9.3 (empty = no attack)
# handle_declare_blockers(state, player_id, pdu) -> [...]    # §9.4
# handle_assign_damage_order(state, player_id, pdu) -> [...] # §9.5
# resolve_first_strike_damage(state) -> [...]                # §9.6
# resolve_combat_damage(state) -> [...]                      # §9.7 COMBAT_DAMAGE_RESULT
