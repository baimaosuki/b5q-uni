"""Explicit cache selection for the shared register-only GMU service."""
from pathlib import Path
def prepare(source,destination):
 source,destination=map(Path,(source,destination));text=source.read_text()
 old='memory->map(kIOMapAnywhere)';assert text.count(old)==1,'Pinned GMU source changed'
 destination.parent.mkdir(parents=True,exist_ok=True)
 destination.write_text(text.replace(old,'memory->map(kIOMapAnywhere|kIOMapInhibitCache)'))
 return destination
