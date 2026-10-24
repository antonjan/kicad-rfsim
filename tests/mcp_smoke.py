"""End-to-end MCP protocol test against a real two-port openEMS job."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

async def main():
    env = dict(os.environ, RFSIM_PYTHON='/home/anton/opt/openEMS/venv/bin/python')
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / 'mcp_server/server.py')], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert len(tools.tools) == 6
            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                if result.isError:
                    raise AssertionError(result)
                return json.loads(result.content[0].text)
            board = str(ROOT / 'validation/openems/out_coarse/microstrip_50ohm.kicad_pcb')
            info = await call('inspect_board', {'board_path': board})
            ports = [{'reference': p['reference'], 'pad': p['pad'], 'type': 'msl'} for p in info['pads']]
            job = await call('prepare_simulation', dict(board_path=board, ports=ports,
                f_start_hz=1e9, f_stop_hz=6e9, margin_mm=4))
            job_id = job['job_id']
            await call('start_simulation', {'job_id': job_id})
            for _ in range(180):
                status = await call('simulation_status', {'job_id': job_id})
                if status['status'] != 'running':
                    break
                await asyncio.sleep(1)
            assert status['status'] == 'completed', status
            results = await call('simulation_results', {'job_id': job_id})
            assert results['traces']['S11']['max_db'] < -7, results
            assert results['traces']['S21']['min_db'] > -3, results
            print(json.dumps(results, indent=2))
            bad = await client.call_tool('simulation_status', {'job_id': '../outside'})
            assert bad.isError
            print('PASS: MCP discovery, extraction, execution, results, invalid ID')

asyncio.run(main())
