# Frame timing: the 60 fps limiter and the 144 fps experiment

Conclusion up front: **the engine advances one logic tick per rendered frame,
and the frame rate is capped at 60 by a hardcoded constant.** Raising the cap
makes the game run proportionally fast (verified: 144 fps → 2.4× speed).

## The limiter

The function entered at RVA `0x3c330` (called from the main loop right after
the draw call) contains the pacing logic. Relevant globals:

| global | meaning |
|---|---|
| `0x140c22100` | frame interval, in ms |
| `0x140c22118` | base time |
| `0x140c22128` | accumulated offset |
| `0x140c22130` | frame counter |
| `0x140c220e0` | thunk → `GetNowCount` (ms clock) |
| `0x140c220f0` | sleep function pointer (set to `0x14003c290`) |
| `0x140c220f8` | timer frequency (1000) |
| `0x140c22110` | 1,000,000 (1 ms in ns) |

Deadline loop (`0x14003c488`):

```
target = frame_counter * interval + base
if (now - target > interval) { resync }          # drop frames when late
else {
    frame_counter++;
    target = frame_counter * interval + base;
    while ((remaining = target - base - now) > 0)
        sleep(min(remaining_ns, 0.95 ms));       # 0x14003c540
}
```

The sleep function at `0x14003c290` is a high-resolution waitable timer:
`CreateWaitableTimerExW(..., 0x2 /* HIGH_RESOLUTION */)` (RVA `0x3caf9`),
`SetWaitableTimerEx` + `WaitForSingleObject(INFINITE)`.

### Where 60 comes from

`0x14003cb85` computes the interval:

```
interval = (int)( (double)freq / 60.0 + 0.5 )    # freq = 1000 -> 17 ms
```

The `60.0` is a double in `.rdata` at **RVA `0x30ce38`**, with exactly one
code reference in the whole binary. That single constant is the cap.

## Experiment 1 — shortening the sleep slices (did nothing)

The proxy can multiply every `SetWaitableTimerEx` due time (`frame_scale`).
With `frame_scale = 0.4167` the log showed the slices got shorter exactly as
requested, while the frame rate stayed 60:

```
frame timer:  915 waits/sec, last wait 0.950 ms, period=0, scale=1.0000
frame timer: 2066 waits/sec, last wait 0.950 ms, period=0, scale=0.4167
```

915 / 2066 ≈ 0.44 ≈ 0.4167 — the scaling worked, but the loop simply spun
more often inside the same 17 ms deadline. This proved the pacing is
**deadline-based**, not slice-based.

## Experiment 2 — patching the constant (works, and proves coupling)

The proxy rewrites the `60.0` double at load time (`target_fps` option in
`th06nc_mod.ini`), before DxLib initialises:

```
config: title set, frame_scale=1.0000, target_fps=144.0
frame-rate constant at 000000014030CE38 = 60.0000 (want 144.0)
patched frame-rate constant: 60.0000 -> 144.0000
```

Result on a 144 Hz display (Hyprland, `eDP-1 1920x1080@144.003`):

- the in-game FPS counter went to ~143 (interval becomes `1000/144 + 0.5`
  → 7 ms),
- **the game ran ~2.4× fast** — bullets, enemies and the player all move at
  2.4× speed.

That is the coupling proof: the update path runs once per frame, so frame rate
*is* game speed.

## Why this was expected

`replay/th6_NN.rpy` files start with `T6RP` and store one obfuscated input
record per logic tick. Deterministic replay playback requires a fixed tick
rate, so the engine cannot simply be ticked faster without breaking replays,
score data, ECL script timing, RNG sequencing and the difficulty balance
tuned around 60 Hz.

## What a real 144 fps mod would need

| approach | difficulty | notes |
|---|---|---|
| raise the cap (this repo) | trivial | game runs 2.4× fast — not playable |
| decouple update from present | medium/hard | run the 60 Hz update only when a 1/60 s accumulator is due; draw + present every display frame. Game speed stays correct, input latency improves. Requires identifying the update function (`0x14007b120` is called once per loop) and reworking the loop, which the DLL proxy would have to hook inline. |
| interpolate entities between ticks | hard | cosmetic only; collisions stay on the 60 Hz state |
| true 144 Hz logic | impractical | rescale every per-frame constant, rebalance, break replays/scores |

## Reproducing

```ini
# th06nc_mod.ini
target_fps=144      # -> ~143 fps, game runs 2.4x fast
# target_fps=60     # -> normal
frame_scale=1.0     # slice multiplier (diagnostic only)
```

The log prints one line per second, e.g.
`frame timer: 915 waits/sec, last wait 0.950 ms, period=0, scale=1.0000`,
which is how the deadline behaviour was identified. Annotated excerpts from the
three runs are in [`evidence-frame-timer.log`](evidence-frame-timer.log).
