"""Reproducible b5q-only display/presenter adaptation; physical GOP is unchanged."""
import hashlib,json,os,subprocess
from pathlib import Path
DEVICE=Path(os.environ.get('UNIXNU_DEVICE',Path(__file__).resolve().parents[1])).resolve()
def prepare(tree):
    tree=Path(tree);rows=[]
    for component,name in [('GopFramebuffer','b5q-review18-gop.patch'),('AdrenoMetal','b5q-review18-presenter.patch'),('AdrenoMetal','b5q-review21-metal-family-cache.patch'),('AdrenoMetal','b5q-review22-metal-memory.patch'),('AdrenoMetal','b5q-review23-metal-diagnostics.patch')]:
        path=tree/'drivers'/component;patch=DEVICE/'patches/tools'/name
        reverse=subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=path,capture_output=True)
        if reverse.returncode:
            subprocess.run(['git','apply','--check',str(patch)],cwd=path,check=True)
            subprocess.run(['git','apply',str(patch)],cwd=path,check=True)
        rows.append(dict(component=component,patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest()))
    # Partial component fixtures omit the official runtime builder. Production
    # trees apply this board policy hook before the payload is sealed.
    if (tree/'scripts/build-boot-runtime.py').is_file():
        patch=DEVICE/'patches/tools/b5q-review22-runtime-policy.patch'
        reverse=subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=tree,capture_output=True)
        if reverse.returncode:
            subprocess.run(['git','apply','--check',str(patch)],cwd=tree,check=True)
            subprocess.run(['git','apply',str(patch)],cwd=tree,check=True)
        rows.append(dict(component='runtime-policy',patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest()))
    return rows

def runtime_source_id(tree):
    """Same build ID as the pinned Metal builder; never accept an old addon."""
    root=Path(tree)/'drivers/AdrenoMetal';digest=hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if (path.is_file() and '.git' not in path.parts and
            path.relative_to(root).parts[0]!='tools' and
            path.suffix in ('.h','.mm','.cpp','.rs','.patch')):
            digest.update(str(path.relative_to(root)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()

def runtime_reusable(tree,addon):
    """Read the source stamp sealed inside the existing owner addon."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('b5q_addon_identity',Path(tree)/'scripts/addon-add-dir.py')
    codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)
    rows=codec.read(Path(addon))
    stamps=[json.loads(data) for name,mode,data in rows
            if name.endswith('/NativeAdrenoMetal.bundle/Contents/Resources/gpu-build.json')]
    return len(stamps)==1 and stamps[0].get('target')=='macos27' and stamps[0].get('metal_source_sha256')==runtime_source_id(tree)
