"""Read local IDX and resolve logical paths without scanning every anonymous bundle."""
from pathlib import Path
from .decoder import schema

def read_resource_manifest(path:Path):
    data=path.read_bytes()
    if len(data)<132: raise ValueError('IDX too short')
    obj=schema('resource_manifest').ROOT_TYPE.GetRootAs(data[128:],0)
    bundles=[]
    if obj.BundlesLength()>1000000 or obj.AssetToBundleListLength()>3000000: raise ValueError('Unreasonable IDX record count')
    for i in range(obj.BundlesLength()):
        item=obj.Bundles(i)
        bundles.append({'name':item.Name().decode('utf-8'),'props':item.Props(),'sccIndex':item.SccIndex(),'dependencies':[item.AllDependencies(j) for j in range(item.AllDependenciesLength())]})
    assets=[]
    for i in range(obj.AssetToBundleListLength()):
        item=obj.AssetToBundleList(i)
        index=item.BundleIndex()
        if not 0<=index<len(bundles): raise ValueError('IDX BundleIndex outside bundle vector')
        row={'bundle_index':index,'bundle':bundles[index]['name']}
        for field in ('AssetName','Name','Path'):
            v=getattr(item,field)();row[field[0].lower()+field[1:]]=v.decode('utf-8') if isinstance(v,bytes) else v
        assets.append(row)
    for b in bundles:
        if any(not 0<=i<len(bundles) for i in b['dependencies']): raise ValueError('IDX dependency outside bundle vector')
    return {'bundles':bundles,'assets':assets,'raw_count':obj.RawCount()}
