"""Apply the complete selected patch series and execute its Edge verifier/helper."""
from pathlib import Path
import tempfile,subprocess,sys,json,re
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'UniXNU/scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu import feeds,patches
ctx=Context(parser().parse_args(['tree','--device',str(root/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
source=root/'sources/UniXNU/out/feeds/xnu-3199e8bc'
def function(s,name):
 m=re.search(r'^'+re.escape(name)+r'\([^;{]*?\)\s*\n\{',s,re.M|re.S)
 assert m,name
 a=m.start();b=s.index('{',a);depth=1;j=b+1
 while depth:
  depth+=(s[j]=='{')-(s[j]=='}');j+=1
 return s[a:j]
with tempfile.TemporaryDirectory(prefix='b5q-v24-core-')as td:
 td=Path(td);tree=td/'xnu'
 subprocess.run(['git','-c','advice.detachedHead=false','clone','--quiet','--shared',str(source),str(tree)],check=True)
 plan=patches.plan(ctx,feeds.resolve(ctx))
 for patch in plan:subprocess.run(['git','-C',str(tree),'apply',str(patch)],check=True)
 s=(tree/'osfmk/kern/sched_clutch.c').read_text();p=(tree/'osfmk/kern/processor.c').read_text()
 a=s.index('\tsched_clutch_edge edge_config_defaults[');b=s.index('#if HAS_MCORE',a);table=s[a:b]
 a=s.index('\t\t\t\tif ((src_pset->pset_type == PSET_AMP_E)');b=s.index('\n\t\t\t\tsched_edge_config_set(',a);exception=s[a:b]
 stub=r'''
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <stdbool.h>
#define MAX_PSET_TYPES 2
#define PSET_AMP_E 0
#define PSET_AMP_P 1
#define TH_BUCKET_FIXPRI 0
#define PERMISSIVE_MIGRATION_BUCKET TH_BUCKET_FIXPRI
#define TH_BUCKET_SHARE_UT 4
#define CLUSTER_TYPE_P 'P'
#define PROCESSOR_SET_NULL NULL
#define PROCESSOR_NULL NULL
#define os_atomic_load(ptr,order) (*(ptr))
#define kprintf printf
#define relaxed 0
#define acquire 0
typedef unsigned pset_id_t,sched_bucket_t;
typedef struct{unsigned sce_migration_weight;bool sce_migration_allowed,sce_steal_allowed;}sched_clutch_edge;
typedef struct{unsigned pset_id,pset_type;} pset;
pset e={0,0},p={1,1};pset *sched_boot_pset=&e,*pset_array[2]={&e,NULL};
typedef struct{unsigned cluster_type,cluster_id;} cluster;
typedef struct{unsigned num_clusters;cluster clusters[2];} ml_topology_info_t;
ml_topology_info_t topo={2,{{'E',0},{'P',1}}};
const ml_topology_info_t *ml_get_topology_info(void){return &topo;}
sched_clutch_edge actual[2][2][6];
sched_clutch_edge sched_edge_config_get(unsigned s,unsigned d,unsigned q){return actual[s][d][q];}
'''
 verifier=function(s,'sched_edge_config_verify_non_decreasing_qos_strictness')
 preferred=function(s,'sched_edge_default_preferred_pset')
 setup='void setup(void){\n'+table+r'''
 for(unsigned src=0;src<2;src++)for(unsigned dst=0;dst<2;dst++)for(unsigned bucket=0;bucket<6;bucket++){
 pset *src_pset=src?&p:&e,*dst_pset=dst?&p:&e;
 sched_clutch_edge edge_config=edge_config_defaults[src][dst];
'''+exception+'\nactual[src][dst][bucket]=edge_config;}}\n'
 idle=function(p,'sheng_cpu_idle_mach')
 recount=r'''
struct recount_usage{unsigned unused;};
struct processor{unsigned pr_recount;};
typedef struct processor *processor_t;
struct processor cpus[8]={{0},{1},{2},{3},{4},{5},{6},{7}};
processor_t cpu_to_processor(int i){return i<0||i>7?NULL:&cpus[i];}
unsigned observed=0;
void recount_processor_usage(unsigned *pr,struct recount_usage *usage,uint64_t *idle){(void)usage;observed++;*idle=1234+*pr;}
'''
 test=r'''
int main(void){
 setup();
 for(unsigned src=0;src<2;src++)for(unsigned dst=0;dst<2;dst++)for(unsigned q=0;q<6;q++)assert(sched_edge_config_verify_non_decreasing_qos_strictness(src,dst,q));
 for(unsigned q=0;q<6;q++){
  assert(!actual[1][0][q].sce_migration_allowed&&!actual[1][0][q].sce_steal_allowed);
  assert(actual[0][1][q].sce_steal_allowed&&actual[0][1][q].sce_migration_allowed==(q==0));
  assert(sched_edge_default_preferred_pset(q)==(q<4?1u:0u));
 }
 actual[1][0][4].sce_migration_allowed=true;assert(!sched_edge_config_verify_non_decreasing_qos_strictness(1,0,4));
 actual[1][0][4].sce_migration_allowed=false;actual[1][0][4].sce_steal_allowed=true;assert(!sched_edge_config_verify_non_decreasing_qos_strictness(1,0,4));
 assert(!sheng_cpu_idle_mach(-1)&&!sheng_cpu_idle_mach(8)&&!observed);
 for(int cpu=0;cpu<8;cpu++)assert(sheng_cpu_idle_mach(cpu)==1234u+(unsigned)cpu);
 assert(observed==8);
 puts("PASS actual patched recount helper and all2x2x6Edge entries against XNU QoS verifier; negative broken matrices rejected");
}
'''
 src=td/'test.c';src.write_text(stub+'static bool\n'+verifier+'\nstatic pset_id_t\n'+preferred+'\n'+setup+recount+'uint64_t\n'+idle+'\n'+test)
 out=td/'test';subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(src),'-o',str(out)],check=True);subprocess.run([str(out)],check=True)
