"""Build Java 8 native Forge adapters against hash-pinned official loader APIs."""
from __future__ import annotations
import argparse, hashlib, os, subprocess, urllib.error, urllib.request, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
VERSION='0.1.0'
LOADER={
    '1.7.10':('1.7.10-10.13.4.1614-1.7.10','00d1ca02192c7efb87da95552ebf247021f1e1d642f86d0a03076314def11529'),
    '1.12.2':('1.12.2-14.23.5.2859','bd8314729d787e35164476d75afb337afb9783917e4f6fa1f77f049adba22f2d'),
    '1.16.5':('1.16.5-36.2.34','56d2b1501c74638f07162904e61b6bdd5312f27a3ad1f1f72d40b3818ce08ed7'),
}
DEPENDENCIES={
    'gson.jar':('https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.2.4/gson-2.2.4.jar','c0328cd07ca9e363a5acd00c1cf4afe8cf554bd6d373834981ba05cebec687fb'),
    'netty.jar':('https://repo.maven.apache.org/maven2/io/netty/netty-all/4.0.23.Final/netty-all-4.0.23.Final.jar','50510e9c9874b539b98ef931fe7eeeb002f6b5b1976ea37669b9493426294561'),
    'guava.jar':('https://repo.maven.apache.org/maven2/com/google/guava/guava/17.0/guava-17.0.jar','8c36a80ea613d0b6b8040a17cf837c5bbe3677bc1b06a058a6c174fdb787ebbc'),
    'eventbus.jar':('https://maven.minecraftforge.net/net/minecraftforge/eventbus/4.0.0/eventbus-4.0.0.jar','8754a57ff4d15dffcab15f50b691f4a9c1108b057fbcfff5c915ce928c41f84e'),
}
def fetch(name: str,url: str,expected: str,cache: Path)->Path:
    path=cache/name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        temporary=path.with_suffix('.download')
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 StarBridge-Builder'}),timeout=120) as response:
                temporary.write_bytes(response.read())
        except urllib.error.HTTPError as error:
            if error.code!=403: raise
            subprocess.run(['curl.exe' if os.name=='nt' else 'curl','--fail','--location','--max-time','120','--user-agent','Mozilla/5.0',url,'--output',str(temporary)],check=True)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected: raise ValueError(f'Official dependency checksum mismatch: {name}')
        temporary.replace(path)
    return path

def build(mc: str,jdk: Path,cache: Path)->Path:
    libs=[fetch(name,url,digest,cache) for name,(url,digest) in DEPENDENCIES.items()]
    coordinate,digest=LOADER[mc]
    libs.append(fetch(f'forge-{mc}.jar',f'https://maven.minecraftforge.net/net/minecraftforge/forge/{coordinate}/forge-{coordinate}-universal.jar',digest,cache))
    output=ROOT/'build'/mc/'classes';output.mkdir(parents=True,exist_ok=True)
    sources=sorted((ROOT/'common/src/main/java').rglob('*.java'))+sorted((ROOT/f'forge-{mc}/src/main/java').rglob('*.java'))
    javac=jdk/'bin'/('javac.exe' if os.name=='nt' else 'javac')
    subprocess.run([str(javac),'-J-Duser.language=en','--release','8','-encoding','UTF-8','-cp',os.pathsep.join(map(str,libs)),'-d',str(output)]+list(map(str,sources)),check=True)
    target=ROOT.parent/'bridge/target'/f'StarBridge-Forge-{mc}-{VERSION}.jar';target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for directory in [output,ROOT/f'forge-{mc}/src/main/resources']:
            for path in sorted(directory.rglob('*')):
                if path.is_file():
                    data=path.read_bytes()
                    if path.suffix=='.class' and int.from_bytes(data[6:8],'big')!=52: raise ValueError('Legacy adapter must target Java 8')
                    entry=zipfile.ZipInfo(path.relative_to(directory).as_posix(),(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(entry,data)
        for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
            path=ROOT.parent/name
            if path.is_file():
                entry=zipfile.ZipInfo('META-INF/licenses/StarBridge/'+name,(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(entry,path.read_bytes())
    print(f'Built Forge {mc}: {target.name}',flush=True)
    return target

def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument('--java-home',type=Path,default=Path(os.environ.get('JAVA_HOME','')));parser.add_argument('--version',choices=LOADER);parser.add_argument('--cache',type=Path,default=ROOT/'build/dependencies');args=parser.parse_args()
    args.cache.mkdir(parents=True,exist_ok=True)
    for mc in [args.version] if args.version else LOADER:build(mc,args.java_home,args.cache)
if __name__=='__main__':main()
