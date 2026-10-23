# Architecture

```
src/patchloop/
  agent/     loop.py (the loop) · models.py (adapters, pricing) · tools.py (6 tools) · context.py (compaction)
             prompts.py · trajectory.py (JSONL)
  sandbox/   docker_env.py (one locked-down container per episode) · local_env.py (--unsafe-local, toy only)
  benchgen/  mutators.py (strategy A) · llm_rewrite.py (strategy B) · validate.py · issues.py · build.py
  evals/     runner.py · grader.py · metrics.py · report.py · viewer/render.py
  mcp_server/server.py
```

## The loop (one episode)

```mermaid
sequenceDiagram
    autonumber
    participant R as Runner
    participant L as loop.run_episode
    participant C as ContextTracker
    participant M as ModelAdapter
    participant T as Toolbox
    participant S as Sandbox (docker exec)
    participant J as Trajectory (JSONL)
    R->>S: start container (bug applied, fresh git)
    R->>L: problem statement, test cmd, budget
    loop each step (<= max_steps, < cost, < wall time)
        L->>C: next prompt > soft limit?
        opt yes
            L->>M: "summarize your progress" (appended, not edited)
            L->>L: messages = fresh [task + summary + last 2 observations]
        end
        L->>M: complete(system, messages, tools)
        Note over L,M: 429 / 5xx / overloaded -> backoff + jitter, logged
        M-->>L: ModelTurn(text, tool_calls, usage, stop_reason, raw)
        alt refusal
            L-->>R: model_refusal
        else no tool call
            L->>L: append nudge
        else tool calls
            L->>T: execute each call in order
            T->>S: docker exec ... (timeout)
            S-->>T: exit code + output
            T-->>L: truncated observation (errors are observations)
            L->>L: loop detector: 3x same -> nudge, 5x -> stop
        end
        L->>J: step record (text, calls, observations, usage, cost, latency)
    end
    L-->>R: EpisodeResult(stop_reason, ...)
    R->>S: git diff, tests hash
    R->>R: grade(diff) in a FRESH container
```

## The sandbox boundary

```mermaid
flowchart LR
    subgraph Host["Host (macOS / Linux)"]
        loop["agent loop<br/>(Python)"]
        run["_run_docker()<br/>asserts argv[0]=='docker'"]
        tests[("tests snapshot<br/>~/.cache/patchloop")]
        env[".env secrets<br/>(never passed in)"]
        loop -->|"command strings"| run
    end
    subgraph Container["Episode container"]
        direction TB
        ws["/workspace<br/>anonymous volume, writable"]
        ro["/workspace/&lt;tests&gt;<br/>bind mount :ro"]
        tmp["/tmp tmpfs"]
        rootfs["root fs --read-only"]
        user["uid 1000, cap-drop ALL,<br/>no-new-privileges, --init"]
        limits["1 CPU · 1 GB · 256 PIDs"]
    end
    run -->|"docker exec ... timeout N bash -c"| Container
    tests -.->|"read-only"| ro
    Container -.-x|"--network none"| Internet((Internet))
    env -.-x Container
```

## Data flow for an experiment

```mermaid
flowchart LR
    A["config/repos.toml"] --> B["benchgen: mutate → validate x2 → issue → leak check"]
    B --> C[("bench/tasks/*.json")]
    C --> D["runner (parallel, resumable, pilot)"]
    D --> E[("results/&lt;run&gt;/episodes + trajectories")]
    E --> F["grader (fresh container)"] --> E
    E --> G["report.py → summary.json, docs/EVAL_REPORT.md"]
    E --> H["viewer.html"]
```
