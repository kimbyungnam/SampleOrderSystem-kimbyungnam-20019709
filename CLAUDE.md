# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a pre-implementation repository. Only `semi/__init__.py` (empty) exists under the `semi` package; everything else is design documentation. Read `PRD.md` (requirements) and `DESIGN.md` (system design, package layout, DB schema, core flows) in full before writing any code — they define the domain rules this system must implement and are the source of truth, not this file.

## Commands

This project targets Python 3.14+

This project uses `flit_core` as the build backend and installs dev tooling via the `dev` extra.

```bash
pip install -e ".[dev]"      # install package + dev tools (ruff, basedpyright, commitizen, prek)
prek install                 # install git hooks (pre-commit + commit-msg), see .pre-commit-config.yaml
ruff check --fix .           # lint
ruff check --select I --fix . # import sorting
ruff format .                 # format
basedpyright                  # type check
```

There is no test suite yet. When one is added, wire the runner and single-test invocation into this file.

Commits must follow Conventional Commits (enforced by the `commitizen` hook on `commit-msg`); use `cz commit` to build compliant messages interactively.

## Architecture (per DESIGN.md)

Single-process, two-thread console app: the main thread runs the console menu loop, and a daemon background worker thread advances production in real time (1s tick), independent of menu interaction. Both threads share the service/repository layers and a single SQLite file (WAL mode); writes are serialized through one process-wide `threading.Lock` in the service layer (approve/reject/release/tick) to prevent races between menu-driven transactions and the ticking worker.

Planned package layout:
```
semi/
├── domain/       # Sample, Order, ProductionJob dataclasses; OrderStatus/JobStatus enums
├── storage/      # db.py (connection/PRAGMA/schema init) + one repository per entity
├── services/     # SampleService, OrderService, ProductionService, MonitoringService
├── scheduler/    # background_worker.py — daemon Thread calling ProductionService.tick() every 1s
├── cli/          # app.py (entrypoint: init DB → start worker → menu loop), menus.py
```

### Domain model and core invariant

Orders flow `RESERVED → CONFIRMED|PRODUCING → RELEASE`, or `RESERVED → REJECTED`. Stock (`stock_quantity`) is only ever decremented at RELEASE time and only ever incremented when a production job completes — never at approval time. This is deliberate: approval only makes a *logical* reservation against "available stock", so that the invariant `stock_quantity >= sum(quantity of un-released CONFIRMED orders for that sample)` holds at all times, which guarantees RELEASE never fails for insufficient stock.

**Available stock** (used only to decide approve → CONFIRMED vs. approve → PRODUCING):
```
available = stock_quantity
          - SUM(quantity WHERE sample_id=? AND status='CONFIRMED')
          - SUM(quantity - shortfall_quantity WHERE sample_id=? AND status='PRODUCING')  -- joined via production_jobs
```
The `PRODUCING` term is the stock each such order already claimed *at the moment it was approved* (`order.quantity - shortfall_quantity`), and stays excluded from `available` until that order transitions to CONFIRMED. `RESERVED` orders never reduce `available`.

This differs from the "outstanding" figure used for monitoring/stock-status (§4.5 of PRD, §4.4 of DESIGN), which sums `RESERVED + CONFIRMED + PRODUCING` quantities per sample — a different, broader "potential demand" view than the approval-time `available` calculation. Don't conflate the two when implementing.

Production quantity/time, when an order is approved with insufficient available stock:
```
shortfall = order.quantity - available
actual_quantity = ceil(shortfall / yield_rate)   # yield_rate already encodes defect rate; actual_quantity IS the stock increase, not multiplied by yield again
total_duration_seconds = avg_production_seconds * actual_quantity
```
Queued production jobs run to completion as originally computed — they are never recalculated or early-completed even if other completions change the stock picture in the meantime. The single production line processes the queue strictly FIFO (`enqueued_at`, tie-broken by `job_id`).

Stock status classification for monitoring (checked in this order — rule 14 in PRD): `stock_quantity == 0` → 고갈(depleted), else `stock_quantity >= outstanding` → 여유(sufficient), else → 부족(short).

### Validation invariants
- Sample registration: unique `sample_id`, `avg_production_seconds > 0`, `0 < yield_rate <= 1` (yield_rate > 1 would break the oversell-prevention invariant above — see PRD §4.2, rule 17).
- Order creation: `sample_id` must reference an existing sample, `quantity > 0`.
- Approve/reject only valid on `RESERVED` orders; release only valid on `CONFIRMED` orders.

There is no auth/role separation (PRD §5, rule 15) — whoever runs the console has unrestricted access to every menu.
