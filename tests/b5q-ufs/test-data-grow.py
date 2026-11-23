#!/usr/bin/env python3
"""Regression for diskutil changing the mountpoint during native APFS growth."""
import importlib.util,sys,tempfile,plistlib
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'scripts/b5q-install'))
s=importlib.util.spec_from_file_location('grow',R/'scripts/b5q-install/build-persistent-data.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='b5q-native-remount-')as td:
 actual=Path(td)/'new-mount';actual.mkdir()
 info=dict(Mounted=True,VolumeUUID=m.DATA_UUID,MountPoint=str(actual),DeviceIdentifier='disk8s1')
 with patch.object(m.subprocess,'check_output',return_value=plistlib.dumps(info))as call:
  assert m.mounted_volume('disk8s1')==actual;call.assert_called_once_with(['diskutil','info','-plist','disk8s1'])
 # Regression from actual CI: resize succeeds but leaves the volume unmounted.
 with patch.object(m.subprocess,'check_output',side_effect=[plistlib.dumps(dict(info,Mounted=False)),plistlib.dumps(info)]),patch.object(m.subprocess,'run')as run:
  assert m.mounted_volume('disk8s1',actual)==actual
  assert run.call_args_list[0].args[0]==['diskutil','mount','-mountPoint',str(actual),'disk8s1']
  assert run.call_args_list[1].args[0]==['diskutil','enableOwnership','disk8s1']
 for bad in (dict(info,Mounted=False),dict(info,VolumeUUID='0'*36),dict(info,MountPoint='relative'),dict(info,MountPoint=str(actual/'missing'))):
  with patch.object(m.subprocess,'check_output',return_value=plistlib.dumps(bad)):
   try:m.mounted_volume('disk8s1')
   except ValueError:pass
   else:raise AssertionError(bad)
print('PASS remounted Data path by same device+UUID; reject unmounted/wrong UUID/relative/missing mountpoint (6 cases)')
