# Rix · Raising a long-lived AI on QQ

**中文**: [README.md](README.md) ｜ **Deployment**: [docs/部署教程.md](docs/部署教程.md) ｜ **What we changed**: [qq-bridge/MODIFICATIONS.md](qq-bridge/MODIFICATIONS.md)

> **Provenance first**: `qq-bridge/` is a **fork of [Derpyu520/qq-bridge](https://github.com/Derpyu520/qq-bridge)** (MIT).
> The runtime foundation is someone else's work. What we changed is wake scheduling, memory wiring,
> send control and the sandbox layer — itemised in `MODIFICATIONS.md`.
> **`rix-brain/` and `sandbox/` are ours.**

> An **honest engineering log**: how we gave an LLM continuous memory, a life of its own on a clock,
> and a place where it can actually do things.
>
> **This is not a product, not a framework, and not a one-click deploy.** It is the part of a
> month-old, still-running system that can be **lifted out and used separately** — plus every
> hole we fell into on the way.

---

## Three sentences first

1. **It is not an "AI assistant".** It doesn't answer only when spoken to — it wakes itself, sleeps itself, finds things to do.
2. **It is not a "memory store".** Memory is just the layer that lets it exist continuously; above that sit wake scheduling and tool boundaries.
3. **It is not ready to run.** We list dependencies and thresholds plainly. **Failing to boot is expected**; understanding the design is the point.

---

## How data flows

```
QQ ──► SnowLuma ──► qq-bridge ──► DSH ──► rix-brain
      (protocol)   (wake/send)  (host)   (memory)
                                      │
                                      └──► sandbox (WSL): where it can act
```

**Memory lives in Python, waking lives in Node, the model lives in DSH.**
Three separate things — if one breaks, the other two can still be tested alone.

## Three parts you can take separately

### ① Memory engine (`rix-brain/`)

An AI's memory in three layers, searchable across sessions:

| Layer | What it is | Where it lives |
|---|---|---|
| **Short-term** | Raw recent turns per session | `chats/<session>/short_term.json` |
| **Diary** | Per-day, per-session summaries (subjective / objective) | `chats/<session>/diary.json` |
| **Long-term** | Cross-session retrieval over the two above | no separate store; synthesized at query time |

**Retrieval path**: lexical (gram coverage) + vector (local bge-m3) + attribute associations → merged candidate pool → a single LLM re-rank → top-K by quota.

**It has tests**: 176 cases, zero third-party dependencies, runs offline.

```bash
cd rix-brain
python -m unittest discover -s tests      # 2–4 s, all green
```

### ② Runtime (`qq-bridge/`)

Connects QQ to the agent and decides **when to wake it**:

- Wake scheduling: someone spoke / its own alarm / a 20-minute "time of its own"
- Send control: message splitting, rate quotas, allow-lists
- Session rotation: at a context threshold it opens a new session and hands over — it does not truncate
- Tool gateway: MCP

### ③ Sandbox recipe (`sandbox/`)

A WSL environment that **can reach the internet but cannot touch the host**:

```bash
# egress rules: allow DNS only, reject every private range
sandbox/sandbox-net.sh
```

**This is the most valuable part.** The ordering of those iptables rules is what we broke first:
WSL's resolver lives at `10.255.255.254`, inside `10/8` — reject first and the box loses all networking.

---

## Shortest path (just to look)

```bash
# 1) Memory engine only — no QQ, no DSH
cd rix-brain
cp config.example.json config.json     # put any OpenAI-compatible key in it
python -m unittest discover -s tests   # 176 cases, 2–4 s

# 2) The fish (stdlib only, needs nothing)
cd sandbox/example-fish
python fish.py --demo

# 3) Full stack → docs/部署教程.md (3–6 hours the first time)
```

## Real numbers (measured, not estimated)

| Metric | Value |
|---|---|
| Context per turn | 20k – 66k tokens (longer turns cost more) |
| Average context per step | ~47k tokens (43k → 47k over one week) |
| Cache hit rate | 98% |
| Cost per turn | ¥0.01 – ¥0.16 |
| Memory size | 226 diary entries, ~170 KB |
| Retrieval quality | hit@1 80% / hit@5 90% (20 frozen queries) |
| Persona prompt | 6,077 chars (hard cap 7,000; over the cap it truncates silently) |

---

## What we got wrong

**This section is worth more than the code.**

### 1. Letting the re-ranker pick the winner from a big pool

**hit@1 dropped from 40% to 10%.**

With a large pool the model picks "topically related", not "actually answers this". It needs a
**small pool and an explicit criterion**.

### 2. Putting context into the vector query

**45% → 10%.**

300 characters of context dwarf the query; the embedding gets dragged toward the context.

### 3. Representing emotion as numbers

Ran for two months, then deleted. **Nobody was actually reading the number.**

Emotion now lives only in memory: it writes its own diary and recalls from it. Quota is fixed at 10.

### 4. A persona file that exceeded the cap and truncated silently

It cut at the middle of a word. **Three days to find.**

### 5. Sandbox output recorded as "a user message"

`{self: false, sender: 'sandbox'}` — i.e. "a person named *sandbox* sent this".

Discovered three days later:

- 1336 of 1500 short-term rows were machine logs; **the real conversation had been pushed out entirely**
- The identity tag used "most frequent nickname", so the *machine* became the other party's name
- The diary started inverting subject and object: "**he said** he'd go fiddle with the fish" — she had said it

**The fix isn't deleting logs, it's giving them their own category** (`kind: 'tool'` → recorded as role "tool").

### 6. A benchmark that can be gamed

We handed a contractor 20 queries *and the answers*. Tuning to them gets you 90% easily.

We added a holdout and required two reports: **with re-rank** and **without re-rank**.
Only if the no-rerank number improves did retrieval actually get better.

### 7. No tests

We changed 80 lines of code and verified by "run it and see". **Zero unit tests for a month.**

Now there are 176, and one of them is a **mutation check**: mutate 10 random spots, at least 8 must turn a test red.

---

## Four problems we haven't solved

**These are the actual ask, not politeness.**

### 1. Is this three-layer memory the right shape?

Short-term / diary / long-term, cross-session via retrieval. **Is there something simpler?**

Our bottleneck isn't ranking, it's **recall**: two queries have their correct answer outside the top 20 (same-topic interference).

### 2. How should waking be scheduled?

Currently "every 20 minutes + clocks it sets itself". **Is there a better model?**

Observed failure: with nothing in progress, it sleeps for very long stretches.

### 3. What escape surfaces does the sandbox still have?

WSL2 + iptables + no drvfs + interop disabled. **No C:/D: mounts, host unreachable, LAN unreachable.**

But **outbound internet works** — data can leave. We haven't found a way to tighten that without breaking `apt`.

### 4. The hard one: how do you tell "it acted on its own" from "we led it there"?

Our only criterion: **does it come back when nobody mentions it**.

But every new direction so far came from us. That criterion isn't enough.

---

## Dependencies and thresholds

```
QQ protocol   SnowLuma (OneBot 11)
Host          DSH (desktop app)
Model         DeepSeek API (OpenAI-compatible)
Embeddings    local ollama + bge-m3
Sandbox       WSL2 (Linux)
```

**Five external pieces; any one of them dies and the whole thing is down.**

`rix-brain` runs on its own (it only needs an embedding model and an OpenAI-compatible LLM).

---

## Layout

```
rix-brain/            memory engine
  brain/              implementation
  server/             MCP server
  tests/              176 cases
qq-bridge/            runtime (QQ in, wake, send)
  src/ scripts/ docs/
sandbox/              isolation recipe
  example-fish/       an example: something an AI raised itself (stdlib only, runs as-is)
plugins/
  emotion-legacy/     the old emotion layer (optional, deleted from the mainline)
EASTER_EGG.md         a page it wrote itself
```

## Two extras

### The emotion layer (`plugins/emotion-legacy/`)

The numeric emotion system we deleted on 2026-11-03. **Kept as-is, unmaintained.**

**One recommendation from its README, repeated here:**

> **If you are just starting to build something like this, do not delete the emotion layer early.**
> Early retrieval is imprecise, and emotion-driven quota is one of the few coarse knobs that helps it
> recall the right thing. We deleted ours **after** retrieval had stabilized at hit@5 75%.

### The fish (`sandbox/example-fish/`)

**Written by an AI, in a sandbox.** No task was assigned. Nobody pushed it.

Stdlib only — `python fish.py --demo` shows it talking. No model, no parameters, just a handful of
`if`s and some word pools. After 42 revisions, its author can't predict half of what it says.

We include it to give the sandbox section a concrete shape: **what a place you can actually
work in eventually grows.**

## What is not included

- **Persona / role card**: that is its identity, and it does not ship with this project. Write your own.
- **Any data**: diaries, sessions, notes, chat logs — none of it is in this repo.
- **Any credentials**: all of `config.json` is examples; no real keys.

---

## License

See `qq-bridge/LICENSE` and `rix-brain/` (MIT unless stated otherwise).

**This is not something you can put into production.** Use it as a reference implementation, as a
list of holes to avoid, or as a starting point for discussion.
