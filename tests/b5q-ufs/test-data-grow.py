#!/usr/bin/env python3
"""Native APFS remount/ownership regression using the real builder helper."""
import importlib.util,sys,tempfile,plistlib
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'scripts/b5q-install'))
s=importlib.util.spec_from_file_location('grow',R/'scripts/b5q-install/build-persistent-data.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='b5q-native-remount-')as td:
 actual=Path(td)/'new-mount';actual.mkdir()
 info=dict(Mounted=True,VolumeUUID=m.DATA_UUID,MountPoint=str(actual),DeviceIdentifier='disk8s1')
 for explicit_mounted in (True,False):
  response=dict(info)
  if not explicit_mounted:response.pop('Mounted')
  with patch.object(m.subprocess,'check_output',return_value=plistlib.dumps(response))as call,patch.object(m.subprocess,'run')as run:
   assert m.mounted_volume('disk8s1')==actual
   assert all(x.args[0]==['diskutil','info','-plist','disk8s1']for x in call.call_args_list)
   run.assert_called_once_with(['sudo','-n','diskutil','enableOwnership','disk8s1'],check=True)
 with patch.object(m.subprocess,'check_output',side_effect=[plistlib.dumps(dict(info,Mounted=False)),plistlib.dumps(info)]),patch.object(m.subprocess,'run')as run:
  assert m.mounted_volume('disk8s1',actual)==actual
  assert [x.args[0]for x in run.call_args_list]==[['diskutil','mount','-mountPoint',str(actual),'disk8s1'],['sudo','-n','diskutil','enableOwnership','disk8s1']]
 for bad in (dict(info,Mounted=False),dict(info,VolumeUUID='0'*36),dict(info,MountPoint='relative'),dict(info,MountPoint=str(actual/'missing'))):
  with patch.object(m.subprocess,'check_output',return_value=plistlib.dumps(bad)),patch.object(m.subprocess,'run'):
   try:m.mounted_volume('disk8s1')
   except ValueError:pass
   else:raise AssertionError(bad)
print('PASS 7 production mount cases: explicit/implicit mounted flags, unmounted remount, ownership ALWAYS enabled, UUID/path refusals')
