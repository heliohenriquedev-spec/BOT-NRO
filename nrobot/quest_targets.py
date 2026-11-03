"""Extract explicit NPC target names independently of the monster sprite catalog."""
import re
from .npc_labels import clean,plain


def targets(lines):
    result=[];reading=False
    for raw in lines:
        for line in str(raw).splitlines():
            line=clean(line)
            match=re.search(r'monstros\s+necess[aá]rios\s*:\s*(.*)',line,re.I)
            if match:reading=True;line=match[1]
            elif reading and (line.startswith('[') or ':' in line):reading=False
            if not reading:continue
            line=re.split(r'\s*\[|\s+(?:Pode realizar|Base Level|Limite de tempo|Zeny|Item)\s*:',line,maxsplit=1,flags=re.I)[0]
            for item in re.split(r'[,;|]',line):
                found=re.fullmatch(r'\s*(\d+)\s+(.+?)\s*',item)
                if found:
                    name=found[2].strip().rstrip('.');entry=dict(name=name,count=int(found[1]))
                    if name and not any(plain(e['name'])==plain(name) for e in result):result.append(entry)
    return result
