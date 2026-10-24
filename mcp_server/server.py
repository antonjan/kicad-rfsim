"""Local stdio MCP interface for RFsim. Solvers run outside the MCP process."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugins'))
import solverenv

mcp = FastMCP('RFsim')
WORK = Path(os.environ.get('RFSIM_WORK_DIR', ROOT / 'runs')).resolve()
KICAD_PYTHON = os.environ.get('RFSIM_KICAD_PYTHON', '/usr/bin/python3')
JOBS = {}
LOCK = threading.Lock()


def job_dir(job_id):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Invalid job ID')
    folder = WORK / job_id
    if not folder.is_dir():
        raise ValueError('Unknown job ID')
    return folder


def worker(request):
    result = subprocess.run([KICAD_PYTHON, str(ROOT / 'mcp_server/board_cli.py')],
        input=json.dumps(request), capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError(result.stderr[-6000:])
    return json.loads(result.stdout)


@mcp.tool()
def inspect_board(board_path: str) -> dict:
    """List saved board pads and nets to choose simulation feeds. Does not modify the board."""
    path = Path(board_path).expanduser().resolve(strict=True)
    return worker({'action': 'inspect', 'board': str(path)})


@mcp.tool()
def prepare_simulation(board_path: str, ports: list[dict], f_start_hz: float,
        f_stop_hz: float, mesh: str = 'coarse', margin_mm: float = 20,
        threads: int = 2, max_timesteps: int = 100000,
        end_criteria: float = 1e-4, n_freq: int = 401,
        field_frequency_hz: float | None = None,
        substrate: dict | None = None) -> dict:
    """Extract full board into a new job without running it. Ports: [{reference:'J1', pad:'1', type:'lumped'}]. Types: lumped/msl/cpw/stripline/coax (must suit geometry). Frequencies in Hz; margin in mm. Substrate override: er,tand,h,cu_t (thicknesses mm); omitted uses saved stackup. Antennas require air-margin and mesh convergence studies."""
    values = [f_start_hz, f_stop_hz, margin_mm, end_criteria]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Settings must be finite')
    if not 0 < f_start_hz < f_stop_hz or margin_mm <= 0:
        raise ValueError('Require 0 < start < stop and positive margin')
    if mesh not in solverenv.RES_DIV or not 1 <= threads <= (os.cpu_count() or 1):
        raise ValueError('Invalid mesh or CPU thread count')
    if not 1 <= max_timesteps <= 10000000 or not 2 <= n_freq <= 10001 or not 0 < end_criteria < 1:
        raise ValueError('Invalid run limits')
    if not ports or len(ports) > 16:
        raise ValueError('Select 1 to 16 ports')
    for port in ports:
        if port.get('type', 'lumped') not in {'lumped', 'msl', 'cpw', 'stripline', 'coax'}:
            raise ValueError('Unknown port type')
    if field_frequency_hz is not None and not f_start_hz <= field_frequency_hz <= f_stop_hz:
        raise ValueError('Field frequency must be within sweep')
    if substrate is not None:
        if set(substrate) != {'er', 'tand', 'h', 'cu_t'} or not all(math.isfinite(v) for v in substrate.values()):
            raise ValueError('Substrate requires finite er,tand,h,cu_t')
        if substrate['er'] < 1 or substrate['tand'] < 0 or min(substrate['h'], substrate['cu_t']) <= 0:
            raise ValueError('Invalid substrate')
    settings = dict(f_start=f_start_hz, f_stop=f_stop_hz, mesh=mesh,
        margin_mm=margin_mm, threads=threads, max_timesteps=max_timesteps,
        end_criteria=end_criteria, n_freq=n_freq, z0=50.0, solver='openems',
        f_field=field_frequency_hz or (f_start_hz + f_stop_hz) / 2)
    model = worker({'action': 'extract', 'board': str(Path(board_path).expanduser().resolve(strict=True)),
                    'ports': ports, 'settings': settings, 'substrate': substrate})
    job_id = uuid.uuid4().hex
    folder = WORK / job_id
    folder.mkdir(parents=True)
    (folder / 'model.json').write_text(json.dumps(model, indent=2))
    return {'job_id': job_id, 'directory': str(folder), 'settings': settings,
            'ports': model['ports'], 'warnings': model.get('warnings', [])}


@mcp.tool()
def start_simulation(job_id: str) -> dict:
    """Start a prepared openEMS job in the background. One running job per server."""
    folder = job_dir(job_id)
    with LOCK:
        if any(p.poll() is None for p in JOBS.values()):
            raise ValueError('A simulation is already running')
        if (folder / 'run.log').exists():
            raise ValueError('Prepare a new job to rerun; existing artifacts are preserved')
        python = solverenv.solver_python()
        if not python:
            raise ValueError('Set RFSIM_PYTHON to the openEMS Python interpreter')
        with (folder / 'run.log').open('wb') as log:
            process = subprocess.Popen([python, '-u', str(ROOT / 'plugins/openems_runner.py'),
                str(folder / 'model.json'), str(folder)], stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
        JOBS[job_id] = process
    return {'job_id': job_id, 'pid': process.pid, 'status': 'running'}


@mcp.tool()
def simulation_status(job_id: str, log_lines: int = 40) -> dict:
    """Get process status, recent log output and artifact paths. After server restart status is unknown."""
    folder = job_dir(job_id)
    process = JOBS.get(job_id)
    code = process.poll() if process else None
    status = ('running' if code is None else 'completed' if code == 0 else 'failed') if process else ('unknown' if (folder / 'run.log').exists() else 'prepared')
    log = folder / 'run.log'
    return {'job_id': job_id, 'status': status, 'exit_code': code,
            'log': '\n'.join(log.read_text(errors='replace').splitlines()[-max(1, min(log_lines, 200)):]) if log.exists() else '',
            'artifacts': [str(p) for p in sorted(folder.iterdir()) if p.is_file()]}


@mcp.tool()
def cancel_simulation(job_id: str) -> dict:
    """Terminate this server's running job and its solver process group, retaining artifacts."""
    job_dir(job_id)
    with LOCK:
        process = JOBS.get(job_id)
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    return simulation_status(job_id)


@mcp.tool()
def simulation_results(job_id: str) -> dict:
    """Summarize completed S parameters and return far-field/line JSON artifact paths. Read logs for convergence warnings."""
    folder = job_dir(job_id)
    status = simulation_status(job_id)
    if status['status'] != 'completed':
        raise ValueError('Results require a successful job in this server session')
    import numpy as np
    import skrf
    files = sorted(folder.glob('results.s*p'))
    if not files:
        raise ValueError('No Touchstone result produced; inspect log')
    network = skrf.Network(str(files[0]))
    traces = {}
    for i in range(network.nports):
        for j in range(network.nports):
            db = 20 * np.log10(np.maximum(np.abs(network.s[:, i, j]), 1e-15))
            idx = int(np.argmin(db))
            traces[f'S{i+1}{j+1}'] = {'min_db': float(db[idx]), 'min_frequency_hz': float(network.f[idx]), 'max_db': float(db.max())}
    return {'job_id': job_id, 'touchstone': str(files[0]), 'traces': traces,
            'farfield_files': [str(p) for p in sorted(folder.glob('farfield*.json'))],
            'lines_file': str(folder / 'lines.json') if (folder / 'lines.json').exists() else None,
            'log': status['log']}


if __name__ == '__main__':
    mcp.run(transport='stdio')
