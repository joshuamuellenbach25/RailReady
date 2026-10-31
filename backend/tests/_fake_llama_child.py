"""Stand-ins for the llama.cpp call, executed inside the extraction child process (no model, no AI calls)."""
import json
import os
import time

NULLS = json.dumps({k: None for k in ("inspected_quantity", "repair_quantity", "tie_specification", "material_responsibility", "work_location")})


def abort_now(messages):
    os.abort()  # same effect as GGML_ASSERT -> ggml_abort: native abort of the process


def sleep_long(messages):
    time.sleep(60)
    return NULLS


def ok(messages):
    return NULLS


def ok_logged(messages):
    log = os.environ["P17_FAKE_LOG"]
    with open(log, "a") as f:
        f.write(f"start {time.time()} {os.getpid()}\n")
    time.sleep(0.4)
    with open(log, "a") as f:
        f.write(f"end {time.time()} {os.getpid()}\n")
    return NULLS
