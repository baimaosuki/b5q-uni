"""Native command-line bounds and independent P4/P5 fallback selections."""
import json
NATIVE_COMMAND_LINE_BYTES=1024

def line(values,default=False):
    text=' '.join(values)
    limit=NATIVE_COMMAND_LINE_BYTES-1
    if not text.isascii()or '\x00'in text or len(text.encode())>limit:
        raise ValueError('DarwinBoot/XNU command line overflow or invalid text')
    return text

def profiles(arguments):
    # Runtime Bluetooth tracing is a full-profile diagnostic. Leave it out of
    # fallback entries so their explicit b5q-f=0 selector still fits XNU's
    # fixed 1024-byte command line without weakening the length check.
    fallback=['b5q-dp=0'if v.startswith('b5q-dp=')else v for v in arguments
              if not v.startswith('log-bluetooth=')]
    safe=['wifi=0'if v.startswith('wifi=')else'bluetooth=0'if v.startswith('bluetooth=')else'usb=0'if v.startswith('usb=')else v for v in fallback]
    args={'xnu':line(arguments,True),'daily':line([*fallback,'b5q-f=0']),
        'safe':line([*safe,'b5q-f=0']),
        'ram-fallback':line(['b5q-data-ufs=0'if v.startswith('b5q-data-ufs=')else v for v in [*safe,'b5q-f=0']])}
    titles=['b5q macOS - Full selected features','b5q - Desktop + Touch / USB / BT / Wi-Fi',
        'b5q - Desktop + Touch safe fallback','b5q - Original 4 GiB RAM Data recovery']
    result=[]
    for (name,value),title in zip(args.items(),titles):
        e=dict(id=name,title=title,type='xnu',path='Payloads/'+('RAM/'if name=='ram-fallback'else'')+'kernel.macho',args=value)
        if name=='ram-fallback':e['initrd']='Payloads/scratch-data.img'
        result.append(e)
    return result

def config(arguments):
    text='version = 1\n[boot]\ntimeout = 3\ndefault = "xnu"\n[kits]\nautoload = false\n[[driver]]\npath = "Drivers/DarwinBoot.efi"\n'
    for e in profiles(arguments):text+='[[entry]]\n'+''.join(k+' = '+json.dumps(v)+'\n'for k,v in e.items())
    return text+'[[entry]]\nid = "reset"\ntitle = "Restart"\ntype = "action"\naction = "reset"\n[[entry]]\nid = "shutdown"\ntitle = "Power off"\ntype = "action"\naction = "shutdown"\n'
