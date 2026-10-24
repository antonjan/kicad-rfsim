# Linux validation — 2026-10-24

Environment: KiCad/pcbnew 10.0.7, openEMS v0.37.0-rc1-8-g27dcde1,
CSXCAD v0.7.0-rc1-8-gcb931b7. Solver interpreter:
`/home/anton/opt/openEMS/venv/bin/python`.

- Upstream coarse microstrip validation: PASS. Worst S11 −11.1 dB,
  minimum S21 −0.3 dB; both excitations reached the 1e-4 end criterion.
- Real stdio MCP client validation: PASS. Initialized the server, discovered
  six tools, inspected the saved board, extracted a new model, started a
  two-port simulation, polled progress and retrieved results. Invalid job ID
  rejected. Worst S11 −11.054 dB; minimum S21 −0.255 dB.
- MCP output: `runs/507d71c8d0c74fc2bb3554e75e6f20cd/` (ignored generated data).
  Touchstone, two far-field JSON files, line data and solver logs were produced.
- MCP client transport test stalled under the restricted execution sandbox;
  the same test completed outside it. Local Codex registration was verified
  with `codex mcp get rfsim`.
- Python compilation and `git diff --check`: PASS.

Not yet validated: GUI interaction, EMerge via MCP, cancellation under load,
patch-antenna resonance/gain against a reference, mesh/domain convergence.
The reference line test establishes a working pipeline, not antenna accuracy.
