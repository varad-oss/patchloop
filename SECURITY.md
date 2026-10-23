# Security

PatchLoop runs model-written shell commands, so its sandbox is the part that matters most. It is a research and
portfolio project, not a hardened multi-tenant service: it relies on Docker's isolation, and a container-escape
bug in the kernel or Docker would defeat it.

## What the sandbox is meant to guarantee

Each episode runs in its own container with no network, a read-only root filesystem, the tests mounted read-only,
a non-root user, all capabilities dropped, `no-new-privileges`, and CPU, memory and PID limits. Agent commands are
only ever issued via `docker exec`; nothing the model writes runs on the host. The grader also rejects patches that
touch tests, `conftest.py` or pytest configuration. These properties are tested in
[`tests/integration/test_sandbox_security.py`](tests/integration/test_sandbox_security.py).

## Reporting an issue

If you find a way for an agent command to reach the host, the network, or the test files, or to make the grader
accept an unfixed bug, please open an issue with:

- the command or patch that does it;
- your Docker version and OS;
- what you observed (for example a file written on the host, or a test edit that succeeded).

These are exactly the bugs the project exists to prevent, and confirmed ones will get a regression test.

Do not include API keys or personal data in reports. None are needed: the default setup runs locally for free.
