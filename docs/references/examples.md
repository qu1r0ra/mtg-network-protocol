**MTGNP RFC v3**

Sample PDU Exchange — LOBBY \+ GAME_SETUP \+ MULLIGAN \+ IN_GAME \+ GAME_OVER

# **1\. LOBBY State**

Both players connect and declare their decks. The server waits until it has received a valid PLAYER_READY from each player before advancing.

## **Step 1 \- Player 1 sends PLAYER_READY**

**C \-\> S**

| { "type": "PLAYER_READY", "seq_num": 1, "player_id": "player_1", "deck_list": \[ "lightning_bolt_001", "lightning_bolt_002", "lightning_bolt_003", "shock_001", "shock_002", "goblin_guide_001", "mountain_001", "mountain_002" \] } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 2 \- Server acknowledges, waits for Player 2**

**S \-\> P1**

| { "type": "GAME_STATE_UPDATE", "seq_num": 1, "state": { "phase": "LOBBY", "players_ready": 1, "waiting_for": \["player_2"\] } } |
| :------------------------------------------------------------------------------------------------------------------------------ |

## **Step 3 \- Player 2 sends PLAYER_READY**

**C \-\> S**

| { "type": "PLAYER_READY", "seq_num": 1, "player_id": "player_2", "deck_list": \[ "counterspell_001", "counterspell_002", "gray_merchant_001", "gray_merchant_002", "island_001", "island_002", "swamp_001", "swamp_002" \] } |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 4 \- Server confirms both ready, transitions to GAME_SETUP**

**S \-\> ALL**

| { "type": "GAME_STATE_UPDATE", "seq_num": 2, "state": { "phase": "GAME_SETUP", "players_ready": 2, "waiting_for": \[\] } } |
| :------------------------------------------------------------------------------------------------------------------------- |

# **2\. GAME_SETUP State**

GAME_SETUP is fully automatic — no client input is required. The server validates decks, sets life totals to 20, shuffles each deck, draws seven cards per player, and determines who goes first via coin flip. It then broadcasts a personalized GAME_STATE_UPDATE to each player before transitioning to MULLIGAN.

## **Step 5 \- Server sends personalized GAME_STATE_UPDATE to Player 1**

Player 1's hand is visible to them; Player 2's hand is hidden (only the count is shown).

**S \-\> P1**

| { "type": "GAME_STATE_UPDATE", "seq_num": 3, "state": { "turn": 0, "phase": "MULLIGAN", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "hand": \["lightning_bolt_001","shock_001","mountain_001","mountain_002","goblin_guide_001","lightning_bolt_002","mountain_003"\], "hand_counts": { "player_2": 7 }, "library_counts": { "player_1": 1, "player_2": 1 }, "battlefield": { "player_1": \[\], "player_2": \[\] }, "graveyard": { "player_1": \[\], "player_2": \[\] }, "stack": \[\] } } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 6 \- Server sends personalized GAME_STATE_UPDATE to Player 2**

Player 2's hand is visible to them; Player 1's hand is hidden (only the count is shown).

**S \-\> P2**

| { "type": "GAME_STATE_UPDATE", "seq_num": 3, "state": { "turn": 0, "phase": "MULLIGAN", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "hand": \["counterspell_001","gray_merchant_001","island_001","swamp_001","counterspell_002","gray_merchant_002","swamp_002"\], "hand_counts": { "player_1": 7 }, "library_counts": { "player_1": 1, "player_2": 1 }, "battlefield": { "player_1": \[\], "player_2": \[\] }, "graveyard": { "player_1": \[\], "player_2": \[\] }, "stack": \[\] } } |
| :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

# **3\. MULLIGAN State**

Each player independently decides whether to keep their opening hand or take a mulligan. MTGNP uses the London Mulligan rule: a player who mulligans draws a new hand of seven cards, then puts a number of cards on the bottom of their library equal to the number of times they have mulliganed.

In this example, Player 1 keeps their opening hand immediately, while Player 2 takes one mulligan before keeping — and must therefore bottom exactly 1 card.

## **Step 7 \- Player 1 keeps their opening hand**

Player 1 is satisfied with their hand. seq_num echoes the GAME_STATE_UPDATE from Step 5 (seq_num 3). No cards are bottomed since Player 1 has not mulliganed.[^1]

**C \-\> S (Player 1\)**

| { "type": "MULLIGAN_CHOICE", "seq_num": 3, "keep": true, "cards_to_bottom": \[\] } |
| :--------------------------------------------------------------------------------- |

## **Step 8 \- Player 2 takes a mulligan**

Player 2 is not happy with their opening hand. seq_num echoes the GAME_STATE_UPDATE from Step 6 (seq_num 3). cards_to_bottom is empty when keep is false.

**C \-\> S (Player 2\)**

| { "type": "MULLIGAN_CHOICE", "seq_num": 3, "keep": false, "cards_to_bottom": \[\] } |
| :---------------------------------------------------------------------------------- |

## **Step 9 \- Server redraws 7 cards for Player 2**

The server draws a fresh 7-card hand for Player 2 and sends a new personalized GAME_STATE_UPDATE. seq_num advances to 4\. Player 1 does not receive a new update.[^2]

**S \-\> P2**

| { "type": "GAME_STATE_UPDATE", "seq_num": 4, "state": { "turn": 0, "phase": "MULLIGAN", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "hand": \["counterspell_001","island_001","swamp_001","island_002","gray_merchant_001","swamp_002","counterspell_002"\], "hand_counts": { "player_1": 7 }, "library_counts": { "player_1": 1, "player_2": 1 }, "battlefield": { "player_1": \[\], "player_2": \[\] }, "graveyard": { "player_1": \[\], "player_2": \[\] }, "stack": \[\] } } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 10 \- Player 2 keeps after mulligan, bottoms 1 card**

Player 2 keeps the new hand. Because they mulliganed once, cards_to_bottom MUST contain exactly 1 card ID. seq_num echoes the redraw GAME_STATE_UPDATE from Step 9 (seq_num 4\).[^3]

**C \-\> S (Player 2\)**

| { "type": "MULLIGAN_CHOICE", "seq_num": 4, "keep": true, "cards_to_bottom": \["counterspell_002"\] } |
| :--------------------------------------------------------------------------------------------------- |

## **Step 11 \- Both players have kept; server transitions to IN_GAME**

Both players have now sent MULLIGAN_CHOICE with keep: true. The server transitions to IN_GAME and begins Player 1's first turn, broadcasting a PHASE_TRANSITION to all players.[^4]

seq_num 5 on the PHASE_TRANSITION continues the server counter from the last GAME_STATE_UPDATE sent to Player 2 (seq_num 4\).[^5]

**S \-\> ALL**

| { "type": "PHASE_TRANSITION", "seq_num": 5, "from_phase": "MULLIGAN", "to_phase": "UNTAP", "active_player": "player_1", "turn": 1 } |
| :---------------------------------------------------------------------------------------------------------------------------------- |

# **4\. IN_GAME State — Turn 1 (Player 1\)**

Player 1 is the Active Player (AP). Player 2 is the Non-Active Player (NAP). The turn follows the full phase sequence: Untap \-\> Upkeep \-\> Draw \-\> Precombat Main \-\> Combat \-\> Postcombat Main \-\> End Step \-\> Cleanup.

## **Step 12 \- Untap Step (automatic, no priority)**

The server untaps all of Player 1's permanents and resets land_played_this_turn to false. No priority is granted. The server immediately advances to Upkeep.[^6]

**S \-\> ALL**

| { "type": "PHASE_TRANSITION", "seq_num": 6, "from_phase": "MULLIGAN", "to_phase": "UNTAP", "active_player": "player_1", "turn": 1 } |
| :---------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (untap broadcast)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 7, "state": { "turn": 1, "phase": "UNTAP", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "land_played": false, "battlefield": { "player_1": \[\], "player_2": \[\] }, "hand_counts": { "player_1": 7, "player_2": 6 }, "library_counts": { "player_1": 1, "player_2": 1 }, "stack": \[\] } } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (advance to Upkeep)**

| { "type": "PHASE_TRANSITION", "seq_num": 8, "from_phase": "UNTAP", "to_phase": "UPKEEP", "active_player": "player_1", "turn": 1 } |
| :-------------------------------------------------------------------------------------------------------------------------------- |

## **Step 13 \- Upkeep Step (both players pass, no actions)**

The server opens a priority window. Player 1 holds priority first. Both players pass with an empty stack, so the server advances to Draw.[^7]

**S \-\> P1**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 8, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------ |

**C \-\> S (Player 1 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 8 } |
| :---------------------------------------- |

**S \-\> P2**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 9, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------ |

**C \-\> S (Player 2 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 9 } |
| :---------------------------------------- |

**S \-\> ALL (both passed, empty stack — advance to Draw)**

| { "type": "PHASE_TRANSITION", "seq_num": 10, "from_phase": "UPKEEP", "to_phase": "DRAW", "active_player": "player_1", "turn": 1 } |
| :-------------------------------------------------------------------------------------------------------------------------------- |

## **Step 14 \- Draw Step (Player 1 draws, both pass)**

The server draws one card for Player 1 and sends a personalized GAME_STATE_UPDATE. A priority window opens; both players pass and the server advances to Precombat Main.[^8]

**S \-\> P1 (shock_002 added to hand)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 11, "state": { "turn": 1, "phase": "DRAW", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "hand": \["lightning_bolt_001","shock_001","mountain_001","mountain_002","goblin_guide_001","lightning_bolt_002","mountain_003","shock_002"\], "hand_counts": { "player_2": 6 }, "library_counts": { "player_1": 0, "player_2": 1 }, "stack": \[\] } } |
| :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

Priority exchange follows (Player 1 passes, Player 2 passes, empty stack). Server advances.

**S \-\> ALL (advance to Precombat Main)**

| { "type": "PHASE_TRANSITION", "seq_num": 14, "from_phase": "DRAW", "to_phase": "PRECOMBAT_MAIN", "active_player": "player_1", "turn": 1 } |
| :---------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 15 \- Precombat Main Phase: Play a Land**

Player 1 plays mountain_003 as their land for the turn. Playing a land does not use the stack and does not require priority. The server updates state and re-issues PRIORITY_GRANT to Player 1.[^9]

**C \-\> S (Player 1 plays land)**

| { "type": "PLAY_LAND", "seq_num": 14, "card_id": "mountain_003" } |
| :---------------------------------------------------------------- |

**S \-\> ALL (land enters battlefield)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 15, "state": { "turn": 1, "phase": "PRECOMBAT_MAIN", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "land_played": true, "battlefield": { "player_1": \[{ "id": "mountain_003", "tapped": false }\], "player_2": \[\] }, "hand_counts": { "player_1": 7, "player_2": 6 }, "stack": \[\] } } |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> P1 (re-issue priority after land)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 15, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

## **Step 16 \- Precombat Main Phase: Cast Goblin Guide**

Player 1 casts goblin_guide_001, paying 1 Red mana. Both players pass priority consecutively, the spell resolves, and Goblin Guide enters the battlefield.

**C \-\> S (Player 1 casts Goblin Guide)**

| { "type": "CAST_SPELL", "seq_num": 15, "card_id": "goblin_guide_001", "targets": \[\], "mana_payment": { "R": 1 } } |
| :------------------------------------------------------------------------------------------------------------------ |

**S \-\> ALL (spell pushed to stack)**

| { "type": "STACK_PUSH", "seq_num": 16, "stack_item_id": "stk_01", "item_type": "SPELL", "source": "goblin_guide_001", "targets": \[\], "controller": "player_1" } |
| :---------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> P1 (AP retains priority)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 16, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 16 } |
| :----------------------------------------- |

**S \-\> P2**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 17, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 2 passes — no response)**

| { "type": "PRIORITY_PASS", "seq_num": 17 } |
| :----------------------------------------- |

Both players passed consecutively with a non-empty stack — server resolves the top item.

**S \-\> ALL (Goblin Guide resolves, enters battlefield)**

| { "type": "STACK_RESOLVE", "seq_num": 18, "stack_item_id": "stk_01", "result": "RESOLVED", "state_changes": \[{ "type": "PERMANENT_ENTERS", "card_id": "goblin_guide_001", "controller": "player_1", "tapped": false }\] } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (updated battlefield)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 19, "state": { "turn": 1, "phase": "PRECOMBAT_MAIN", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "battlefield": { "player_1": \[ { "id": "mountain_003", "tapped": false }, { "id": "goblin_guide_001", "tapped": false, "summoning_sickness": true } \], "player_2": \[\] }, "hand_counts": { "player_1": 6, "player_2": 6 }, "stack": \[\] } } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

Both players pass priority again with an empty stack. Server advances to Combat.

**S \-\> ALL (advance to Combat)**

| { "type": "PHASE_TRANSITION", "seq_num": 22, "from_phase": "PRECOMBAT_MAIN", "to_phase": "BEGIN_COMBAT", "active_player": "player_1", "turn": 1 } |
| :------------------------------------------------------------------------------------------------------------------------------------------------ |

## **Step 17 \- Begin Combat Step (both pass)**

Priority window opens at Begin Combat. Both players pass with an empty stack.

**S \-\> ALL (advance to Declare Attackers)**

| { "type": "PHASE_TRANSITION", "seq_num": 25, "from_phase": "BEGIN_COMBAT", "to_phase": "DECLARE_ATTACKERS", "active_player": "player_1", "turn": 1 } |
| :--------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 18 \- Declare Attackers Step**

Goblin Guide entered the battlefield this turn, so it has summoning sickness and MUST NOT attack. Player 1 has no other attackers, so they declare no attackers. The server advances past combat.[^10]

**S \-\> P1 (priority to declare attackers)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 25, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 declares no attackers)**

| { "type": "DECLARE_ATTACKERS", "seq_num": 25, "attackers": \[\] } |
| :---------------------------------------------------------------- |

With no attackers declared, the server skips Declare Blockers, Assign Damage Order, and Combat Damage, advancing directly to End of Combat.

**S \-\> ALL (skip to End of Combat)**

| { "type": "PHASE_TRANSITION", "seq_num": 26, "from_phase": "DECLARE_ATTACKERS", "to_phase": "END_OF_COMBAT", "active_player": "player_1", "turn": 1 } |
| :---------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 19 \- Postcombat Main Phase (both pass)**

Priority window opens. Player 1 takes no further actions. Both pass with empty stack.

**S \-\> ALL (advance to Postcombat Main)**

| { "type": "PHASE_TRANSITION", "seq_num": 29, "from_phase": "END_OF_COMBAT", "to_phase": "POSTCOMBAT_MAIN", "active_player": "player_1", "turn": 1 } |
| :-------------------------------------------------------------------------------------------------------------------------------------------------- |

Both players pass priority. Server advances to End Step.

**S \-\> ALL**

| { "type": "PHASE_TRANSITION", "seq_num": 32, "from_phase": "POSTCOMBAT_MAIN", "to_phase": "END_STEP", "active_player": "player_1", "turn": 1 } |
| :--------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 20 \- End Step (both pass)**

A final priority window opens. Both players pass with an empty stack. Server advances to Cleanup.

**S \-\> ALL**

| { "type": "PHASE_TRANSITION", "seq_num": 35, "from_phase": "END_STEP", "to_phase": "CLEANUP", "active_player": "player_1", "turn": 1 } |
| :------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 21 \- Cleanup Step**

Player 1 has 6 cards in hand (under the 7-card limit), so no discard is needed. The server clears all damage from creatures and removes until-end-of-turn effects, then broadcasts a final GAME_STATE_UPDATE. Summoning sickness is cleared from Goblin Guide. No priority is granted. The server increments the turn counter, switches the Active Player to Player 2, and begins Turn 2's Untap Step.

**S \-\> ALL (damage cleared, summoning sickness removed)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 36, "state": { "turn": 1, "phase": "CLEANUP", "active_player": "player_1", "life_totals": { "player_1": 20, "player_2": 20 }, "battlefield": { "player_1": \[ { "id": "mountain_003", "tapped": false }, { "id": "goblin_guide_001", "tapped": false, "summoning_sickness": false } \], "player_2": \[\] }, "hand_counts": { "player_1": 6, "player_2": 6 }, "stack": \[\] } } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (Turn 2 begins — Player 2 is now Active Player)**

| { "type": "PHASE_TRANSITION", "seq_num": 37, "from_phase": "CLEANUP", "to_phase": "UNTAP", "active_player": "player_2", "turn": 2 } |
| :---------------------------------------------------------------------------------------------------------------------------------- |

# **5\. IN_GAME State — Turn 2 (Player 2\)**

Player 2 is now the Active Player (AP). Player 1 is the Non-Active Player (NAP). Player 2 enters with 6 cards in hand, no permanents on the battlefield. Player 1 has mountain_003 and goblin_guide_001 in play. The Turn 2 UNTAP PHASE_TRANSITION was already broadcast at seq_num 37\.

## **Step 22 \- Untap Step (automatic, no priority)**

Player 2 has no permanents to untap. The server resets land_played_this_turn for Player 2 and immediately advances to Upkeep.

**S \-\> ALL (state after untap)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 38, "state": { "turn": 2, "phase": "UNTAP", "active_player": "player_2", "life_totals": { "player_1": 20, "player_2": 20 }, "land_played": false, "battlefield": { "player_1": \[ { "id": "mountain_003", "tapped": false }, { "id": "goblin_guide_001", "tapped": false } \], "player_2": \[\] }, "hand_counts": { "player_1": 6, "player_2": 6 }, "library_counts": { "player_1": 0, "player_2": 1 }, "stack": \[\] } } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |

**S \-\> ALL (advance to Upkeep)**

| { "type": "PHASE_TRANSITION", "seq_num": 39, "from_phase": "UNTAP", "to_phase": "UPKEEP", "active_player": "player_2", "turn": 2 } |
| :--------------------------------------------------------------------------------------------------------------------------------- |

## **Step 23 \- Upkeep Step (both pass)**

Priority opens with Player 2 holding priority first. Neither player takes action. Both pass consecutively with an empty stack.

**S \-\> P2**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 39, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 2 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 39 } |
| :----------------------------------------- |

**S \-\> P1**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 40, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 40 } |
| :----------------------------------------- |

**S \-\> ALL (advance to Draw)**

| { "type": "PHASE_TRANSITION", "seq_num": 41, "from_phase": "UPKEEP", "to_phase": "DRAW", "active_player": "player_2", "turn": 2 } |
| :-------------------------------------------------------------------------------------------------------------------------------- |

## **Step 24 \- Draw Step (Player 2 draws island_002)**

The server draws one card for Player 2\. Player 2 now has 7 cards in hand. A priority window opens; both players pass and the server advances to Precombat Main.[^11]

**S \-\> P2 (personalized update with new card)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 42, "state": { "turn": 2, "phase": "DRAW", "active_player": "player_2", "life_totals": { "player_1": 20, "player_2": 20 }, "hand": \["counterspell_001","gray_merchant_001","island_001","swamp_001","gray_merchant_002","swamp_002","island_002"\], "hand_counts": { "player_1": 6 }, "library_counts": { "player_1": 0, "player_2": 0 }, "stack": \[\] } } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

Priority exchange: Player 2 passes, Player 1 passes, empty stack. Server advances.

**S \-\> ALL (advance to Precombat Main)**

| { "type": "PHASE_TRANSITION", "seq_num": 45, "from_phase": "DRAW", "to_phase": "PRECOMBAT_MAIN", "active_player": "player_2", "turn": 2 } |
| :---------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 25 \- Precombat Main Phase: Play a Land**

Player 2 plays swamp_001. The server places it on the battlefield, sets land_played to true, and re-issues PRIORITY_GRANT to Player 2\.

**C \-\> S (Player 2 plays land)**

| { "type": "PLAY_LAND", "seq_num": 45, "card_id": "swamp_001" } |
| :------------------------------------------------------------- |

**S \-\> ALL (swamp_001 enters battlefield)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 46, "state": { "turn": 2, "phase": "PRECOMBAT_MAIN", "active_player": "player_2", "life_totals": { "player_1": 20, "player_2": 20 }, "land_played": true, "battlefield": { "player_1": \[ { "id": "mountain_003", "tapped": false }, { "id": "goblin_guide_001", "tapped": false } \], "player_2": \[{ "id": "swamp_001", "tapped": false }\] }, "hand_counts": { "player_1": 6, "player_2": 6 }, "stack": \[\] } } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |

**S \-\> P2 (re-issue priority after land)**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 46, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

## **Step 26 \- Precombat Main Phase: Player 1 casts Lightning Bolt**

Player 2 passes priority. Player 1 (NAP) receives priority and casts lightning_bolt_001 targeting Player 2, tapping mountain_003 to pay 1 Red mana. Player 2 holds counterspell_001 but only has swamp_001 available — they cannot pay the UU cost. Player 2 passes. Lightning Bolt resolves, dealing 3 damage to Player 2.[^12]

**C \-\> S (Player 2 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 46 } |
| :----------------------------------------- |

**S \-\> P1 (NAP receives priority)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 47, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 casts Lightning Bolt targeting Player 2\)**

| { "type": "CAST_SPELL", "seq_num": 47, "card_id": "lightning_bolt_001", "targets": \["player_2"\], "mana_payment": { "R": 1 } } |
| :------------------------------------------------------------------------------------------------------------------------------ |

**S \-\> ALL (Lightning Bolt pushed to stack)**

| { "type": "STACK_PUSH", "seq_num": 48, "stack_item_id": "stk_02", "item_type": "SPELL", "source": "lightning_bolt_001", "targets": \["player_2"\], "controller": "player_1" } |
| :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> P1 (AP retains priority after casting)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 48, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 48 } |
| :----------------------------------------- |

**S \-\> P2**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 49, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 2 passes — cannot pay UU for Counterspell)**

| { "type": "PRIORITY_PASS", "seq_num": 49 } |
| :----------------------------------------- |

Both players passed consecutively with a non-empty stack. Server resolves the top item.[^13]

**S \-\> ALL (Lightning Bolt resolves — 3 damage to Player 2\)**

| { "type": "STACK_RESOLVE", "seq_num": 50, "stack_item_id": "stk_02", "result": "RESOLVED", "state_changes": \[{ "type": "DAMAGE", "target": "player_2", "amount": 3 }\] } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |

**S \-\> ALL (updated life totals)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 51, "state": { "turn": 2, "phase": "PRECOMBAT_MAIN", "active_player": "player_2", "life_totals": { "player_1": 20, "player_2": 17 }, "land_played": true, "battlefield": { "player_1": \[ { "id": "mountain_003", "tapped": true }, { "id": "goblin_guide_001", "tapped": false } \], "player_2": \[{ "id": "swamp_001", "tapped": false }\] }, "hand_counts": { "player_1": 5, "player_2": 6 }, "stack": \[\] } } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

Priority re-opens. Both players pass with an empty stack. Server advances to Combat.

**S \-\> ALL (advance to Combat)**

| { "type": "PHASE_TRANSITION", "seq_num": 54, "from_phase": "PRECOMBAT_MAIN", "to_phase": "BEGIN_COMBAT", "active_player": "player_2", "turn": 2 } |
| :------------------------------------------------------------------------------------------------------------------------------------------------ |

## **Step 27 \- Combat Phase (no attackers)**

Player 2 has no creatures on the battlefield and declares no attackers. Both players pass at Begin Combat. The server skips to End of Combat.

**S \-\> ALL (advance to Declare Attackers)**

| { "type": "PHASE_TRANSITION", "seq_num": 57, "from_phase": "BEGIN_COMBAT", "to_phase": "DECLARE_ATTACKERS", "active_player": "player_2", "turn": 2 } |
| :--------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> P2**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 57, "time_limit_ms": 60000 } |
| :------------------------------------------------------------------------------------------- |

**C \-\> S (Player 2 declares no attackers)**

| { "type": "DECLARE_ATTACKERS", "seq_num": 57, "attackers": \[\] } |
| :---------------------------------------------------------------- |

**S \-\> ALL (skip to End of Combat)**

| { "type": "PHASE_TRANSITION", "seq_num": 58, "from_phase": "DECLARE_ATTACKERS", "to_phase": "END_OF_COMBAT", "active_player": "player_2", "turn": 2 } |
| :---------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 28 \- Postcombat Main Phase (both pass)**

Priority window opens. Player 2 has no further actions. Both pass with an empty stack.

**S \-\> ALL (advance to Postcombat Main)**

| { "type": "PHASE_TRANSITION", "seq_num": 61, "from_phase": "END_OF_COMBAT", "to_phase": "POSTCOMBAT_MAIN", "active_player": "player_2", "turn": 2 } |
| :-------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (advance to End Step)**

| { "type": "PHASE_TRANSITION", "seq_num": 64, "from_phase": "POSTCOMBAT_MAIN", "to_phase": "END_STEP", "active_player": "player_2", "turn": 2 } |
| :--------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 29 \- End Step (both pass)**

Final priority window of the turn. Both players pass with an empty stack.

**S \-\> ALL (advance to Cleanup)**

| { "type": "PHASE_TRANSITION", "seq_num": 67, "from_phase": "END_STEP", "to_phase": "CLEANUP", "active_player": "player_2", "turn": 2 } |
| :------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 30 \- Cleanup Step**

Player 2 has 6 cards in hand (under the 7-card limit — drew 1, played swamp_001), so no discard is needed. The server clears damage markers from all creatures. mountain_003 untaps at the start of Player 1's next turn, not here. The server increments the turn counter, switches the Active Player to Player 1, and begins Turn 3's Untap Step.[^14]

**S \-\> ALL (damage cleared)**

| { "type": "GAME_STATE_UPDATE", "seq_num": 68, "state": { "turn": 2, "phase": "CLEANUP", "active_player": "player_2", "life_totals": { "player_1": 20, "player_2": 17 }, "battlefield": { "player_1": \[ { "id": "mountain_003", "tapped": true }, { "id": "goblin_guide_001", "tapped": false } \], "player_2": \[{ "id": "swamp_001", "tapped": false }\] }, "hand_counts": { "player_1": 5, "player_2": 6 }, "stack": \[\] } } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (Turn 3 begins — Player 1 is Active Player again)**

| { "type": "PHASE_TRANSITION", "seq_num": 69, "from_phase": "CLEANUP", "to_phase": "UNTAP", "active_player": "player_1", "turn": 3 } |
| :---------------------------------------------------------------------------------------------------------------------------------- |

# **6\. GAME_OVER State**

NOTE: Several turns have elapsed between Turn 2 and the exchange shown below. Over the course of those turns, Goblin Guide attacked repeatedly, and Player 1 used additional burn spells to reduce Player 2's life total. Player 2 managed to deploy Gray Merchant of Asphodel, draining Player 1 for some life, but was never able to stabilize the board. By Turn 7, the game state entering Player 1's Precombat Main Phase is as follows:

| Life totals: Player 1 \= 14, Player 2 \= 3 Battlefield: Player 1: mountain_001, mountain_002, mountain_003 (all untapped), goblin_guide_001 (untapped) Player 2: swamp_001, island_001 (both untapped) Player 1 hand: lightning_bolt_003, shock_002 Player 2 hand: counterspell_001 seq_num at start of this exchange: 118 |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 31 \- Player 1 casts Lightning Bolt targeting Player 2 (lethal)**

Player 1 casts lightning_bolt_003, targeting Player 2 who is at 3 life. The Bolt deals 3 damage — exactly enough to reduce Player 2's life total to 0\.

**S \-\> P1 (priority granted in Precombat Main)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 118, "time_limit_ms": 60000 } |
| :-------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 casts Lightning Bolt)**

| { "type": "CAST_SPELL", "seq_num": 118, "card_id": "lightning_bolt_003", "targets": \["player_2"\], "mana_payment": { "R": 1 } } |
| :------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> ALL (Lightning Bolt pushed to stack)**

| { "type": "STACK_PUSH", "seq_num": 119, "stack_item_id": "stk_09", "item_type": "SPELL", "source": "lightning_bolt_003", "targets": \["player_2"\], "controller": "player_1" } |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

**S \-\> P1 (AP retains priority)**

| { "type": "PRIORITY_GRANT", "player_id": "player_1", "seq_num": 119, "time_limit_ms": 60000 } |
| :-------------------------------------------------------------------------------------------- |

**C \-\> S (Player 1 passes)**

| { "type": "PRIORITY_PASS", "seq_num": 119 } |
| :------------------------------------------ |

**S \-\> P2**

| { "type": "PRIORITY_GRANT", "player_id": "player_2", "seq_num": 120, "time_limit_ms": 60000 } |
| :-------------------------------------------------------------------------------------------- |

**C \-\> S (Player 2 passes — counterspell_001 requires UU, only BU available)**

| { "type": "PRIORITY_PASS", "seq_num": 120 } |
| :------------------------------------------ |

Both players passed consecutively. Server resolves the top item.

**S \-\> ALL (Lightning Bolt resolves — 3 damage to Player 2\)**

| { "type": "STACK_RESOLVE", "seq_num": 121, "stack_item_id": "stk_09", "result": "RESOLVED", "state_changes": \[{ "type": "DAMAGE", "target": "player_2", "amount": 3 }\] } |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## **Step 32 \- Server detects win condition and broadcasts GAME_OVER**

Player 2's life total has reached 0\. The server immediately detects the LIFE_ZERO win condition, skips any further priority windows, and broadcasts GAME_OVER to all connected players. Player 1 is declared the winner.[^15]

**S \-\> ALL**

| { "type": "GAME_OVER", "seq_num": 122, "winner_id": "player_1", "loser_id": "player_2", "reason": "LIFE_ZERO" } |
| :-------------------------------------------------------------------------------------------------------------- |

The reason field identifies how the game ended.[^16]

winner_id is always set to the non-offending or surviving player.[^17]

## **Step 33 \- Server transitions back to LOBBY**

Immediately after broadcasting GAME_OVER, the server transitions back to LOBBY state. The existing TCP connections are retained. Both players must send a fresh PLAYER_READY PDU to begin a new game. The server does not broadcast a PHASE_TRANSITION for this — the GAME_OVER PDU itself signals the return to LOBBY.[^18]

[^1]: A player who has never mulliganed keeps with an empty cards_to_bottom array, since N \= 0\.

[^2]: Only the mulliganing player receives a new GAME_STATE_UPDATE after a redraw. The other player receives no PDU until both have kept and the server broadcasts PHASE_TRANSITION.

[^3]: When keep is false, cards_to_bottom MUST be empty. When keep is true, cards_to_bottom MUST contain exactly N card IDs where N equals the number of mulligans taken. The server rejects a mismatch with ERROR code ILLEGAL_ACTION.

[^4]: Players decide independently — each player's MULLIGAN_CHOICE is processed separately. Player 1's keep does not block or affect Player 2's mulligan decision.

[^5]: seq_num on PHASE_TRANSITION continues the server counter from the last GAME_STATE_UPDATE sent to either player — here seq_num 5 follows seq_num 4, the redraw sent to Player 2\.

[^6]: The Untap Step has no priority window. The server performs all untap actions automatically and advances to Upkeep without waiting for any client PDU.

[^7]: Every priority window follows the same pattern: PRIORITY_GRANT to AP, PRIORITY_PASS from AP, PRIORITY_GRANT to NAP, PRIORITY_PASS from NAP — then PHASE_TRANSITION if the stack is empty. Only the Precombat Main spell-casting window is shown in full detail; other windows are summarised for brevity.

[^8]: Per the RFC, on the very first turn the first player does NOT draw a card during the Draw Step. This example shows a representative turn with a draw for clarity; a strict Turn 1 implementation would skip the card draw and open the priority window on an unchanged hand.

[^9]: PLAY_LAND bypasses the stack entirely. The server deducts the land from the hand, places it on the battlefield, sets land_played to true, and re-issues PRIORITY_GRANT to the Active Player.

[^10]: A creature has summoning sickness the turn it enters the battlefield. It MUST NOT be declared as an attacker and MUST NOT activate tap abilities until the controller's next Untap Step.

[^11]: Player 2's library reaches 0 after this draw. An 8-card deck minus 7 drawn at setup minus 1 bottomed during mulligan leaves 0 cards. Any draw attempt on Turn 3 or later triggers the DECK_EMPTY win condition.

[^12]: Player 1 receiving priority during Player 2's Precombat Main Phase is legal. When the Active Player passes priority, the Non-Active Player receives it and may cast instants or activate abilities at instant speed.

[^13]: Counterspell costs UU. Player 2's only mana source is swamp_001, which produces Black mana. Had Player 2 attempted the cast, the server would have returned ERROR code INSUFFICIENT_MANA.

[^14]: mountain_003 remains tapped through Cleanup — lands are not untapped during the owner's Cleanup Step. They untap at the start of the owner's next Untap Step.

[^15]: LIFE_ZERO is detected immediately after STACK_RESOLVE applies damage — no further priority windows are granted before GAME_OVER is broadcast.

[^16]: Valid reason values: LIFE_ZERO (life total reaches 0), DECK_EMPTY (draw from empty library), CONCEDE (player sends CONCEDE PDU), DISCONNECT (connection lost, reconnect timer expired).

[^17]: winner_id is the non-offending or surviving player in all cases.

[^18]: TCP connections are preserved across GAME_OVER. Both players can start a new game immediately by sending PLAYER_READY on the same connection — no reconnection required.
