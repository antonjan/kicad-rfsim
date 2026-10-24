# Linux and MCP

RFsim is Python; no plugin recompilation is needed. The headless pipeline has
been exercised with Ubuntu KiCad 10.0.7 and the existing openEMS installation.
EMerge is not yet exercised by the MCP adapter (which currently uses openEMS).

## Environment

Create a virtual environment and install the MCP requirements:

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r mcp_server/requirements.txt
```

The board worker uses `/usr/bin/python3` and the distro's KiCad `pcbnew`
bindings. Override `RFSIM_KICAD_PYTHON` if necessary. The solver uses a separate
Python with working `CSXCAD`, `openEMS`, NumPy and h5py imports:

```sh
export RFSIM_PYTHON=/home/anton/opt/openEMS/venv/bin/python
.venv/bin/python mcp_server/server.py
```

The server speaks stdio MCP; launch it from an MCP client, not an interactive
terminal. No HTTP listener or external account is needed. `RFSIM_WORK_DIR`
overrides the default `runs/` output directory. Board paths are local files.
This server is intended for a trusted local client and has the permissions of
its launching user.

## Register with Codex

From any directory:

```sh
codex mcp add rfsim \
  --env RFSIM_PYTHON=/home/anton/opt/openEMS/venv/bin/python \
  --env RFSIM_KICAD_PYTHON=/usr/bin/python3 \
  -- /home/anton/kicad-rfsim/.venv/bin/python \
  /home/anton/kicad-rfsim/mcp_server/server.py
codex mcp get rfsim
```

The registration follows [official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
Open a new client session after registering so it discovers the tools.
For other clients, use the same absolute command, script argument and environment.

## Tools and workflow

1. `inspect_board(board_path)` lists saved board pads and nets.
2. `prepare_simulation(board_path, ports, f_start_hz, f_stop_hz, ...)` extracts
   full board geometry into a fresh job. It returns settings, ports, warnings
   and an output directory. Ports are objects such as
   `{"reference":"J1","pad":"1","type":"msl"}`. Choose `lumped`, `msl`,
   `cpw`, `stripline`, or `coax` according to the actual feed geometry.
3. Review `model.json`, stackup, feed and domain before running.
4. `start_simulation(job_id)` starts openEMS in the background.
5. `simulation_status(job_id)` returns status, log tail and artifact paths.
6. `simulation_results(job_id)` summarizes S parameters and returns Touchstone,
   far-field JSON and line-data paths. `cancel_simulation(job_id)` terminates
   the process group while retaining output.

Jobs do not overwrite existing simulations. A server instance runs one solver
job at a time. Running status is tracked in memory: after restarting the server,
previous jobs have unknown status and their files remain available on disk.
Do not start another instance on the same work directory while a job is running.

## Patch antennas

Use the complete board, actual ground plane, substrate thickness, dielectric
constant and loss tangent. The adapter uses the saved stackup unless explicitly
overridden with `er`, `tand`, `h`, `cu_t` (thicknesses in mm).
Set the air margin for the antenna frequency; the 20 mm default is not a
universal antenna setting. Compare larger domains and finer meshes, inspect
termination logs, and check the feed before treating resonance, efficiency or
far-field patterns as reliable. A successful process exit alone does not prove
mesh/domain convergence. The initial microstrip test validates the software
pipeline, not antenna accuracy.

## KiCad GUI plugin

The PCM metadata now permits Linux. A package can be installed through KiCad's
Plugin and Content Manager with Install from File. For GUI plots, KiCad's Python
also needs scikit-rf, matplotlib and h5py; the MCP virtual environment does not
install these into the system interpreter. Set `RFSIM_PYTHON` in the environment
that launches KiCad. GUI interaction has not been validated here.

## Verification

```sh
RFSIM_PYTHON=/home/anton/opt/openEMS/venv/bin/python \
  /usr/bin/python3 validation/openems/run_headless_openems.py coarse
.venv/bin/python tests/mcp_smoke.py
```

The second command uses the first command's generated reference board and
exercises actual MCP discovery, extraction, solver execution and result reading.
