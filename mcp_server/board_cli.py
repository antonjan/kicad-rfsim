"""KiCad-side worker; stdout contains JSON only, no plugin registration."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins'))
import pcbnew
import board_reader


def main(request):
    board = pcbnew.LoadBoard(request['board'])
    pads = {(fp.GetReference(), p.GetNumber()): p
            for fp in board.GetFootprints() for p in fp.Pads()}
    if request['action'] == 'inspect':
        return {'kicad': pcbnew.GetBuildVersion(), 'pads': [
            {'reference': ref, 'pad': num, 'net': p.GetNetname(),
             'x_mm': pcbnew.ToMM(p.GetPosition().x),
             'y_mm': pcbnew.ToMM(p.GetPosition().y)}
            for (ref, num), p in sorted(pads.items())]}
    selected = []
    for port in request['ports']:
        key = (port['reference'], str(port['pad']))
        if key not in pads:
            raise ValueError('Unknown reference/pad: %s' % (key,))
        selected.append(pads[key])
    if len({p.m_Uuid.AsString() for p in selected}) != len(selected):
        raise ValueError('Duplicate ports')
    settings = request['settings']
    model = board_reader.extract(board, selected, settings['margin_mm'],
        substrate=request.get('substrate'), f_stop=settings['f_stop'],
        mesh=settings['mesh'], subregion=False)
    for extracted, requested in zip(model['ports'], request['ports']):
        kind = requested.get('type', extracted['type'])
        if extracted.get('drill') and kind == 'lumped':
            raise ValueError('Through-hole pads require a coax or line feed')
        if kind == 'coax' and not extracted.get('coax'):
            raise ValueError('No coax return gap found')
        if kind in {'msl', 'cpw', 'stripline'} and not extracted.get('direction'):
            raise ValueError('Line port needs an axis-aligned feed track')
        if kind == 'cpw' and not extracted.get('gap'):
            raise ValueError('No coplanar gap found')
        if kind == 'stripline' and not extracted.get('height'):
            raise ValueError('No stripline reference planes found')
        extracted['type'] = kind
    model['settings'] = settings
    return model


if __name__ == '__main__':
    print(json.dumps(main(json.load(sys.stdin))))
