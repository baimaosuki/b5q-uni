"""Preserve hash-qualified Samsung GPU bytes through local ADT regeneration."""
import hashlib,re
from pathlib import Path

def expected():
    header=(Path(__file__).resolve().parents[1]/'package/B5qPeripheralHardware.h').read_text()
    result={}
    for name,stem in [('b5q-gmu-fw','gmu'),('b5q-sqe-fw','sqe'),('b5q-zap-fw','zap')]:
        size=int(re.search(r'constexpr uint64_t '+stem+r'FirmwareBytes=(\d+);',header)[1])
        values=re.search(stem+r'FirmwareSha256\[32\]=\{([^}]+)\}',header)[1]
        digest=bytes(int(v,16)for v in values.split(',')).hex()
        result[name]=(size,digest)
    return result

def verify(chosen):
    proof={}
    for name,(size,digest)in expected().items():
        data=chosen.get(name)
        if not isinstance(data,bytes)or len(data)!=size:raise ValueError('Missing/wrong-size GPU ADT firmware: '+name)
        actual=hashlib.sha256(data).hexdigest()
        if actual!=digest:raise ValueError('GPU ADT firmware SHA256 mismatch: '+name)
        proof[name]={'bytes':size,'sha256':actual}
    return proof

def preserve(board,chosen):
    proof=verify(chosen)
    target=board.setdefault('adt',{}).setdefault('chosen',{}).setdefault('bytes',{})
    for name in proof:
        if name in target and bytes.fromhex(target[name])!=chosen[name]:raise ValueError('Conflicting GPU ADT firmware: '+name)
        target[name]=chosen[name].hex()
    return proof


def manifest():
    # Canonical sizes/hashes are the same original-device constants used by XNU.
    from pathlib import Path
    header=(Path(__file__).resolve().parents[1]/'package/B5qPeripheralHardware.h').read_text()
    result={}
    for short,key in [('gmu','b5q-gmu-fw'),('sqe','b5q-sqe-fw'),('zap','b5q-zap-fw')]:
        size=int(re.search(r'constexpr uint64_t '+short+r'FirmwareBytes=(\d+);',header)[1])
        values=re.search(short+r'FirmwareSha256\[32\]=\{([^}]+)\}',header)[1]
        digest=bytes(int(v,16)for v in values.split(',')).hex()
        result[key]=(size,digest)
    return result

def verify(chosen):
    result={}
    for name,(size,digest)in manifest().items():
        value=chosen.get(name)
        if not isinstance(value,bytes)or len(value)!=size:
            raise ValueError('GPU ADT firmware missing/size mismatch: '+name)
        if hashlib.sha256(value).hexdigest()!=digest:
            raise ValueError('GPU ADT firmware SHA mismatch: '+name)
        result[name]=dict(bytes=size,sha256=digest)
    return result

def preserve(board,chosen):
    result=verify(chosen)
    properties=board.setdefault('adt',{}).setdefault('chosen',{}).setdefault('bytes',{})
    for name in result:properties[name]=chosen[name].hex()
    return result
