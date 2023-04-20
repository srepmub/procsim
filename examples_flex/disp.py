import os
import xml.etree.ElementTree as ET

import tabulate

props = ['sensorDetector', 'slicingGridFrameNumber', 'sliceStartPosition', 'sliceStopPosition', 'completenessAssesment']
prefix = 'FLX_RWS'

eop = '{http://www.opengis.net/eop/2.1}'

lines = []
for f in os.listdir('workspace'):
    if f.startswith(prefix):
        tree = ET.parse(f'workspace/{f}/{f.lower()}.xml')
        attrs = {}
        for info in tree.findall(f'{eop}metaDataProperty/{eop}EarthObservationMetaData/{eop}vendorSpecific/{eop}SpecificInformation'):
            attrs[info.find(f'{eop}localAttribute').text] = info.find(f'{eop}localValue').text
        lines.append([f] + [attrs[prop] for prop in props])

lines = sorted(lines, key = lambda x: (x[0], x[2])) # sort on filename, frame nr

print(tabulate.tabulate(lines, headers=['filename'] + props))