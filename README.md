# mtg-network-protocol <!-- omit from toc -->

<p align="center">
  <img src="assets/banner.jpg" alt="Magic: The Gathering" width="100%">
  <br>
  <em>Image Source: <a href="https://www.thegamer.com/magic-the-gathering-collection-every-card/">TheGamer</a></em>
</p>

![Year, Term, Course](https://img.shields.io/badge/AY2526--T3-CSNETWK-blue)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=fff) ![uv](https://img.shields.io/badge/uv-261230.svg?logo=uv&logoColor=#de5fe9) ![Pydantic](https://img.shields.io/badge/Pydantic-e92063?logo=pydantic&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)

A TCP-based client-server protocol and engine implementation for conducting two-player, simplified **Magic: The Gathering** card game sessions over a network. Built in compliance with **[RFC 0001 (MTGNP v1.0)](docs/references/rfc.md)** for the course **CSNETWK (Introduction to Computer Networking)**.

## Table of Contents <!-- omit from toc -->

- [1. Introduction \& Background](#1-introduction--background)
- [2. Project Structure](#2-project-structure)
- [3. Getting Started](#3-getting-started)
  - [3.1. Technical Prerequisites](#31-technical-prerequisites)
  - [3.2. Installation](#32-installation)
- [4. Running the System](#4-running-the-system)
  - [4.1. Starting the Authoritative Server](#41-starting-the-authoritative-server)
    - [Verbose Mode (Mandatory for Machine Problem Demo)](#verbose-mode-mandatory-for-machine-problem-demo)
    - [Custom Host / Port Configuration](#custom-host--port-configuration)
  - [4.2. Connecting Interactive Clients](#42-connecting-interactive-clients)
    - [Interactive Controls \& Exiting](#interactive-controls--exiting)
  - [4.3. Scripted / Headless Client Execution](#43-scripted--headless-client-execution)
  - [4.4. Running the Test Suite](#44-running-the-test-suite)
  - [4.5. Rebuilding the Card Catalog](#45-rebuilding-the-card-catalog)
- [5. System Architecture \& Protocol Highlights](#5-system-architecture--protocol-highlights)
  - [5.1. Network Transport \& Framing (4-Byte Length Prefix)](#51-network-transport--framing-4-byte-length-prefix)
  - [5.2. Session Lifecycle \& State Machine](#52-session-lifecycle--state-machine)
  - [5.3. Priority Window \& Sequence Token (`seq_num`) Validation](#53-priority-window--sequence-token-seq_num-validation)
  - [5.4. State-Based Actions (SBAs) \& Trigger Pause/Resume Pipeline](#54-state-based-actions-sbas--trigger-pauseresume-pipeline)
- [6. Known Limitations \& RFC Deviations](#6-known-limitations--rfc-deviations)
- [7. Work Distribution Matrix \& AI Usage](#7-work-distribution-matrix--ai-usage)
  - [7.1. Work Distribution Matrix](#71-work-distribution-matrix)
  - [7.2. AI Usage Declaration](#72-ai-usage-declaration)
  - [7.3. Open-Source Libraries \& Utilities Citation](#73-open-source-libraries--utilities-citation)
- [8. Documentation Index \& References](#8-documentation-index--references)

---

## 1. Introduction & Background

Magic: The Gathering is one of the most rules-dense and stateful games ever designed. Implementing its ruleset over a network requires transitioning from simple request-response paradigms to a complex, layered, and event-driven protocol specification.

**MTGNP (Magic: The Gathering Multiplayer Network Protocol v1.0)** standardizes the network communication between an authoritative server and two client endpoints over raw TCP socket streams. The system models complex game dynamics, including:

- **14 Turn Phases and Steps**: From Untap and Upkeep through Combat subdivisions to Cleanup.
- **Priority Window Exchange**: Strict Active Player (AP) vs. Non-Active Player (NAP) priority passing before resolving items on the stack or advancing turn phases.
- **The Stack (LIFO)**: Supporting non-creature spells, creatures, instants, sorceries, and triggered abilities.
- **State-Based Actions (SBAs)**: Single-funnel checks for player life total checks (life $\le 0$), creature lethal damage, and 0-toughness deaths applied automatically before priority grants.
- **Event-Driven Triggers**: Enters-the-Battlefield (ETB), attack declaration, and spell-casting triggers, featuring interactive target selection pauses (`TRIGGER_CHOICE`).
- **Hidden Information & Information Privacy**: The server acts as the single source of truth, censoring opponent hand contents while broadcasting counts and public battlefield state.

The codebase is engineered with an **asyncio socket transport layer**, **Pydantic discriminated union PDU schemas**, a **data-driven card engine ([cards.json](src/mtgnp/protocol/cards.json))**, and a **functional game core** decoupled from network I/O.

For full protocol specifications, see [RFC 0001](docs/references/rfc.md) and the domain glossary in [CONTEXT.md](CONTEXT.md).

---

## 2. Project Structure

A high-level overview of the repository layout and core Python package components:

```text
.
├── docs/                       # Specifications, ADRs, and reference documents
│   ├── adr/                    # Architectural Decision Records (ADRs 0001–0013)
│   ├── agents/                 # Contributor guidelines and issue tracker triage docs
│   └── references/             # Normative RFC 0001 spec, rubric, card tables, and PDU traces
│       ├── card_instances.tsv  # Master card instance list
│       ├── color_summary.tsv   # Card color breakdown
│       ├── examples.md         # PDU walkthroughs across all lifecycle states
│       ├── master_card_list.tsv# Master card templates
│       ├── rfc.md              # MTGNP v1.0 Normative Specification (RFC 0001)
│       └── rubric.md           # CSNETWK Machine Problem Instructions & Rubric
├── src/                        # Core Python application package
│   └── mtgnp/
│       ├── client/             # Client package (CLI & Headless Script runner)
│       │   ├── connection.py   # Asyncio TCP socket manager & frame decoder
│       │   ├── controller.py   # State-machine driven CLI player interaction handler
│       │   ├── renderer.py     # Terminal renderer for battlefield, hand, life, and stack
│       │   └── __main__.py     # Client binary entry point (`mtgnp-client`)
│       ├── protocol/           # Protocol definitions, wire constants, & framing
│       │   ├── cards.json      # Compiled 60-card MTG catalog database
│       │   ├── catalog.py      # Out-of-band card catalog parser & validator
│       │   ├── constants.py    # Wire limits, ports, hand/deck sizes, and timeouts
│       │   ├── errors.py       # Standardized protocol error codes (RFC §11)
│       │   ├── framing.py      # 4-byte uint32 length-prefixed stream framer
│       │   └── pdus.py         # Pydantic discriminated union schemas (25 PDU types)
│       └── server/             # Authoritative server game engine package
│           ├── cast.py         # Spell casting validation (costs, timing, lands)
│           ├── combat.py       # Attackers/blockers declaration & combat damage resolution
│           ├── custom_effects.py# Code escape hatches for complex card effects
│           ├── effects.py      # Data-driven effect primitives (DAMAGE, DRAW, PUMP, etc.)
│           ├── engine.py       # Core PDU dispatcher & rule orchestrator
│           ├── lifecycle.py    # State machine transitions (LOBBY -> GAME_OVER)
│           ├── priority.py     # Priority grant/pass and sequence token management
│           ├── sba.py          # State-Based Actions & trigger placement pipeline
│           ├── stack.py        # LIFO stack pushing, targeting, & top resolution
│           ├── state.py        # Authoritative GameState, PlayerState, and Zone models
│           ├── transport.py    # Asyncio TCP listener, client connections, & reconnects
│           ├── triggers.py     # Trigger detection & choice pause/resume handlers
│           ├── turn.py         # 14-step turn phase progression manager
│           └── __main__.py     # Server entry point (`mtgnp-server`)
├── tests/                      # Pytest suite (231 passing tests)
│   ├── engine/                 # Unit tests for casting, combat, SBAs, and triggers
│   ├── golden/                 # Script fixtures and golden-session scaffold
│   ├── protocol/               # Framing, serialization, and card catalog tests
│   └── transport/              # Socket stream framing & disconnect/reconnect tests
├── tools/                      # Utility scripts
│   └── build_catalog.py        # Script to re-compile cards.json from TSV master lists
├── CLAUDE.md                   # Developer guidance & issue tracker conventions
├── CONTEXT.md                  # MTGNP domain glossary & ubiquitous language definition
├── pyproject.toml              # Dependency configuration managed by uv
└── README.md                   # Project documentation & usage guide
```

---

## 3. Getting Started

### 3.1. Technical Prerequisites

Ensure your development machine meets the following requirements:

1. **Git**: Installed for version control.
2. **Python `>= 3.11`**: Standard modern Python runtime.
3. **uv**: Fast unified Python package and project manager.
   - Installation guide: <https://docs.astral.sh/uv/getting-started/installation/>

### 3.2. Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/qu1r0ra/mtg-network-protocol.git
   cd mtg-network-protocol
   ```
2. Synchronize project dependencies (this automatically sets up an isolated `.venv` virtual environment):
   ```bash
   uv sync
   ```

---

## 4. Running the System

You can run the MTGNP server, launch client instances, run automated test suites, or recompile the card catalog using `uv`.

### 4.1. Starting the Authoritative Server

To launch the MTGNP TCP server on default host (`127.0.0.1`) and port (`4444`):

```bash
uv run mtgnp-server
```

#### Verbose Mode (Mandatory for Machine Problem Demo)

To output real-time raw PDU socket framing and wire message logs to stdout:

```bash
uv run mtgnp-server --verbose
```

#### Custom Host / Port Configuration

```bash
uv run mtgnp-server --host 0.0.0.0 --port 8888 --verbose
```

### 4.2. Connecting Interactive Clients

Open separate terminal windows for each player and launch the client binary:

**Player 1 Terminal:**

```bash
uv run mtgnp-client --host 127.0.0.1 --port 4444 --player-id Alice --deck-file decks/red.json --verbose
```

**Player 2 Terminal:**

```bash
uv run mtgnp-client --host 127.0.0.1 --port 4444 --player-id Bob --deck-file decks/green.json --verbose
```

#### Interactive Controls & Exiting

- **Mulligan Phase**: Input `keep` to accept opening hand, or `mulligan` to redraw.
- **Priority Phase**: Select from rendered options (cast spell, play land, attack, block) or type `pass` to pass priority.
- **Disconnect / Concede**: Issue a `concede` command or press `Ctrl+C` in the client terminal to gracefully exit.

### 4.3. Scripted / Headless Client Execution

For non-interactive testing or pre-recorded PDU sequence playback, pass a script file containing predefined actions:

```bash
uv run mtgnp-client --script tests/golden/sample_script.json --verbose
```

### 4.4. Running the Test Suite

Execute the full suite of 231 unit, client, integration, and protocol tests:

```bash
uv run pytest
```

### 4.5. Rebuilding the Card Catalog

If modifying [master_card_list.tsv](docs/references/master_card_list.tsv) or [card_instances.tsv](docs/references/card_instances.tsv), regenerate the out-of-band [cards.json](src/mtgnp/protocol/cards.json) catalog and [card_instances.json](src/mtgnp/protocol/card_instances.json) legal-instance set by running [build_catalog.py](tools/build_catalog.py):

```bash
uv run python tools/build_catalog.py
```

---

## 5. System Architecture & Protocol Highlights

### 5.1. Network Transport & Framing (4-Byte Length Prefix)

MTGNP operates over persistent TCP stream sockets. To resolve TCP packet fragmentation and stream boundary issues, every payload is wrapped in a strict binary framing layer ([framing.py](src/mtgnp/protocol/framing.py)):

$$\text{Frame} = [\text{Length Prefix (4 bytes, Big-Endian uint32)}] + [\text{JSON Payload (UTF-8 Encoded)}]$$

- **Maximum PDU Size**: Restricted to 65,535 bytes (`MAX_PDU_BYTES` in [constants.py](src/mtgnp/protocol/constants.py)).
- **Discriminator**: All 25 wire PDUs inherit from a base Pydantic class discriminating on the string `"type"` field ([pdus.py](src/mtgnp/protocol/pdus.py)).

### 5.2. Session Lifecycle & State Machine

The server orchestrates session progression through 5 strict state phases ([lifecycle.py](src/mtgnp/server/lifecycle.py)):

```text
  ┌────────┐       Both Players Ready      ┌────────────┐
  │ LOBBY  ├──────────────────────────────►│ GAME_SETUP │
  └▲───────┘                               └─────┬──────┘
   │                                             │ Shuffled & Hands Dealt
   │ Connection Retained                         ▼
   │                                       ┌────────────┐
   │                                       │  MULLIGAN  │
   │                                       └─────┬──────┘
   │                                             │ Both Accepted / Kept
   │                                             ▼
  ┌┴───────────┐         Life = 0          ┌────────────┐
  │ GAME_OVER  │◄──────────────────────────┤  IN_GAME   │
  └────────────┘    or Disconnect / Concede└────────────┘
```

### 5.3. Priority Window & Sequence Token (`seq_num`) Validation

Priority governs player actions during `IN_GAME`. The server issues a `PRIORITY_GRANT` containing a unique `seq_num` token ([ADR 0006](docs/adr/0006-seqnum-semantics.md)):

- Any player action PDU (e.g., `CAST_SPELL`, `PASS_PRIORITY`, `DECLARE_ATTACKERS`) MUST echo the exact active `seq_num`.
- If a client submits an action with an outdated token, the server rejects it with a `STALE_ACTION` error PDU ([errors.py](src/mtgnp/protocol/errors.py)) without mutating state.

### 5.4. State-Based Actions (SBAs) & Trigger Pause/Resume Pipeline

Before granting priority to any player, the server executes a single-funnel SBA check ([sba.py](src/mtgnp/server/sba.py)):

1. Checks for loss conditions (Life $\le 0$).
2. Evaluates creature lethal damage and 0-toughness deaths, moving dead cards to the Graveyard.
3. Drains pending ETB or death events into triggered abilities.
4. **Targeted Trigger Pause/Resume**: If a triggered ability requires target selection, the server pauses normal priority, stores `pending_trigger_choice` state, and sends `TRIGGER_CHOICE` to the controlling client ([ADR 0007](docs/adr/0007-targeted-trigger-pause-resume.md)). Upon receiving `TRIGGER_CHOICE_RESPONSE`, it resumes, pushes `STACK_PUSH` to the stack, and grants priority.

---

## 6. Known Limitations & RFC Deviations

As documented during the core engine architectural phase, two specific low-level items deviate intentionally from RFC 0001:

1. **`TRIGGER_ORDER` / `TRIGGER_ORDER_RESPONSE` (RFC §8.6.2) — Not Emitted**
   - _Rationale_: The engine does not prompt players to manually order simultaneous triggers when multiple triggers fire at the same time. Pending triggers are pushed to the stack in queue order. In the shipped 60-card catalog (e.g. two identical Goblin Guides attacking simultaneously), the triggers are functionally identical, making resolution order outcome-neutral. The error code `TRIGGER_ORDER_INVALID` is preserved in [errors.py](src/mtgnp/protocol/errors.py).
2. **`ACTIVATE_ABILITY` (RFC §10.2.8) — Explicitly Rejected, Not Resolved**
   - [engine.py](src/mtgnp/server/engine.py) returns an `ILLEGAL_ACTION` ERROR instead of silently dropping unsupported ability requests. Activated abilities for cards such as Llanowar Elves, Merfolk Looter, Prodigal Sorcerer, Mother of Runes, Royal Assassin, Millstone, and Rod of Ruin are not fully resolved by the current engine.
3. **Selected Card-Specific Rules Are Simplified**
   - The implementation focuses on the RFC networking, lifecycle, priority, stack, and combat requirements. Some full MTG card text, including Aura attachment and several protection, flying, vigilance, regeneration, and activated-ability details, remains simplified and should be disclosed during the demo.

---

## 7. Work Distribution Matrix & AI Usage

### 7.1. Work Distribution Matrix

In accordance with the CSNETWK Machine Problem rubric instructions:

| Task / Feature                                                | Member 1: AGUILA, Christian Fernand | Member 2: BUNYI, Christian Joseph | Member 3: CHUA, Jeffrey Eivann | Member 4: RADAM, Paul Powell |
| :------------------------------------------------------------ | :---------------------------------: | :-------------------------------: | :----------------------------: | :--------------------------: |
| **TCP Server**: connection handling, framing, dispatch        |                                     |                                   |                                |                              |
| **Game lifecycle**: LOBBY, GAME_SETUP, MULLIGAN logic         |                                     |                                   |                                |                              |
| **Turn & phase engine** (all phases/steps, transitions)       |                                     |                                   |                                |                              |
| **Priority & Stack logic**, spell/ability resolution          |                                     |                                   |                                |                              |
| **Combat system** (attackers, blockers, damage)               |                                     |                                   |                                |                              |
| **Client implementation** & state rendering                   |                                     |                                   | Client integration, command handling, state rendering, session flow                              |                              |
| **PDU serialisation/deserialisation** (all 25 PDU types)      |                                     |                                   | Client-side PDU parsing, sending, and receiving                               |                              |
| **Error handling**, PING/PONG heartbeat, disconnect logic     |                                     |                                   | Client heartbeat, PING/PONG handling, disconnect handling                               |                              |
| **Verbose mode** (client + server PDU logging, toggle on/off) |                                     |                                   | Client-side verbose PDU logging                               |                              |
| **Testing & interoperability**                                |                                     |                                   | Client/integration testing, two-client end-to-end testing                               |                              |
| **README / documentation / AI disclosure**                    |                                     |                                   |                                |                              |

### 7.2. AI Usage Declaration

In accordance with CSNETWK Machine Problem guidelines:

- **Harnesses Used**: Antigravity AI Coding Assistant, Chatgpt, GitHub Copilot Assistant, and Claude Code.
- **Models Used**: Various Gemini models (e.g. Gemini 3.6 Flash), OpenAI ChatGPT (GPT-5.6 Sol), and Claude models (e.g. Claude 3.7 Sonnet).
- **Application**:
  - (has yet to be populated)
  - Used AI to implement code for files in the 'client' sub-folder under the 'src/mtgnp' folder (init.py, main.py, connection.py, controller.py, renderer.py)
- **Verification**: All AI-assisted code was manually reviewed, verified against RFC 0001 normative rules, and validated via the 231-test Pytest suite.

### 7.3. Open-Source Libraries & Utilities Citation

In accordance with the CSNETWK Machine Problem rubric guidelines (Academic Integrity & Open-Source Policy):

| Open-Source Library / Asset | License | Purpose / Role in Project | Citation / Repository |
| :--- | :--- | :--- | :--- |
| **[Pydantic](https://github.com/pydantic/pydantic)** (`>=2.6`) | MIT | PDU schema definitions, data validation, and wire serialization/deserialization | [pydantic/pydantic](https://github.com/pydantic/pydantic) |
| **[pytest](https://github.com/pytest-dev/pytest)** (`>=8.0`) | MIT | Unit, integration, protocol, and golden trace test suite runner | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) |
| **[uv](https://github.com/astral-sh/uv)** | MIT / Apache-2.0 | Unified Python package manager, virtual environment, and task runner | [astral-sh/uv](https://github.com/astral-sh/uv) |
| **[Hatchling](https://github.com/pypa/hatch)** | MIT | PEP 517 build system backend for package targets | [pypa/hatch](https://github.com/pypa/hatch) |
| **Banner Image** (`assets/banner.jpg`) | Third-Party Media | README header visual banner | Courtesy of [TheGamer](https://www.thegamer.com/magic-the-gathering-collection-every-card/) |

---

## 8. Documentation Index & References

- [RFC 0001 Normative Specification](docs/references/rfc.md): Full wire protocol and game rules reference.
- [CSNETWK Rubric & Instructions](docs/references/rubric.md): Grading criteria and demo submission requirements.
- [Sample PDU Traces](docs/references/examples.md): Step-by-step example PDU exchanges for all 5 game states.
- [MTGNP Domain Glossary](CONTEXT.md): Ubiquitous language dictionary for protocol concepts.
- [Architectural Decision Records](docs/adr/): Design decisions covering asyncio concurrency, sequence tokens, trigger pauses, and data-driven card effects.
