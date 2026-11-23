import json
import re
import sys

import docx
from docx.table import Table

d = docx.Document(sys.argv[1])
body = d.element.body
section = ""; reqs = {}; order=[]
idre = re.compile(r'^(BR|FR|NFR|TC|UC|RSK|IF|PAC|AD|AP|SP|CN|A|D|C|SO|R)-\d{1,4}$')
for child in body.iterchildren():
    tag = child.tag.split('}')[1]
    if tag == 'p':
        from docx.text.paragraph import Paragraph
        p = Paragraph(child, d)
        if p.style is not None and p.style.name.startswith('Heading') and p.text.strip():
            section = p.text.strip()
    elif tag == 'tbl':
        tb = Table(child, d); header=None
        for r in tb.rows:
            cells=[]; prev=None
            for c in r.cells:
                if c._tc is prev: continue
                prev=c._tc; cells.append(re.sub(r'\s+',' ',c.text).strip())
            if header is None: header=cells; continue
            if cells and idre.match(cells[0]):
                rid=cells[0]
                rec={'id':rid,'section':section,'fields':dict(zip(header,cells))}
                if rid not in reqs:
                    reqs[rid]=rec; order.append(rid)
                else:
                    reqs[rid].setdefault('other_refs',[]).append(section)
json.dump([reqs[i] for i in order], open(sys.argv[2],'w'), indent=1)
from collections import Counter

print(Counter(r.split('-')[0] for r in order))
